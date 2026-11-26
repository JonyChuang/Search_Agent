"""Run the submission, checkpoint, and worker paths on a disposable MySQL database."""

import asyncio
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage
from sqlalchemy import text

from app.config import settings
from app.controllers.career_task_controller import TrainingRequest, submit
from app.core.exceptions import BizError
from app.db.career import career_transaction, close, verify_career_schema
from app.services.career_queue import CareerQueue
from app.services.career_records import CareerRecords
from app.services.career_training_contract import TrainingContract, topic_skills
from app.services.career_worker import NativeCareerCheckpoints, _run_claimed
from eval.harness_v2_eval import plan_for
from eval.harness_v2_replay import archived


@unittest.skipUnless(os.environ.get("CAREER_HARNESS_MYSQL_TEST_DB"), "requires a disposable MySQL test database")
class TrainingMysqlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIn(settings.career_mysql_host, {"localhost", "127.0.0.1", "::1"})
        self.assertEqual(settings.career_mysql_database, os.environ["CAREER_HARNESS_MYSQL_TEST_DB"])
        self.assertTrue(settings.career_mysql_database.startswith("harness_v2_"))
        self.addAsyncCleanup(close)
        self.user = str(uuid4())
        await verify_career_schema()
        async with career_transaction() as db:
            records = CareerRecords(db, self.user)
            self.job = (await records.jobs().create({
                "company": "Harness 测试", "title": "后端工程师", "description": "Java 与 MySQL",
                "skills": "Java MySQL", "location": None, "sourceName": "测试夹具", "sourceUrl": None,
                "sourcedOn": datetime.now(timezone.utc).date(),
            }))["id"]
            await records.save_job_notes(self.job, 0, "原偏好")

    async def asyncTearDown(self):
        async with career_transaction() as db:
            await db.execute(text("DELETE FROM career_task WHERE user_id = :user"), {"user": self.user})
            await db.execute(text("DELETE FROM career_job WHERE user_id = :user"), {"user": self.user})

    async def create_and_claim(self):
        conversation = str(uuid4())
        request = TrainingRequest(requestId=uuid4(), jobId=self.job, requirements={"questionCount": 2})
        pinned = [{"field": "复习顺序", "value": "Java", "version": 2, "confirmed": True}]
        async with career_transaction() as db:
            records = CareerRecords(db, self.user)
            created = (await submit("TRAINING", request, records, pinned=pinned, conversation_id=conversation))["data"]
            repeated = (await submit("TRAINING", request, records, pinned=pinned, conversation_id=conversation))["data"]
            self.assertEqual(created["id"], repeated["id"])
            with self.assertRaises(BizError):
                await submit("TRAINING", request, records, pinned=pinned, conversation_id=str(uuid4()))
            with self.assertRaises(BizError):
                await submit("TRAINING", request.model_copy(update={"jobId": uuid4()}), records)
            with self.assertRaises(BizError):
                await submit("TRAINING", request, CareerRecords(db, str(uuid4())))
            await records.save_job_notes(self.job, 1, "更新后另一个偏好")
        async with career_transaction() as db:
            row = await CareerQueue(db).claim(("TRAINING",))
            self.assertEqual(row["id"], created["id"])
        return row

    async def test_repair_worker_takeover_stale_writes_and_archived_replay(self):
        first = await self.create_and_claim()
        contract = TrainingContract.model_validate(first["context_json"]["trainingContract"])
        self.assertEqual(contract.prioritySkills, ["Java"])
        # Seeded topics include aliases. Use the canonical skill from each selected question.
        catalog = first["training_catalog_json"]
        chosen = [{**item, "topic": sorted(topic_skills(item["topic"], set(contract.requiredSkills)))[0]}
                  for item in catalog[:2]]
        draft = plan_for(chosen, contract)
        invalid = {**draft, "questions": [{**draft["questions"][0], "version": 999}, draft["questions"][1]]}
        invoke = AsyncMock(return_value=AIMessage(content="", tool_calls=[
            {"name": "TrainingPlan", "args": invalid, "id": "fixture"},
        ]))
        config = SimpleNamespace(id=uuid4(), updated_at=datetime.now(timezone.utc), capability=["function_call"],
                                 context_window_tokens=8192)
        model = SimpleNamespace(model_name="mysql-fixture", bind_tools=lambda *args, **kwargs: SimpleNamespace(ainvoke=invoke))
        write = NativeCareerCheckpoints.training_runtime

        async def checkpoint_then_crash(callback, value):
            await write(callback, value)
            if value["stage"] == "REPAIRING":
                raise asyncio.CancelledError()

        with patch("app.services.career_task_service.build_default_chat_model", return_value=(model, config)):
            with (patch.object(NativeCareerCheckpoints, "training_runtime", checkpoint_then_crash),
                  self.assertRaises(asyncio.CancelledError)):
                await _run_claimed(first)
            async with career_transaction() as db:
                await db.execute(text("UPDATE career_task SET lease_until = CURRENT_TIMESTAMP(6) WHERE id = :id"),
                                 {"id": first["id"]})
            async with career_transaction() as db:
                second = await CareerQueue(db).claim(("TRAINING",))
                self.assertEqual(second["generation"], first["generation"] + 1)
                self.assertEqual(second["context_json"]["trainingContract"], first["context_json"]["trainingContract"])
                self.assertEqual(second["training_runtime_json"]["repairRounds"], 1)
            with self.assertRaises(BizError):
                await NativeCareerCheckpoints(first).training_runtime({"stale": True})
            with self.assertRaises(BizError):
                await NativeCareerCheckpoints(first).plan(draft)
            self.assertEqual(await _run_claimed(second), "SUCCEEDED")
        invoke.assert_awaited_once()
        async with career_transaction() as db:
            queue = CareerQueue(db)
            final = await queue.owned(self.user, first["id"])
            self.assertEqual(final["training_runtime_json"]["repairRounds"], 2)
            self.assertEqual(final["training_runtime_json"]["modelCalls"], 1)
            self.assertNotIn("candidate", final["training_runtime_json"])
            self.assertEqual(len(final["result_json"]["steps"]), 2)
            events = await queue.events(self.user, first["id"])
            self.assertTrue(any(event["step"] == "training_outcome" for event in events))
            self.assertTrue(all(not event["details"] or "replay" not in event["details"] for event in events))
        cases = await archived(UUID(self.user), UUID(first["id"]))
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["original"], cases[0]["replay"]["validation"])
        self.assertTrue(cases[0]["replay"]["repair"]["passed"])

    async def test_cancel_rejects_running_generation(self):
        running = await self.create_and_claim()
        async with career_transaction() as db:
            queue = CareerQueue(db)
            state = await queue.change_state(self.user, running["id"], "CANCEL", "RUNNING", running["generation"])
            self.assertEqual(state["status"], "CANCELLED")
            self.assertFalse(await queue.finish(running, {"stale": True}, None))
        with self.assertRaises(BizError):
            await NativeCareerCheckpoints(running).training_runtime({"stale": True})
