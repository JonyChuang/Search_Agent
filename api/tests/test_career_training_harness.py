from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.services.career_chat_context import fit_agent_round
from app.services.career_chat_tools import CareerChatTools, CareerToolError
from app.services.career_question_catalog import order_questions
from app.services.career_task_service import CareerRun, execute_training
from app.services.career_training_harness import explain_learning, learn_from_attempts, learning_candidates


def attempt(question, *, correct=False, version=1):
    return {"questionId": question, "questionVersion": version, "topic": "Redis",
            "attemptId": str(uuid4()), "correct": correct}


def question(question_id, topic, version=1):
    return {"id": question_id, "version": version, "topic": topic, "prompt": f"Explain {topic}"}


class LearningPolicyTest(TestCase):
    def test_latest_attempt_wins_and_repetition_does_not_create_evidence(self):
        job = {"skills": "Redis / Java"}
        self.assertIsNone(learn_from_attempts([attempt("a"), attempt("a")], job))
        self.assertIsNone(learn_from_attempts([attempt("a", version=2), attempt("a")], job))
        self.assertIsNone(learn_from_attempts([attempt("a", correct=True), attempt("a"), attempt("b")], job))
        self.assertIsNone(learn_from_attempts([attempt("a"), attempt("b")], {"skills": "Java"}))
        self.assertEqual(learn_from_attempts([attempt("a"), attempt("b")], job)["priorities"][0]["misses"], 2)

    def test_keeps_selected_question_and_prioritizes_unseen_version(self):
        job = {"skills": "Redis / MySQL / Spring"}
        learning = learn_from_attempts([attempt("previous"), attempt("other")], job)
        catalog = [question("previous", "Redis"), question("mysql", "MySQL"), question("spring", "Spring"),
                   question("previous", "Redis", 2), {**question("older", "Redis"), "practiceCompleted": True}]
        targets = learning_candidates(catalog, learning)
        self.assertEqual(list(targets), [("previous", 2)])
        plan = order_questions(catalog, job, "spring", targets)[:3]
        self.assertEqual([(q["id"], q["version"]) for q in plan], [("spring", 1), ("previous", 2), ("mysql", 1)])
        self.assertEqual(explain_learning(plan, catalog, learning)["priorities"][0]["status"], "SELECTED")
        self.assertEqual(explain_learning(plan[:1], catalog, learning)["priorities"][0]["status"], "AVAILABLE")

    def test_context_budget_keeps_tool_protocol_and_discards_old_turn(self):
        history = [SystemMessage(content="system"), HumanMessage(content="old " * 800), AIMessage(content="reply")]
        tool_call = AIMessage(content="", tool_calls=[{"id": "call_1", "args": {}, "name": "get"}])
        result = ToolMessage(content="data " * 2000, tool_call_id="call_1")
        messages = [*history, HumanMessage(content="current"), tool_call, result]
        fitted = fit_agent_round(1200, 200, 20, messages, 3)
        self.assertEqual([message.type for message in fitted], ["system", "human", "ai", "tool"])
        self.assertEqual(fitted[-1].tool_call_id, "call_1")
        self.assertLess(len(fitted[-1].content), len(result.content))
        self.assertIsNone(fit_agent_round(530, 200, 20, messages, 3))


class HarnessIntegrationTest(IsolatedAsyncioTestCase):
    async def test_native_lookup_skips_model_and_retries_with_validation_feedback(self):
        job = {"skills": "Redis"}
        learning = learn_from_attempts([attempt("previous"), attempt("other")], job)
        run = CareerRun(id=uuid4(), lease=uuid4(), userId=uuid4(), kind="TRAINING", context={"job": job},
                        practiceLearning=learning)
        eligible = [question("previous", "Redis"), question("new", "Redis")]
        callbacks = Mock(questions=AsyncMock(return_value=eligible), plan=AsyncMock())
        model = Mock(model_name="test")
        plan = {"analysis": "work on Redis", "steps": ["practice"], "questions": [{"id": "new", "version": 1}]}
        invoke = model.bind_tools.return_value.ainvoke = AsyncMock(side_effect=[
            AIMessage(content="invalid"),
            AIMessage(content="", tool_calls=[{"name": "create_training_plan", "id": "call_plan", "args": plan}]),
        ])
        await execute_training(run, model, callbacks, "Produce a training plan.", native_catalog=True)
        callbacks.questions.assert_awaited_once()
        model.bind_tools.assert_called_once()
        self.assertEqual(model.bind_tools.call_args.kwargs["tool_choice"], "create_training_plan")
        self.assertIn('"id":"new"', invoke.await_args_list[0].args[0][1].content)
        self.assertNotIn(learning["priorities"][0]["evidence"][0], invoke.await_args_list[0].args[0][1].content)
        self.assertIn("Expected one create_training_plan", invoke.await_args_list[1].args[0][0].content)
        callbacks.plan.assert_awaited_once_with(plan)

    async def test_career_guard_rejects_other_jobs_and_unapproved_side_effects(self):
        tools = CareerChatTools(uuid4(), "test-token", uuid4())
        with self.assertRaises(CareerToolError):
            await tools._request("POST", "/api/career/tasks/training", json={"jobId": str(uuid4())})
        with self.assertRaises(CareerToolError):
            await tools._request("POST", "/api/career/applications/submit", json={"jobId": str(tools.job_id)})
        with self.assertRaises(CareerToolError):
            await tools.create("UNKNOWN", uuid4())
