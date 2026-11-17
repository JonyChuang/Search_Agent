import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from uuid import uuid4

import httpx

from app.schemas.chat_schema import ChatStreamRequest
from app.services.career_chat_tools import CareerChatTools, requests_plan
from app.services.chat_service import ChatService


class CareerChatToolsTest(IsolatedAsyncioTestCase):
    def test_creation_requests_are_explicit(self):
        self.assertTrue(requests_plan("请帮我为当前岗位制定一个备考计划。"))
        self.assertTrue(requests_plan("创建备考计划"))
        for text in ("不要创建备考计划", "如何创建备考计划？", "分析附件里的创建备考计划步骤"):
            self.assertFalse(requests_plan(text))

    async def test_explicit_chat_action_uses_the_scoped_job_and_produces_a_task_card(self):
        job_id, request_id, task_id = uuid4(), uuid4(), uuid4()
        request_body = {"jobId": str(job_id), "requestId": str(request_id)}
        request_count = 0

        def handle(request: httpx.Request):
            nonlocal request_count
            request_count += 1
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/api/career/tasks/training")
            self.assertEqual(request.headers["Authorization"], "Bearer fixture")
            self.assertEqual(json.loads(request.content), request_body)
            return httpx.Response(200, json={"code": 0, "data": {"id": str(task_id)}})

        client = httpx.AsyncClient(base_url="http://java.test", headers={"Authorization": "Bearer fixture"},
                                   transport=httpx.MockTransport(handle))
        body = ChatStreamRequest(message="为当前岗位创建备考计划", career_job_id=job_id, career_plan_request_id=request_id)
        with patch("app.services.career_chat_tools.httpx.AsyncClient", return_value=client):
            service = object.__new__(ChatService)
            events = [event async for event in service._generate_events(uuid4(), None, body, [], [], "Bearer fixture")]
        self.assertEqual(request_count, 1)
        self.assertEqual(events[1]["status"], "success")
        self.assertEqual(events[1]["stats"], {"career_job_id": str(job_id), "career_plan_id": str(task_id)})

    async def test_read_tools_are_scoped_without_model_supplied_identifiers(self):
        job_id = uuid4()
        tools = CareerChatTools(job_id, "Bearer fixture")
        headers = {"Authorization": "Bearer fixture"}

        def handle(request: httpx.Request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, f"/api/career/jobs/{job_id}")
            return httpx.Response(200, json={"data": {"company": "示例公司", "title": "示例岗位", "description": "JD"}})

        client = httpx.AsyncClient(base_url="http://java.test", headers=headers, transport=httpx.MockTransport(handle))
        read_job = tools.read_tools()[0]
        self.assertEqual(read_job.args, {})
        with patch("app.services.career_chat_tools.httpx.AsyncClient", return_value=client) as factory:
            self.assertEqual(json.loads(await read_job.ainvoke({}))["title"], "示例岗位")
        self.assertEqual(factory.call_args.kwargs["headers"], headers)
