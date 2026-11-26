"""Opt-in integration tests against local PostgreSQL and Redis."""

import asyncio
import os
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select, text

from app.config import settings
from app.core.agent.tools.mcp import execution
from app.core.exceptions import BizError
from app.core.realtime import chat_events
from app.core.security import create_access_token
from app.db.postgres import SessionLocal, close
from app.main import create_app
from app.models.agent_runtime_model import agent_tool_results
from app.models.conversation_model import Conversation, Message
from app.models.mcp_server_model import MCPServer
from app.models.user_model import User
from app.services import career_worker, tool_results
from app.services.career_context_versions import CareerContextVersions
from app.services.chat_service import ChatService, bus


@skipUnless(os.getenv("RUN_AGENT_RUNTIME_INTEGRATION") == "1", "requires local PostgreSQL and Redis")
class RuntimeIntegrationTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        loopback = {"localhost", "127.0.0.1", "::1"}
        if settings.postgres_host not in loopback or urlsplit(settings.redis_url).hostname not in loopback:
            self.fail("Use disposable local PostgreSQL and Redis instances")
        self.addAsyncCleanup(close)
        self.owner, self.other, self.conv, self.job = uuid4(), uuid4(), uuid4(), uuid4()
        self.redis_a = Redis.from_url(settings.redis_url, decode_responses=True)
        self.redis_b = Redis.from_url(settings.redis_url, decode_responses=True)
        self.addAsyncCleanup(self.redis_a.aclose)
        self.addAsyncCleanup(self.redis_b.aclose)
        await self.redis_a.ping()
        async with SessionLocal.begin() as session:
            session.add(User(id=self.owner, username=f"verify-{self.owner.hex}", password_hash="fixture"))
            session.add(User(id=self.other, username=f"verify-{self.other.hex}", password_hash="fixture"))
            await session.flush()
            session.add(Conversation(id=self.conv, user_id=self.owner, is_group=False))
        self.addAsyncCleanup(self.remove_user)

    async def remove_user(self):
        async with SessionLocal.begin() as session:
            await session.execute(delete(User).where(User.id.in_([self.owner, self.other])))

    def auth(self, user=None, **extra):
        return {"Authorization": f"Bearer {create_access_token(str(user or self.owner))}", **extra}

    async def remove_redis_keys(self, *keys):
        await self.redis_a.delete(*keys)

    async def test_context_versions_concurrent_update_deletion_and_explicit_rollback(self):
        historic = Message(conversation_id=self.conv, role="user", content="我的求职目标是前端。",
                           meta_data={"career_job_id": str(self.job)})
        async with SessionLocal() as session:
            versions = CareerContextVersions(session, self.owner, self.conv, self.job)
            original = await versions.save(message=historic)
            self.assertEqual((await session.get(Message, historic.id)).content, historic.content)
        self.assertEqual(original["version"], 1)

        async def update(value):
            async with SessionLocal() as session:
                versions = CareerContextVersions(session, self.owner, self.conv, self.job)
                return await versions.save(expected=1, edits={"求职目标": value})

        results = await asyncio.gather(update("AI Agent"), update("Java"), return_exceptions=True)
        self.assertEqual([result.status_code for result in results if isinstance(result, BizError)], [409])
        self.assertEqual([result["version"] for result in results if isinstance(result, dict)], [2])
        async with SessionLocal() as session:
            versions = CareerContextVersions(session, self.owner, self.conv, self.job)
            await versions.save(expected=2, edits={"求职目标": None})
        async with SessionLocal() as session:
            versions = CareerContextVersions(session, self.owner, self.conv, self.job)
            self.assertEqual((await versions.read())["state"], {})
            _, summary, pinned = await ChatService(session)._job_history(self.owner, self.conv, self.job)
            self.assertNotIn("前端", summary + pinned)
            restored = await versions.save(expected=3, rollback=1)
            self.assertEqual(restored["state"], original["state"])
            self.assertEqual(restored["version"], 4)

    async def test_stream_resumes_across_app_instances_and_checks_owner(self):
        stream = chat_events.ChatEventStream(str(self.conv), str(uuid4()))
        self.addAsyncCleanup(self.remove_redis_keys, stream.key, stream.marker(str(self.conv)))
        first, second = create_app(), create_app()
        async with (asyncio.timeout(15),
                    AsyncClient(transport=ASGITransport(app=first), base_url="http://instance-a") as a,
                    AsyncClient(transport=ASGITransport(app=second), base_url="http://instance-b") as b):
            url = f"/api/chat/{self.conv}/events"
            with patch.object(chat_events, "get_redis", return_value=self.redis_a):
                await stream.start()
                await stream.publish("token", {"text": "first token", "i": 0})
                await stream.publish("token", {"text": "second token", "i": 1})
                await stream.publish("done", {"conversation_id": str(self.conv)})
                original = await a.get(url, headers=self.auth(**{"Last-Event-ID": f"{stream.turn}:0-0"}))
                self.assertEqual(original.status_code, 200)
                self.assertIn("first token", original.text)
            with (patch.object(chat_events, "get_redis", return_value=self.redis_b),
                  patch.object(bus, "get_redis", return_value=self.redis_b)):
                replay = await b.get(url, headers=self.auth(**{"Last-Event-ID": f"{stream.turn}:1-0"}))
                self.assertEqual(replay.status_code, 200)
                self.assertNotIn("first token", replay.text)
                self.assertIn("second token", replay.text)
                self.assertEqual(re.findall(r"(?m)^id: (.*)$", replay.text),
                                 [f"{stream.turn}:2-0", f"{stream.turn}:3-0"])
                completed = await b.get(url, headers=self.auth(**{"Last-Event-ID": f"{stream.turn}:3-0"}))
                self.assertIn("event: idle", completed.text)
                await self.redis_b.delete(stream.key)
                await self.redis_b.delete(stream.marker(str(self.conv)))
                expired = await b.get(url, headers=self.auth(**{"Last-Event-ID": f"{stream.turn}:2-0"}))
                self.assertIn("event: idle", expired.text)
                forbidden = await b.get(url, headers=self.auth(self.other, **{"Last-Event-ID": f"{stream.turn}:1-0"}))
                self.assertIn("会话不存在", forbidden.text)

    async def test_approval_consumption_is_atomic_across_clients_and_owner_scoped(self):
        schema = {"type": "object"}
        digest = execution.schema_digest(schema)
        async with SessionLocal.begin() as session:
            server = MCPServer(user_id=self.owner, name="fixture", url="https://example.invalid/mcp",
                               tools_cache=[{"name": "one", "schemaDigest": digest}], tool_permissions={"one": "read"})
            session.add(server)
        with patch.object(execution, "get_redis", return_value=self.redis_a):
            await execution.ToolExecutionGuard.invoke_mcp(self.owner, server.id, "one", {"value": "fixture"})
            consent = UUID((await execution.pending_approvals(self.owner))[0]["id"])
            expired = await execution._request_approval(self.owner, server, "one", {})
        key = execution._key(self.owner, expired)
        self.addAsyncCleanup(self.remove_redis_keys, key, execution._key(self.owner, consent), execution._queue(self.owner))
        await self.redis_a.expire(key, 0)
        remote = AsyncMock()
        remote.list_tools.return_value = SimpleNamespace(
            tools=[SimpleNamespace(name="one", inputSchema=schema)], nextCursor=None,
        )
        remote.call_tool.return_value = SimpleNamespace(isError=False, model_dump=lambda **_: {"fixture": True})
        adapter = MagicMock()
        adapter.session.return_value.__aenter__.return_value = remote
        async with (asyncio.timeout(15),
                    AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://instance-a") as a,
                    AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://instance-b") as b):
            with (patch.object(execution, "get_redis", side_effect=[
                self.redis_a, self.redis_b, self.redis_a, self.redis_b,
            ]), patch.object(execution, "build_connection"),
                  patch.object(execution, "MultiServerMCPClient", return_value=adapter)):
                request = {"approve": True}
                path = "/api/tools/mcp/approvals/"
                unauthenticated = await a.post(path + str(consent), json=request)
                self.assertEqual(unauthenticated.status_code, 401)
                for owner, item in [(self.other, consent), (self.owner, expired)]:
                    response = await a.post(path + str(item), json=request, headers=self.auth(owner))
                    self.assertEqual(response.status_code, 404)
                results = await asyncio.gather(
                    a.post(path + str(consent), json=request, headers=self.auth()),
                    b.post(path + str(consent), json=request, headers=self.auth()),
                )
                self.assertEqual(sorted(result.status_code for result in results), [200, 404])
                remote.call_tool.assert_awaited_once_with("one", {"value": "fixture"})

    async def test_tool_archive_serializes_quota_and_preserves_scoped_readback(self):
        value = "完整结果 with evidence. " * 300
        archive = tool_results.ToolResultArchive(self.owner, self.conv)
        with patch.object(tool_results, "_MAX_ACTIVE_RESULTS", 1):
            outcomes = await asyncio.gather(*(archive.compact("fixture", value) for _ in range(2)))
        self.assertEqual(sum("额度已满" in outcome for outcome in outcomes), 1)
        ref = UUID(next(re.search(r"[0-9a-f-]{36}", outcome)[0] for outcome in outcomes if "工具结果引用" in outcome))
        key = f"agent-tool-results:read:{self.owner}"
        self.addAsyncCleanup(self.remove_redis_keys, key)
        with (patch.object(tool_results, "get_redis", side_effect=[self.redis_a, self.redis_b, self.redis_b]),
              patch.object(tool_results, "_READS_PER_MINUTE", 2)):
            other_scope = tool_results.ToolResultArchive(self.owner, self.conv, self.job)
            self.assertIn("已过期", await other_scope.reader().ainvoke({"reference": ref}))
            answer = await archive.reader().ainvoke({"reference": ref})
            self.assertEqual(answer, f"next_offset=1000\n{value[:1000]}")
            self.assertIn("过于频繁", await archive.reader().ainvoke({"reference": ref, "offset": 1000}))
        async with SessionLocal.begin() as session:
            await session.execute(text("UPDATE agent_tool_results SET expires_at = now() WHERE id = :id"), {"id": ref})
            # Keep deletions of any unrelated local expired fixtures inside a savepoint.
            async with session.begin_nested() as savepoint:
                await tool_results.purge_expired_tool_results(session)
                self.assertIsNone(await session.scalar(
                    select(agent_tool_results.c.id).where(agent_tool_results.c.id == ref),
                ))
                await savepoint.rollback()

    async def test_queue_alert_persists_deduplicates_and_clears(self):
        async with SessionLocal.begin() as session:
            await session.execute(text("""
                CREATE TEMP TABLE career_queue_samples (LIKE public.career_queue_samples INCLUDING ALL) ON COMMIT DROP
            """))

            @asynccontextmanager
            async def begin():
                yield session

            with (patch.object(career_worker, "SessionLocal", SimpleNamespace(begin=begin)),
                  self.assertLogs(career_worker.logger, level="INFO") as logs):
                await career_worker.record_queue_sample(3, 1, 310)
                await career_worker.record_queue_sample(2, 1, 310)
                await session.execute(text("UPDATE career_queue_samples SET sampled_at = sampled_at - interval '1 minute'"))
                await career_worker.record_queue_sample(0, 0, 0)
            rows = (await session.execute(text("SELECT queued, alert FROM career_queue_samples ORDER BY sampled_at"))).all()
            self.assertEqual(rows, [(3, True), (0, False)])
            self.assertEqual(sum("transition=raised" in line for line in logs.output), 1)
            self.assertEqual(sum("transition=cleared" in line for line in logs.output), 1)
