"""Store oversized tool observations and expose scoped, paginated references."""

import asyncio
import logging
from uuid import UUID, uuid4

from langchain_core.tools import tool
from redis.exceptions import RedisError
from sqlalchemy import text

from app.core.security import decrypt_secret, encrypt_secret
from app.db.postgres import SessionLocal
from app.db.redis import get_redis
from app.services.career_chat_context import clip

logger = logging.getLogger(__name__)
READ_TOOL = "read_tool_result"
_MAX_RESULT_BYTES = 2_000_000
_MAX_ACTIVE_BYTES = 16_000_000
_MAX_ACTIVE_RESULTS = 128
_READS_PER_MINUTE = 60


async def purge_expired_tool_results(session) -> int:
    result = await session.execute(text("""
        DELETE FROM agent_tool_results WHERE id IN (
            SELECT id FROM agent_tool_results WHERE expires_at <= now()
            ORDER BY expires_at LIMIT 1000 FOR UPDATE SKIP LOCKED
        )
    """))
    return result.rowcount


class ToolResultArchive:
    def __init__(self, user_id: UUID, conversation_id: UUID, job_id: UUID | None = None):
        self.scope = {"user": user_id, "conversation": conversation_id, "job": job_id}

    async def compact(self, name: str, value: str) -> str:
        if name == READ_TOOL:
            return value
        summary = clip(value, 500)
        if summary == value:
            return value
        if len(value.encode()) > _MAX_RESULT_BYTES:
            return "工具返回超过归档上限。以下是可用摘录。\n" + summary
        reference = uuid4()
        try:
            encrypted = encrypt_secret(value)
            async with SessionLocal.begin() as session:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:owner, 0))"),
                    {"owner": f"agent-tool-results:{self.scope['user']}"},
                )
                count, size = (await session.execute(text("""
                    SELECT count(*), COALESCE(sum(octet_length(ciphertext)), 0)
                    FROM agent_tool_results WHERE user_id = :user AND expires_at > now()
                """), self.scope)).one()
                if count >= _MAX_ACTIVE_RESULTS or size + len(encrypted.encode()) > _MAX_ACTIVE_BYTES:
                    return "工具结果归档额度已满。以下为可用摘录。\n" + summary
                await session.execute(text("""
                    INSERT INTO agent_tool_results(id, user_id, conversation_id, job_id, tool, ciphertext, expires_at)
                    VALUES (:id, :user, :conversation, :job, :tool, :ciphertext, now() + interval '7 days')
                """), {**self.scope, "id": reference, "tool": name, "ciphertext": encrypted})
        except Exception as error:
            logger.warning("Tool result archival unavailable type=%s", type(error).__name__)
            return "工具输出暂无法归档。以下是可用摘录。\n" + summary
        return f"工具结果引用 {reference}。可使用 read_tool_result 分页读取。\n{summary}"

    def reader(self):
        @tool(READ_TOOL)
        async def read_tool_result(reference: UUID, offset: int = 0) -> str:
            """读取本对话的工具结果引用。offset 从零开始，后续页使用输出中的 next_offset。"""
            if offset < 0:
                return "无效的读取位置。"
            try:
                async with asyncio.timeout(1), get_redis().pipeline(transaction=True) as pipe:
                    key = f"agent-tool-results:read:{self.scope['user']}"
                    pipe.incr(key)
                    pipe.expire(key, 60, nx=True)
                    reads, _ = await pipe.execute()
            except (RedisError, TimeoutError):
                return "工具结果读取暂不可用，请稍后重试。"
            if reads > _READS_PER_MINUTE:
                return "工具结果读取过于频繁，请稍后重试。"
            async with SessionLocal() as session:
                encrypted = (await session.execute(text("""
                    SELECT ciphertext FROM agent_tool_results WHERE id = :id AND user_id = :user
                        AND conversation_id = :conversation AND job_id IS NOT DISTINCT FROM :job AND expires_at > now()
                """), {**self.scope, "id": reference})).scalar_one_or_none()
            if encrypted is None:
                return "该工具结果不存在或已过期。"
            value = decrypt_secret(encrypted)
            excerpt = value[offset:offset + 1000]
            next_offset = offset + len(excerpt)
            return f"next_offset={next_offset if next_offset < len(value) else 'end'}\n{excerpt}"

        return read_tool_result
