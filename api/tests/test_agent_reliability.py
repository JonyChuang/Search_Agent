import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpcore
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from app.core.agent.tools.mcp import connection, execution
from app.core.exceptions import BizError
from app.core.rag import search
from app.core.rag.chunker import count_tokens
from app.core.rag.search import _distinct_candidates
from app.schemas.chat_schema import ChatStreamRequest
from app.services import career_worker, chat_service
from app.services.career_chat_context import effective_content, summarize, without_constraint_updates
from eval.career_workflow_eval import run


class AgentReliabilityTest(IsolatedAsyncioTestCase):
    async def test_sensitive_mcp_call_cannot_run_before_owner_confirmation(self):
        user, ident, approval = uuid4(), uuid4(), uuid4()
        digest = execution.schema_digest({"type": "object"})
        server = SimpleNamespace(id=ident, enabled=True, tool_permissions={"write": "read"}, updated_at="r1",
                                 tools_cache=[{"name": "write", "schemaDigest": digest}])
        with (patch.object(execution.MCPServerRepository, "get", new=AsyncMock(return_value=server)) as lookup,
              patch.object(execution, "_request_approval", new=AsyncMock(return_value=approval)) as enqueue,
              patch.object(execution, "build_connection") as transport):
            result = await execution.ToolExecutionGuard.invoke_mcp(user, ident, "write", {"value": "sample"})
            self.assertIn(str(approval), result)
            lookup.assert_awaited_once_with(user, ident)
            transport.assert_not_called()
            with self.assertRaises(BizError):
                await execution.ToolExecutionGuard.invoke_mcp(
                    user, ident, "write", {}, approved_revision="old", expected_schema=digest,
                )
            server.tools_cache = [{"name": "write"}]
            with self.assertRaises(BizError):
                await execution.ToolExecutionGuard.invoke_mcp(user, ident, "write", {})
            enqueue.assert_awaited_once()
            transport.assert_not_called()

    async def test_live_schema_and_revocation_are_checked_before_approved_execution(self):
        user, ident = uuid4(), uuid4()
        schema = {"type": "object"}
        digest = execution.schema_digest(schema)
        server = SimpleNamespace(id=ident, enabled=True, tool_permissions={"tool": "confirm"}, updated_at="r1",
                                 tools_cache=[{"name": "tool", "schemaDigest": digest}])
        for live_schema, permissions, should_run in [({}, {}, False), (schema, {}, False),
                                                     (schema, {"tool": "confirm"}, True)]:
            with self.subTest(live_schema=live_schema, permissions=permissions):
                remote = AsyncMock()
                remote.list_tools.return_value = SimpleNamespace(
                    tools=[SimpleNamespace(name="tool", inputSchema=live_schema)], nextCursor=None,
                )
                remote.call_tool.return_value = SimpleNamespace(isError=False, model_dump=lambda **_: {})
                latest = SimpleNamespace(**{**vars(server), "tool_permissions": permissions})
                adapter = MagicMock()
                adapter.session.return_value.__aenter__.return_value = remote
                with (patch.object(execution.MCPServerRepository, "get", new=AsyncMock(side_effect=[server, latest])),
                      patch.object(execution, "build_connection"),
                      patch.object(execution, "MultiServerMCPClient", return_value=adapter)):
                    call = execution.ToolExecutionGuard.invoke_mcp(
                        user, ident, "tool", {}, approved_revision="r1", expected_schema=digest,
                    )
                    if should_run:
                        self.assertEqual(await call, {})
                        remote.call_tool.assert_awaited_once_with("tool", {})
                    else:
                        with self.assertRaises(BizError):
                            await call
                        remote.call_tool.assert_not_awaited()

    def test_authoritative_context_survives_stale_summary_and_deletion(self):
        historical = SimpleNamespace(id=uuid4(), role="user", content="我的求职目标是前端。请保留答题反馈。")
        echo = SimpleNamespace(id=uuid4(), role="assistant", content="已确认，求职目标是前端。")
        active = {"求职目标": [None, "AI Agent 工程"]}
        for state in [active, {}]:
            self.assertNotIn("前端", summarize([historical, echo], state))
            self.assertNotIn("前端", effective_content(echo, state, keep_current=False))
        self.assertEqual(active, {"求职目标": [None, "AI Agent 工程"]})
        self.assertEqual(without_constraint_updates("我的求职目标是什么？\n请解释租约。"), "我的求职目标是什么？\n请解释租约。")
        self.assertEqual(without_constraint_updates(historical.content), "请保留答题反馈。")

    async def test_ordinary_chat_applies_budget_before_the_model(self):
        service = chat_service.ChatService(None)
        service.agent_repo.get_by_user = AsyncMock(return_value=None)
        service.persona_repo.get_active = AsyncMock(return_value=None)
        service._recall_lagged = AsyncMock(return_value="")
        service._tool_scope = AsyncMock(return_value=({}, None))
        service._history_messages = AsyncMock(return_value=[
            HumanMessage(content="old " * 7000), AIMessage(content="answer " * 7000),
        ])
        captured = []

        async def stream(messages):
            captured.extend(messages)
            yield AIMessageChunk(content="fixture answer")

        config = SimpleNamespace(model_name="fixture")
        body = ChatStreamRequest(message="explain leases")
        with (patch.object(chat_service, "build_default_chat_model",
                           new=AsyncMock(return_value=(SimpleNamespace(astream=stream), config))),
              patch.object(chat_service, "build_enabled_tools", new=AsyncMock(return_value=[])),
              patch.object(chat_service.settings, "chat_context_window", 4096),
              patch.object(chat_service.settings, "chat_reserved_output", 512)):
            events = [event async for event in service._generate_events(
                uuid4(), SimpleNamespace(id=uuid4()), body, [{"text": "evidence " * 20000}], [],
            )]
        self.assertEqual(events, [{"type": "token", "text": "fixture answer"}])
        self.assertEqual(len(captured), 2)
        self.assertIn("explain leases", captured[-1].content)
        self.assertLess(sum(count_tokens(message.content) for message in captured), 4096 - 512)

    async def test_ordinary_multimodal_reserves_image_budget_before_provider(self):
        service = chat_service.ChatService(None)
        service.agent_repo.get_by_user = AsyncMock(return_value=None)
        service.persona_repo.get_active = AsyncMock(return_value=None)
        service._recall_lagged = AsyncMock(return_value="")
        service._history_messages = AsyncMock(return_value=[])
        service._stream_multimodal = MagicMock()
        body = ChatStreamRequest(message="analyze the image", image_keys=["image-fixture"])
        with (patch.object(chat_service, "build_default_chat_model", new=AsyncMock(return_value=(None, None))),
              patch.object(chat_service.settings, "chat_context_window", 3000),
              patch.object(chat_service.settings, "chat_reserved_output", 512)):
            events = [event async for event in service._generate_events(
                uuid4(), SimpleNamespace(id=uuid4()), body, [], [],
            )]
        self.assertIn("超出上下文预算", events[0]["text"])
        service._stream_multimodal.assert_not_called()

    async def test_worker_stops_stale_runner_and_releases_on_shutdown(self):
        row = {"id": "test-task", "generation": 2}
        for loses_lease in (True, False):
            with self.subTest(loses_lease=loses_lease):
                started, canceled = asyncio.Event(), asyncio.Event()

                async def run(_row):
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        canceled.set()

                @asynccontextmanager
                async def transaction():
                    yield None

                queue = SimpleNamespace(renew=AsyncMock(return_value=False), release=AsyncMock())
                with (patch.object(career_worker, "run_claimed", run),
                      patch.object(career_worker, "CareerQueue", return_value=queue),
                      patch.object(career_worker, "career_transaction", transaction),
                      patch.object(career_worker, "_LEASE_HEARTBEAT_SECONDS", 0 if loses_lease else 20)):
                    supervised = asyncio.create_task(career_worker.supervise(row))
                    await asyncio.wait_for(started.wait(), 2)
                    if loses_lease:
                        await asyncio.wait_for(supervised, 2)
                        queue.renew.assert_awaited_once_with(row)
                        queue.release.assert_not_awaited()
                    else:
                        supervised.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await asyncio.wait_for(supervised, 2)
                        queue.release.assert_awaited_once_with(row)
                    self.assertTrue(canceled.is_set())

    async def test_global_search_preserves_phrase_and_gates_only_vectors(self):
        def hits(*rows):
            return {"hits": {"hits": [
                {"_id": ident, "_score": score, "_source": {}} for ident, score in rows
            ]}}

        es = SimpleNamespace(search=AsyncMock(side_effect=[
            hits(("exact", 0.55), ("semantic", 0.85), ("weak", 0.51)), hits(("exact", 3.0)),
        ]))
        scope = [{"term": {"user_id": "fixture"}}]
        _, ranked, scores, _ = await search._rank_candidates(es, scope, "Java volatile", [0.5], 10, 0.45)
        self.assertEqual(ranked, ["exact", "semantic"])
        self.assertAlmostEqual(scores["semantic"], 0.7)
        self.assertEqual(es.search.await_args_list[0].kwargs["body"]["knn"]["filter"], {"bool": {"filter": scope}})
        phrase = es.search.await_args_list[1].kwargs["body"]["query"]["bool"]
        self.assertEqual(phrase["must"], [{"match_phrase": {"content": "Java volatile"}}])
        self.assertEqual(phrase["filter"], scope)
        es.search = AsyncMock(return_value=hits(("exact", 3.0)))
        self.assertEqual((await search._rank_candidates(es, scope, "Java volatile", [], 10, 0.45))[1], ["exact"])
        es.search.assert_awaited_once()

    async def test_only_validated_addresses_reach_the_network_backend(self):
        backend = connection.PublicNetworkBackend()
        loop = asyncio.get_running_loop()
        returned = [(None, None, None, None, ("8.8.8.8", 443))]
        with (patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=returned)),
              patch.object(connection.AnyIOBackend, "connect_tcp", new=AsyncMock()) as dial):
            await backend.connect_tcp("service.example", 443)
            dial.assert_awaited_once_with("8.8.8.8", 443, None, None, None)
        with (patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=[])),
              patch.object(connection.AnyIOBackend, "connect_tcp", new=AsyncMock()) as dial):
            with self.assertRaises(httpcore.ConnectError):
                await backend.connect_tcp("service.example", 443)
            dial.assert_not_awaited()

    async def test_workflow_eval_reports_model_calls_and_recovery_separately(self):
        result = await run()
        self.assertEqual(result["constraints"], [4, 4])
        self.assertEqual(result["task_success"], [4, 4])
        self.assertEqual(result["correct_tool_calls"], [4, 6])
        self.assertEqual(result["checkpoint_recovery"], [2, 2])

    def test_parent_coverage_is_scoped_by_document_and_knowledge_base(self):
        shared = {"source_id": "doc-a", "kb_id": "kb-a", "parent_id": "parent-a"}
        hits = {"a": shared, "b": dict(shared), "c": {**shared, "source_id": "doc-b"}}
        self.assertEqual(_distinct_candidates(hits, hits.keys()), 2)

    async def test_parent_shortfall_expands_once_and_embeds_once(self):
        shared = {"source_id": "doc", "kb_id": "kb", "parent_id": "parent", "content": "part"}
        initial = {"a": shared, "b": dict(shared)}
        enlarged = {**initial, "c": {**shared, "parent_id": "other"}}
        embed = AsyncMock(return_value=[0.3])
        rank = AsyncMock(side_effect=[(initial, ["a", "b"], {}, True), (enlarged, ["a", "b", "c"], {}, True)])
        collect = AsyncMock(return_value=[{}, {}])
        with (patch.object(search, "get_es"),
              patch.object(search, "get_client_for_type", new=AsyncMock(return_value=SimpleNamespace(embed_one=embed))),
              patch.object(search, "get_optional_client_for_type", new=AsyncMock(return_value=None)),
              patch.object(search, "_rank_candidates", new=rank), patch.object(search, "_collect_results", new=collect)):
            self.assertEqual(len(await search.hybrid_search(None, uuid4(), "example", 2, 2)), 2)
        embed.assert_awaited_once()
        self.assertEqual(rank.await_count, 2)
        self.assertGreater(rank.await_args_list[1].args[4], rank.await_args_list[0].args[4])
