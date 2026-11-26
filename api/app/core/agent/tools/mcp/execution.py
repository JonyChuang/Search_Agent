"""Owner-scoped MCP permissions and short-lived, single-use write approvals."""

import asyncio
import json
import logging
from hashlib import sha256
from time import time
from uuid import UUID, uuid4

from langchain_mcp_adapters.client import MultiServerMCPClient
from redis.exceptions import RedisError

from app.core.agent.tools.mcp.connection import build_connection
from app.core.exceptions import BizError
from app.core.security import decrypt_secret, encrypt_secret
from app.db.postgres import SessionLocal
from app.db.redis import get_redis
from app.repositories.mcp_server_repository import MCPServerRepository

logger = logging.getLogger(__name__)
_TTL = 300
_MAX_PENDING = 20


def schema_digest(schema: dict) -> str:
    return sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()


def _reviewed_schema(server, name: str) -> str | None:
    return next((item.get("schemaDigest") for item in (server.tools_cache or []) if item["name"] == name), None)


def _queue(user_id: UUID) -> str:
    return f"mcp:approval:{{{user_id}}}:pending"


def _key(user_id: UUID, request_id: UUID) -> str:
    return f"mcp:approval:{{{user_id}}}:{request_id}"


def _preview(value):
    if isinstance(value, dict):
        return {key: "[已隐藏]" if any(part in key.lower() for part in (
            "password", "secret", "token", "authorization", "credential", "api_key", "apikey",
        )) else _preview(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_preview(item) for item in value]
    return value


async def _request_approval(user_id, server, tool: str, arguments: dict) -> UUID:
    return await _enqueue(user_id, {
        "server": str(server.id), "name": server.name, "revision": str(server.updated_at),
        "tool": tool, "arguments": arguments, "schemaDigest": _reviewed_schema(server, tool),
    })


async def request_schedule_approval(user_id: UUID, arguments: dict) -> UUID:
    return await _enqueue(user_id, {"server": None, "name": "定时研究", "tool": "create_scheduled_task",
                                    "arguments": arguments})


async def _enqueue(user_id: UUID, entry: dict) -> UUID:
    request_id = uuid4()
    now = int(time())
    record = json.dumps({**entry, "expiresAt": now + _TTL}, ensure_ascii=False)
    if len(record.encode()) > 24_000:
        raise BizError("工具参数过长，无法生成待确认操作", code=400, status_code=400)
    try:
        async with asyncio.timeout(1), get_redis().pipeline(transaction=True) as pipe:
            queue = _queue(user_id)
            pipe.set(_key(user_id, request_id), encrypt_secret(record), ex=_TTL)
            pipe.zremrangebyscore(queue, "-inf", now - _TTL)
            pipe.zadd(queue, {str(request_id): now})
            pipe.zremrangebyrank(queue, 0, -(_MAX_PENDING + 1))
            pipe.expire(queue, _TTL)
            await pipe.execute()
    except (RedisError, TimeoutError) as error:
        raise BizError("操作确认服务暂不可用", code=503, status_code=503) from error
    return request_id


async def pending_approvals(user_id: UUID) -> list[dict]:
    try:
        async with asyncio.timeout(1):
            redis = get_redis()
            ids = await redis.zrevrange(_queue(user_id), 0, _MAX_PENDING - 1)
            if not ids:
                return []
            payloads = await redis.mget([_key(user_id, UUID(value)) for value in ids])
    except (RedisError, TimeoutError) as error:
        raise BizError("操作确认服务暂不可用", code=503, status_code=503) from error
    pending = []
    for request_id, payload in zip(ids, payloads, strict=True):
        if payload:
            row = json.loads(decrypt_secret(payload))
            pending.append({"id": request_id, "server": row["name"], "tool": row["tool"],
                            "arguments": _preview(row["arguments"]), "expiresAt": row["expiresAt"]})
    return pending


class ToolExecutionGuard:
    @staticmethod
    async def _authorized_server(user_id: UUID, server_id: UUID, tool: str, revision=None, expected_schema=None):
        async with SessionLocal() as session:
            server = await MCPServerRepository(session).get(user_id, server_id)
            mode = (server.tool_permissions or {}).get(tool) if server and server.enabled else None
            reviewed = _reviewed_schema(server, tool) if mode in {"read", "confirm"} else None
            if (not reviewed or (expected_schema is not None and expected_schema != reviewed)
                    or (revision is not None and (revision != str(server.updated_at) or expected_schema != reviewed))):
                logger.info("tool authorization denied owner=%s server=%s tool=%s", user_id, server_id, tool)
                raise BizError("MCP 工具未授权或权限已变更", code=403, status_code=403)
            return server

    @classmethod
    async def invoke_mcp(cls, user_id: UUID, server_id: UUID, tool: str, arguments: dict, *,
                         approved_revision=None, expected_schema=None):
        server = await cls._authorized_server(user_id, server_id, tool, approved_revision, expected_schema)
        # Every external server is untrusted for side effects, including existing `read` grants.
        if approved_revision is None:
            approval = await _request_approval(user_id, server, tool, arguments)
            return f"工具尚未执行。请在工具配置的 MCP 待确认区域查看并审批请求 {approval}。"
        try:
            connection = build_connection(server)
            async with asyncio.timeout(45):
                async with MultiServerMCPClient({"tool": connection}).session("tool") as remote:
                    cursor = None
                    for _ in range(32):
                        page = await remote.list_tools(cursor=cursor)
                        matching = next((item for item in page.tools if item.name == tool), None)
                        if matching is not None:
                            break
                        cursor = page.nextCursor
                        if not cursor:
                            break
                    if matching is None or schema_digest(matching.inputSchema) != expected_schema:
                        raise BizError("远程工具定义已变更，请重新同步后发起审批", code=409, status_code=409)
                    await cls._authorized_server(user_id, server_id, tool, approved_revision, expected_schema)
                    result = await remote.call_tool(tool, arguments)
        except BizError:
            raise
        except Exception as error:
            logger.warning("MCP call failed owner=%s server=%s tool=%s type=%s", user_id, server_id, tool,
                           type(error).__name__)
            raise BizError("无法确认 MCP 操作结果，请检查远程服务状态", code=502, status_code=502) from None
        logger.info("MCP call completed owner=%s server=%s tool=%s error=%s", user_id, server_id, tool, result.isError)
        if result.isError:
            raise BizError("远程 MCP 工具返回执行错误", code=502, status_code=502)
        return result.model_dump(mode="json", by_alias=True)


async def decide_approval(user_id: UUID, request_id: UUID, approve: bool):
    try:
        async with asyncio.timeout(1), get_redis().pipeline(transaction=True) as pipe:
            pipe.getdel(_key(user_id, request_id))
            pipe.zrem(_queue(user_id), str(request_id))
            payload, _ = await pipe.execute()
    except (RedisError, TimeoutError) as error:
        raise BizError("操作确认服务暂不可用", code=503, status_code=503) from error
    if not payload:
        raise BizError("待确认操作已过期或已处理", code=404, status_code=404)
    if not approve:
        return None
    row = json.loads(decrypt_secret(payload))
    if row["server"] is None:
        from app.repositories.tool_config_repository import ToolConfigRepository
        from app.schemas.agent_task_schema import AgentTaskUpsertRequest
        from app.services.agent_task_service import AgentTaskService

        async with SessionLocal() as session:
            configurations = await ToolConfigRepository(session).list_by_user(user_id)
            if any(config.tool_key == row["tool"] and not config.enabled for config in configurations):
                raise BizError("定时研究工具已关闭", code=403, status_code=403)
            task = await AgentTaskService(session).create(user_id, AgentTaskUpsertRequest.model_validate(row["arguments"]))
            logger.info("Scheduled task approved owner=%s request=%s", user_id, request_id)
            return {"id": str(task.id)}
    return await ToolExecutionGuard.invoke_mcp(user_id, UUID(row["server"]), row["tool"], row["arguments"],
                                              approved_revision=row["revision"], expected_schema=row.get("schemaDigest"))
