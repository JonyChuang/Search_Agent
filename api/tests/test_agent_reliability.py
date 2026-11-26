import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpcore

from app.core.agent.tools.mcp import connection, execution
from app.core.exceptions import BizError
from app.core.rag import search
from app.core.rag.search import _distinct_candidates
from eval.career_workflow_eval import run


class AgentReliabilityTest(IsolatedAsyncioTestCase):
    async def test_sensitive_mcp_call_cannot_run_before_owner_confirmation(self):
        user, ident, approval = uuid4(), uuid4(), uuid4()
        server = SimpleNamespace(id=ident, enabled=True, tool_permissions={"write": "confirm"}, updated_at="r1")
        with (patch.object(execution.MCPServerRepository, "get", new=AsyncMock(return_value=server)) as lookup,
              patch.object(execution, "_request_approval", new=AsyncMock(return_value=approval)),
              patch.object(execution, "build_connection") as transport):
            result = await execution.ToolExecutionGuard.invoke_mcp(user, ident, "write", {"value": "sample"})
            self.assertIn(str(approval), result)
            lookup.assert_awaited_once_with(user, ident)
            transport.assert_not_called()
            with self.assertRaises(BizError):
                await execution.ToolExecutionGuard.invoke_mcp(user, ident, "write", {}, approved_revision="old")

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
