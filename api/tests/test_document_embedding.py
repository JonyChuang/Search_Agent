import asyncio
from unittest import TestCase
from unittest.mock import patch

import httpx

from app.core.llm.client import LLMClient, is_provider_quota_error, llm_task_connections


class DocumentEmbeddingTest(TestCase):
    def test_each_task_uses_its_own_client_and_quota_error_is_not_retried(self):
        clients = []
        loops = []

        def new_client():
            loop = asyncio.get_running_loop()
            loops.append(loop)
            calls = 0

            async def respond(request):
                nonlocal calls
                self.assertIs(asyncio.get_running_loop(), loop)
                calls += 1
                self.assertEqual(calls, 1)
                return httpx.Response(429, json={"error": {"code": "1113"}})

            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            clients.append(client)
            return client

        async def run_task():
            async with llm_task_connections():
                with self.assertRaises(httpx.HTTPStatusError) as failure:
                    await LLMClient("https://test.invalid", "test", "embedding-3").embed(["test"])
                self.assertTrue(is_provider_quota_error(failure.exception.response))

        with patch("app.core.llm.client._new_client", side_effect=new_client):
            asyncio.run(run_task())
            asyncio.run(run_task())

        self.assertIsNot(loops[0], loops[1])
        self.assertEqual(len(clients), 2)
        self.assertTrue(all(client.is_closed for client in clients))
