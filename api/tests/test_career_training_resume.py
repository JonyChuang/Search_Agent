import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.services.career_task_service import CareerRun, InvalidCareerToolResponse, train


class TrainingResumeTest(IsolatedAsyncioTestCase):
    async def test_resumed_catalog_skips_lookup_and_rebuilds_tool_turn(self):
        catalog = [{"id": "java-hashcode", "version": 1}]
        run = CareerRun(id=uuid4(), lease=uuid4(), userId=uuid4(), kind="TRAINING",
                        context={"role": "backend"}, trainingCatalog=catalog)
        plan = {"analysis": "岗位分析", "steps": ["练习集合"], "questions": catalog}
        model = Mock()
        invoke = model.bind_tools.return_value.ainvoke = AsyncMock(return_value=AIMessage(
            content="", tool_calls=[{"name": "create_training_plan", "args": plan, "id": "call_plan"}],
        ))
        client = Mock(put=AsyncMock(return_value=Mock()))
        with patch("app.services.career_task_service.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            await train(run, model)

        model.bind_tools.assert_called_once()
        self.assertEqual(model.bind_tools.call_args.kwargs["tool_choice"], "create_training_plan")
        messages = invoke.call_args.args[0]
        self.assertIsInstance(messages[-1], ToolMessage)
        self.assertEqual(messages[-1].tool_call_id, messages[-2].tool_calls[0]["id"])
        self.assertEqual(json.loads(messages[-1].content), catalog)
        client.put.assert_awaited_once_with(f"/internal/career/tasks/{run.id}/plan", json=plan)

    async def test_retries_invalid_plan_reply_without_requerying_the_catalog(self):
        catalog = [{"id": "java-hashcode", "version": 1}]
        run = CareerRun(id=uuid4(), lease=uuid4(), userId=uuid4(), kind="TRAINING",
                        context={"role": "backend"}, trainingCatalog=catalog)
        plan = {"analysis": "岗位分析", "steps": ["练习集合"], "questions": catalog}
        model = Mock()
        invoke = model.bind_tools.return_value.ainvoke = AsyncMock(side_effect=[
            AIMessage(content="可以先复习集合。"),
            AIMessage(content="", tool_calls=[{"name": "create_training_plan", "args": plan, "id": "call_plan"}]),
        ])
        client = Mock(put=AsyncMock(return_value=Mock()))
        with patch("app.services.career_task_service.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            await train(run, model)

        self.assertEqual(invoke.await_count, 2)
        retry_messages = invoke.await_args_list[1].args[0]
        self.assertIsInstance(retry_messages[-1], HumanMessage)
        self.assertIn("java-hashcode", retry_messages[-1].content)
        client.put.assert_awaited_once_with(f"/internal/career/tasks/{run.id}/plan", json=plan)

    async def test_refuses_to_save_a_plan_outside_the_checkpointed_catalog(self):
        run = CareerRun(id=uuid4(), lease=uuid4(), userId=uuid4(), kind="TRAINING",
                        context={"role": "backend"}, trainingCatalog=[{"id": "java-hashcode", "version": 1}])
        bad_plan = {"analysis": "岗位分析", "steps": ["练习集合"], "questions": [{"id": "java-hashcode", "version": 2}]}
        model = Mock()
        invoke = model.bind_tools.return_value.ainvoke = AsyncMock(return_value=AIMessage(
            content="", tool_calls=[{"name": "create_training_plan", "args": bad_plan, "id": "call_plan"}],
        ))
        client = Mock(put=AsyncMock())
        with patch("app.services.career_task_service.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            with self.assertRaises(InvalidCareerToolResponse):
                await train(run, model)

        self.assertEqual(invoke.await_count, 2)
        client.put.assert_not_awaited()
