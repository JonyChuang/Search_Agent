"""Regression checks for the native career routes and context."""

import asyncio
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet
from langchain_core.messages import AIMessage, HumanMessage
from mcp.types import Tool
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import settings
from app.core.agent.tools.mcp import tool_cache
from app.core.memory.retrieval import embedding_cache
from app.core.rag.search import _collect_results
from app.main import create_app
from app.services.career_chat_context import effective_content, fit_turn, latest_constraints


class NativeRoutesTest(unittest.TestCase):
    def test_legacy_public_routes_have_native_equivalents(self):
        root = Path(__file__).resolve().parents[2] / "backend" / "src" / "main" / "java"
        if not root.is_dir():
            self.skipTest("Legacy route inventory requires the repository checkout")

        def normalize(path):
            return re.sub(r"\{[^}]+\}", "{}", path).rstrip("/")

        legacy = {("GET", "/api/career/health")}
        for source in root.rglob("*.java"):
            blocks = re.split(r'@RequestMapping\("([^"]+)"\)', source.read_text(encoding="utf-8"))
            for prefix, block in zip(blocks[1::2], blocks[2::2], strict=True):
                if not prefix.startswith("/api/career"):
                    continue
                for match in re.finditer(r'@(Get|Post|Put|Patch|Delete)Mapping\b(?:\((?:value\s*=\s*)?"([^"]*)")?', block):
                    legacy.add((match[1].upper(), normalize(prefix + (match[2] or ""))))
        routes = {(method, normalize(route.path)) for route in create_app().routes
                  for method in getattr(route, "methods", ())}
        self.assertGreaterEqual(len(legacy), 80)
        self.assertEqual(legacy - routes, set())

    def test_low_budget_preserves_complete_turns(self):
        history = [HumanMessage(content="first " * 500), AIMessage(content="reply " * 500),
                   HumanMessage(content="second"), AIMessage(content="reply")]
        question, kept = fit_turn(1150, 200, "system", [], "current question", [], history)
        self.assertEqual(question, "current question")
        self.assertEqual(kept, history[2:])


class NativeOptimizationsTest(unittest.IsolatedAsyncioTestCase):
    async def test_job_constraints_survive_recent_window_and_ignore_superseded_value(self):
        old = SimpleNamespace(id=uuid4(), role="user", content="截止时间是周三。\n复习顺序是先 SQL 再 Redis。")
        recent = SimpleNamespace(id=uuid4(), role="user", content="截止时间改为周五。",
                                 meta_data={"career_constraints": {"截止时间": "截止时间改为周五。"}})

        async def rows():
            yield recent
            for count in range(100):
                yield SimpleNamespace(id=count, role="user", content="谢谢")
            yield old

        current = await latest_constraints(rows())
        self.assertEqual(set(current), {"截止时间", "复习顺序"})
        self.assertEqual(current["截止时间"][0], str(recent.id))
        self.assertEqual(effective_content(old, current), "复习顺序是先 SQL 再 Redis。")

    async def test_rag_deduplicates_parent_and_backfills_missing_parent(self):
        parent = {"chunk_id": "p", "source_id": "doc", "kb_id": "kb", "content": "combined"}
        picked = {"source_id": "doc", "kb_id": "kb", "parent_id": "p", "content": "child"}
        hits = {"a": picked, "duplicate": picked, "b": {**picked, "source_id": "other", "content": "fallback"}}
        es = SimpleNamespace(search=AsyncMock(return_value={"hits": {"hits": [{"_source": parent}]}}))
        result = await _collect_results(es, "user", hits, list(hits), {"a": 0.9, "duplicate": 0.8, "b": 0.7}, 2)
        self.assertEqual([(item["chunk_id"], item["content"]) for item in result], [("a", "combined"), ("b", "fallback")])
        es.search.assert_awaited_once()
        self.assertIn({"term": {"user_id": "user"}}, es.search.call_args.kwargs["body"]["query"]["bool"]["filter"])

    async def test_mcp_loads_shared_descriptors_once_and_isolates_revisions(self):
        entries = {}

        class Redis:
            async def get(self, key):
                return entries.get(key)

            async def set(self, key, value, **options):
                if options.get("nx") and key in entries:
                    return False
                entries[key] = value
                return True

            async def eval(self, script, key_count, key, *args):
                if key_count == 1 and entries.get(key) == args[0]:
                    entries.pop(key)
                elif key_count == 2 and entries.get(args[0]) == args[1]:
                    entries[key] = args[2]

        async def fetch():
            await asyncio.sleep(0.02)
            return [Tool(name="example", inputSchema={"type": "object"})]

        fetcher = AsyncMock(side_effect=fetch)
        with patch.object(tool_cache, "get_redis", return_value=Redis()):
            results = await asyncio.gather(*[tool_cache.load_descriptors("u", "server", "rev1", fetcher) for _ in range(2)])
            fetcher.assert_awaited_once()
            self.assertEqual(results[0], results[1])
            await tool_cache.load_descriptors("u", "server", "rev2", fetcher)
            await tool_cache.load_descriptors("other", "server", "rev1", fetcher)
            self.assertEqual(fetcher.await_count, 3)

    async def test_memory_cache_reuses_encrypted_vectors_with_user_scope_and_fallback(self):
        entries = {}

        async def set_value(key, value, *, ex):
            self.assertEqual(ex, 120)
            entries[key] = value

        redis = SimpleNamespace(get=AsyncMock(side_effect=entries.get), set=AsyncMock(side_effect=set_value))
        embed = AsyncMock(return_value=[0.5, 1.0])
        client = SimpleNamespace(base_url="https://embedding.test", model_name="test", api_key="credential", embed_one=embed)
        user = uuid4()
        with patch.multiple(settings, memory_shared_recall_cache_enabled=True, embedding_dims=2,
                            fernet_key=Fernet.generate_key().decode()), patch.object(
            embedding_cache, "get_redis", return_value=redis,
        ):
            self.assertEqual(await embedding_cache.recall_embedding(client, user, "question"), [0.5, 1.0])
            self.assertEqual(await embedding_cache.recall_embedding(client, user, "question"), [0.5, 1.0])
            embed.assert_awaited_once()
            key, value = next(iter(entries.items()))
            self.assertNotIn("question", key)
            self.assertNotIn("0.5", value)
            await embedding_cache.recall_embedding(client, uuid4(), "question")
            redis.get.side_effect = RedisConnectionError("unavailable")
            redis.set.side_effect = RedisConnectionError("unavailable")
            self.assertEqual(await embedding_cache.recall_embedding(client, user, "question"), [0.5, 1.0])
            self.assertEqual(embed.await_count, 3)
