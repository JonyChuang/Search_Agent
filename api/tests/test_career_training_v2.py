import asyncio
import copy
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.controllers.career_task_controller import TrainingRequest, submit
from app.core.agent.loop.models import RubricDef, RubricDim
from app.core.agent.loop.verifier.llm_verifier import _render_prompt
from app.services.career_chat_tools import requests_plan
from app.services.career_chat_context import constraint_details, parse_constraint_request
from app.services.career_context import CareerContextTooLarge
from app.services.career_context_versions import CareerContextVersions
from app.services.career_learning_state import TrainingUtilityWeights, learning_state, with_training_utility
from app.services.career_question_catalog import order_questions, question_key
from app.services.career_task_service import CareerRun, CareerTrace, generate_verified_plan
from app.services.career_training_contract import (
    TrainingContractError,
    TrainingRequirements,
    build_contract,
    feasible_questions,
    fixed_deadline,
    read_requirements,
)
from app.services.career_training_runtime import TrainingExecution, TrainingProgress, retry_block
from app.services.career_training_harness import explain_learning, learning_candidates, question_utilities
from app.services.career_training_verifier import TrainingPlan, schema_report, verify_plan

NOW = datetime(2026, 11, 26, 16, 30, tzinfo=timezone.utc)
JOB = {"skills": "Redis / MySQL"}
CATALOG = [{"id": "redis", "version": 2, "topic": "Redis"}, {"id": "mysql", "version": 1, "topic": "MySQL"}]


def contract(requirements=None, *, text="", pinned=(), repair="local-v1", created_at=NOW):
    return build_contract(
        user=str(uuid4()), job_id=str(uuid4()), conversation=str(uuid4()), job=JOB, preferred=None,
        requirements=TrainingRequirements.model_validate(requirements or {}), request_text=text, pinned=pinned,
        created_at=created_at, repair=repair, learning="objective-practice-v1",
    )


def plan() -> dict:
    return {
        "analysis": "岗位分析", "experienceIds": [],
        "questions": [{"id": item["id"], "version": item["version"]} for item in CATALOG],
        "schedule": [
            {"title": "练习 " + item["topic"], "skill": item["topic"], "scheduledDate": "2026-11-27",
             "questionRefs": [item["id"]]} for item in CATALOG
        ],
    }


class ContractTests(unittest.TestCase):
    def test_current_requirements_override_pinned_in_local_time(self):
        pinned = [{"field": "截止时间", "value": "下周三", "confirmed": True, "version": 3}]
        text = "周五之前完成 Redis 和 MySQL 的复习，安排两道题，优先复习 Redis，并且不要重复已经完成的题目"
        spec = contract({"timeZone": "Asia/Shanghai"}, text=text, pinned=pinned)
        self.assertTrue(requests_plan(text))
        self.assertEqual(spec.startDate, date(2026, 11, 27))
        self.assertEqual(spec.deadline, date(2026, 11, 27))
        self.assertEqual(spec.questionCount, 2)
        self.assertEqual(spec.prioritySkills, ["Redis"])
        self.assertTrue(spec.excludeCompleted)
        pinned[0]["value"] = "下周一"
        pinned[0].update(fixed_deadline("下周一", NOW, "Asia/Shanghai"))
        new = contract({"timeZone": "Asia/Shanghai"}, pinned=pinned)
        self.assertEqual(new.deadline, date(2026, 11, 30))
        self.assertEqual(spec.deadline, date(2026, 11, 27))
        self.assertNotEqual(spec.id, new.id)

    def test_conflicting_preferences_and_uncertain_input(self):
        spec = contract(text="安排五道题左右，优先复习 Redis 还是 MySQL")
        self.assertIsNone(spec.questionCount)
        self.assertEqual(spec.prioritySkills, [])
        self.assertIn("左右", spec.preferences[0])
        with self.assertRaisesRegex(TrainingContractError, "时区"):
            contract(text="周五之前完成 Redis 的复习")
        with self.assertRaisesRegex(TrainingContractError, "固定的截止日期"):
            contract({"timeZone": "Asia/Shanghai"}, text="明天截止，后天截止")
        with self.assertRaisesRegex(TrainingContractError, "题量"):
            feasible_questions(contract({"questionCount": 1, "prioritySkills": ["Redis"]}), CATALOG)

    def test_negation_range_condition_and_structured_precedence(self):
        self.assertEqual(contract(text="安排五道题").questionCount, 5)
        self.assertEqual(contract(text="先安排三道题，改成五道题").questionCount, 5)
        for raw in ("不要安排五道题", "如果有时间就安排五道题", "如果有时间，安排五道题", "安排五道题左右"):
            with self.subTest(raw=raw):
                self.assertIsNone(contract(text=raw).questionCount)
                self.assertIn(raw, contract(text=raw).preferences)
        for raw in ("最多安排五道题", "至少安排三道题", "安排三到五道题", "安排三道题，同时安排五道题",
                    "不要超过五道题", "不要安排五道题，安排五道题", "截止日期是周五，周六"):
            with self.subTest(raw=raw), self.assertRaises(TrainingContractError) as error:
                contract(text=raw)
            self.assertEqual(error.exception.code, "CONTRACT_CONFIRMATION_REQUIRED")
        self.assertEqual(read_requirements("不要优先复习 Redis")[0].status, "NEGATED")
        self.assertEqual(contract(text="不要优先复习 Redis").prioritySkills, [])
        self.assertIsNone(contract(text="周五不需要完成复习").deadline)
        self.assertIsNone(contract(text="请复习 Redis").questionCount)
        mixed = contract({"questionCount": 4}, text="安排三道题，安排五道题")
        self.assertEqual(mixed.questionCount, 4)
        self.assertEqual({source.get("status") for source in mixed.sources if source["type"] == "natural"}, {"CONFLICTING"})
        self.assertTrue(any(source["type"] == "structured" and source["field"] == "questionCount" for source in mixed.sources))

    def test_fixed_date_does_not_drift_and_legacy_relative_requires_confirmation(self):
        zone = "Asia/Shanghai"
        pinned = {"field": "截止时间", "value": "明天", "confirmed": True, **fixed_deadline("明天", NOW, zone)}
        tomorrow = NOW + timedelta(days=1)
        self.assertEqual(contract({"timeZone": zone}, pinned=[pinned]).deadline, date(2026, 11, 28))
        self.assertEqual(contract({"timeZone": zone}, pinned=[pinned], created_at=tomorrow).deadline, date(2026, 11, 28))
        self.assertEqual(fixed_deadline("明天", NOW, "America/Los_Angeles")["normalizedValue"], "2026-11-27")
        west = {**pinned, **fixed_deadline("明天", NOW, "America/Los_Angeles")}
        east_midnight = datetime(2026, 11, 28, 3, tzinfo=timezone.utc)
        traveling = contract({"timeZone": zone}, pinned=[west], created_at=east_midnight)
        self.assertEqual((traveling.startDate, traveling.deadline), (date(2026, 11, 27), date(2026, 11, 27)))
        with self.assertRaisesRegex(TrainingContractError, "早于"):
            contract({"timeZone": zone}, pinned=[pinned], created_at=tomorrow + timedelta(days=1))
        with self.assertRaisesRegex(TrainingContractError, "重新确认"):
            contract({"timeZone": zone}, pinned=[{"field": "截止时间", "value": "明天", "confirmed": True}])

    def test_feasibility_keep_pinned_and_exact_cover(self):
        spec = contract({"requiredSkills": ["Python", "Spring"], "questionCount": 2, "excludeCompleted": True})
        a = {"id": "a", "version": 1, "topic": "Redis MySQL"}
        b = {"id": "b", "version": 1, "topic": "Python Spring"}
        done = {"id": "done", "version": 1, "topic": "Redis MySQL Python Spring", "practiceCompleted": True}
        self.assertEqual(feasible_questions(spec, [*CATALOG, done, b, a])[:2], [b, a])
        pinned = contract({"requiredQuestions": [{"id": "redis", "version": 1}]})
        with self.assertRaisesRegex(TrainingContractError, "指定题目"):
            feasible_questions(pinned, CATALOG)

    def test_verifier_rejects_dates_order_and_personal_claim_references(self):
        bad = plan()
        bad["schedule"].reverse()
        bad["schedule"][0]["scheduledDate"] = "2026-11-30"
        bad["experienceIds"] = [str(uuid4())]
        spec = contract({"deadline": "2026-11-29", "prioritySkills": ["Redis"], "questionCount": 2})
        report = verify_plan(TrainingPlan.model_validate(bad), spec, CATALOG, set())
        self.assertEqual({error.code for error in report.errors}, {
            "DEADLINE_EXCEEDED", "INVALID_DATE_ORDER", "PRIORITY_ORDER_MISMATCH", "UNCONFIRMED_EXPERIENCE",
        })

    def test_phase_order_and_preflight_use_same_question_rules(self):
        redis, mysql = CATALOG
        catalog = [redis, mysql, {**redis, "id": "redis-2"}]
        strict = contract(text="先完成 Redis 阶段后再复习 MySQL", requirements={"questionCount": 3})
        self.assertEqual(strict.orderMode, "STRICT_PHASE_ORDER")
        plain = strict.model_copy(update={"orderMode": "FIRST_OCCURRENCE_ORDER"})
        for ids, expected in ((["redis", "redis-2", "mysql"], (True, True)),
                              (["redis", "mysql", "redis-2"], (True, False)),
                              (["mysql", "redis", "redis-2"], (False, False))):
            draft = plan()
            different = {item["id"]: item for item in catalog}
            draft["questions"] = [{"id": identifier, "version": different[identifier]["version"]} for identifier in ids]
            draft["schedule"] = [{"title": "练习", "scheduledDate": None, "skill": None, "questionRefs": [identifier]}
                                 for identifier in ids]
            candidate = TrainingPlan.model_validate(draft)
            self.assertEqual(tuple(verify_plan(candidate, spec, catalog, set()).passed for spec in (plain, strict)), expected)
            legacy = strict.model_copy(update={"version": 1, "verifierVersion": "training-verifier-v1"})
            self.assertEqual(verify_plan(candidate, legacy, catalog, set()).passed, expected[0])
        witness = []
        feasible_questions(strict, catalog, witness=witness)
        self.assertEqual([item["id"] for item in witness], ["redis", "redis-2", "mysql"])
        dual = [{"id": "both", "version": 1, "topic": "Redis MySQL"}]
        with self.assertRaisesRegex(TrainingContractError, "复习阶段"):
            feasible_questions(strict.model_copy(update={"questionCount": 1}), dual)
        self.assertEqual(feasible_questions(plain.model_copy(update={"questionCount": 1}), dual), dual)

    def test_candidate_truncation_and_search_limit(self):
        spec = contract({"prioritySkills": ["Redis", "MySQL", "Python"], "questionCount": 3})
        catalog = [{"id": f"d{i}", "version": 1, "topic": "Spring"} for i in range(31)]
        catalog += [{"id": "skip", "version": 1, "topic": "Redis Python"}, {"id": "p", "version": 1, "topic": "Python"}, *CATALOG]
        witness = []
        snapshot = feasible_questions(spec, catalog)[:30]
        feasible_questions(spec, snapshot, witness=witness)
        self.assertEqual([q["id"] for q in witness][:2], ["redis", "mysql"])
        self.assertIn(witness[-1]["id"], {"p", "skip"})
        with patch("app.services.career_training_contract.MAX_FEASIBILITY_STEPS", 1):
            with self.assertRaises(TrainingContractError) as blocked:
                feasible_questions(spec, catalog)
        self.assertEqual(blocked.exception.code, "TASK_CONTRACT_FEASIBILITY_UNDETERMINED")

    def test_offline_semantic_rubric_uses_the_plan_artifact(self):
        rubric = RubricDef(name="career_training", dims=[RubricDim(key="practicality", label="可执行性", weight=1)])
        prompt = _render_prompt("后端研发", rubric, {"schedule": ["Redis"]})
        self.assertIn('"schedule": ["Redis"]', prompt)
        self.assertIn("可执行性", prompt)

    def test_learning_recency_distinct_questions_and_stale_version(self):
        def sample(question, days, correct, version=1):
            return {"questionId": f"r-{question}", "questionVersion": version, "currentVersion": 2,
                    "submittedAt": NOW - timedelta(days=days), "correct": correct, "topic": "Redis",
                    "attemptId": f"r-{question}-{days}"}

        weak = [sample(1, 0, False, 2), sample(2, 1, False, 2), sample(1, 2, False, 2)]
        stale = [sample(1, 25, False), sample(2, 26, False)]
        improved = [sample(1, 0, True, 2), sample(2, 1, True, 2), sample(1, 2, False, 2), sample(2, 3, False, 2)]
        dropped = [sample(1, 0, False, 2), sample(2, 1, False, 2), sample(1, 2, True, 2), sample(2, 3, True, 2)]
        for attempts, expected in (([], "EXPLORE"), (weak[:1], "EXPLORE"), (weak, "WEAK"),
                                   (stale, "EXPLORE"), (improved, "CONSOLIDATE"), (dropped, "WEAK")):
            with self.subTest(expected=expected, count=len(attempts)):
                state = learning_state(attempts, ["Redis", "Spring"], NOW)
                skills = {item["skill"]: item for item in state["priorities"]}
                self.assertEqual(skills["Redis"]["masteryStatus"], expected)
                self.assertLessEqual(skills["Redis"]["sampleSize"], 2)
                self.assertEqual(skills["Spring"]["sampleSize"], 0)


class SubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_deadline_edit_and_rollback_preserve_normalization_metadata(self):
        records = {0: {"version": 0, "state": {}, "source": "history"}}

        async def execute(query, params):
            if "INSERT INTO career_context_versions" in str(query):
                records[params["version"]] = {"version": params["version"], "source": params["source"],
                                             "state": json.loads(params["state"]), "field_meta": json.loads(params["field_meta"])}

        session = SimpleNamespace(execute=execute, add=Mock(), flush=AsyncMock(), commit=AsyncMock())
        conversation = uuid4()
        service = CareerContextVersions(session, uuid4(), conversation, uuid4())
        service.read = AsyncMock(side_effect=lambda version=None: records[max(records) if version is None else version])
        first = SimpleNamespace(id=uuid4(), conversation_id=conversation, role="user", created_at=NOW,
                                content="截止时间改为明天。")
        saved = await service.save(message=first, time_zone="Asia/Shanghai")
        original = saved["field_meta"]["截止时间"]
        self.assertEqual(original["normalizedValue"], "2026-11-28")
        self.assertEqual(original["rawValue"], "明天")
        changed = await service.save(edits={"截止时间": "2026-12-03"}, time_zone="America/Los_Angeles", expected=1)
        self.assertEqual(changed["field_meta"]["截止时间"]["normalizedValue"], "2026-12-03")
        rollback = await service.save(rollback=1, expected=2, time_zone="America/Los_Angeles")
        self.assertEqual(rollback["field_meta"]["截止时间"], original)
        self.assertEqual(rollback["state"]["截止时间"][0], str(first.id))
        condition = "如果有时间，截止时间改为周五。"
        self.assertEqual(parse_constraint_request(condition), ({}, condition))
        legacy = constraint_details({"截止时间": [str(first.id), "明天"]}, 1)
        self.assertFalse(legacy[0]["confirmed"])

    async def test_freezes_separate_scopes_and_does_not_rebuild_on_request_replay(self):
        user, job, conversation, request_id = (str(uuid4()) for _ in range(4))
        body = TrainingRequest(jobId=job, requestId=request_id, requirements={"questionCount": 2})
        owned = SimpleNamespace(get=AsyncMock(return_value={"id": job, "company": "示例", "title": "研发",
                                                            "location": "", "description": "", **JOB}))
        records = SimpleNamespace(db=None, user=user, jobs=lambda: owned, job_notes=AsyncMock(return_value={"notes": None}))
        stored = {}

        async def store(owner, kind, job_id, request, context, **extra):
            row = {"user_id": owner, "job_id": job_id, "kind": kind, "request_json": request, "context_json": context,
                   "training_catalog_json": extra["training_catalog"]}
            stored[(owner, request["requestId"])] = row
            return row

        with (patch("app.controllers.career_task_controller.CareerQueue") as queue,
              patch("app.controllers.career_task_controller.CareerTraining") as training,
              patch("app.controllers.career_task_controller.view", side_effect=lambda row: row)):
            queue.return_value.lookup_request = AsyncMock(side_effect=lambda owner, req: stored.get((owner, req)))
            queue.return_value.by_request = AsyncMock(side_effect=lambda owner, kind, req: stored.get((owner, req["requestId"])))
            queue.return_value.insert = AsyncMock(side_effect=store)
            training.return_value.apply_training_snapshot = AsyncMock()
            training.return_value.catalog = AsyncMock(return_value=CATALOG)
            pinned = [{"field": "复习顺序", "value": "Redis 再 MySQL", "confirmed": True, "version": 3}]
            first = (await submit("TRAINING", body, records, pinned=pinned, conversation_id=conversation))["data"]
            pinned[0]["value"] = "MySQL 再 Redis"
            replay = (await submit("TRAINING", body, records, pinned=pinned, conversation_id=conversation))["data"]
            self.assertIs(replay, first)
            self.assertEqual(first["context_json"]["trainingContract"]["prioritySkills"], ["Redis", "MySQL"])
            training.return_value.catalog.assert_awaited_once()
            other = SimpleNamespace(**{**vars(records), "user": str(uuid4())})
            stand_alone = (await submit("TRAINING", body, other))["data"]["context_json"]["trainingContract"]
            self.assertIsNone(stand_alone["conversationId"])
            self.assertEqual(stand_alone["prioritySkills"], [])
            self.assertEqual(stand_alone["userId"], other.user)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.spec = contract({"deadline": "2026-11-28", "questionCount": 2})
        self.run = CareerRun(id=uuid4(), lease=uuid4(), userId=uuid4(), kind="TRAINING", context={"job": JOB},
                             trainingCatalog=CATALOG)
        self.callbacks = SimpleNamespace(plan=AsyncMock(), record_event=AsyncMock(), training_runtime=AsyncMock())
        self.trace = CareerTrace(self.run, self.callbacks)
        self.runtime = TrainingExecution(self.spec, None, self.callbacks.training_runtime)
        self.model = SimpleNamespace(model_name="test")

    async def generate(self, replies, budget=None):
        async def invoke(messages):
            value = next(replies)
            if isinstance(value, Exception):
                raise value
            return AIMessage(content="", tool_calls=[{"name": self.tool, "args": value, "id": "test"}])

        def bind(tools, *, tool_choice):
            self.tool = tool_choice
            return SimpleNamespace(ainvoke=invoke)

        self.model.bind_tools = bind
        await generate_verified_plan(self.run, self.model, self.trace, {"instructions": "测试"}, self.run.context,
                                     self.runtime, budget)

    async def test_deterministic_repair_retains_other_content_without_another_call(self):
        bad = plan()
        bad["questions"][0]["version"] = 5
        bad["schedule"][0]["scheduledDate"] = "2026-12-12"
        await self.generate(iter([bad]))
        final = self.callbacks.plan.await_args.args[0]
        self.assertEqual(final["questions"], plan()["questions"])
        self.assertEqual(final["analysis"], bad["analysis"])
        self.assertEqual(final["schedule"][1]["title"], bad["schedule"][1]["title"])
        self.assertEqual((self.runtime.state.modelCalls, self.runtime.state.repairRounds), (1, 1))

    async def test_patch_recovery_preserves_model_reservation_and_merges_original_analysis(self):
        bad = plan()
        bad["questions"][0]["id"] = "not-in-catalog"
        snapshot = {}

        async def exit_after_reservation(value):
            snapshot.update(copy.deepcopy(value))
            if value["stage"] == "REPAIRING":
                raise asyncio.CancelledError()

        self.runtime = TrainingExecution(self.spec, None, exit_after_reservation)
        with self.assertRaises(asyncio.CancelledError):
            await self.generate(iter([bad]))
        self.callbacks.plan.assert_not_awaited()
        self.runtime = TrainingExecution(self.spec, TrainingProgress.model_validate(snapshot), self.callbacks.training_runtime)
        good = {key: value for key, value in plan().items() if key in {"questions", "schedule"}}
        await self.generate(iter([good]))
        self.assertEqual(self.tool, "TrainingPlanPatch")
        self.assertEqual(self.runtime.state.modelCalls, 3)
        self.assertEqual(self.runtime.state.repairRounds, 1)
        self.assertEqual(self.runtime.state.unknownOperations, 1)
        self.assertEqual(self.callbacks.plan.await_args.args[0]["analysis"], bad["analysis"])

    async def test_repeated_schema_failure_stops_and_cannot_save(self):
        with self.assertRaisesRegex(TrainingContractError, "上限"):
            await self.generate(iter([{}, {}, {}]))
        self.assertTrue(self.runtime.state.stalled)
        self.assertEqual(self.runtime.state.modelCalls, 3)
        self.callbacks.plan.assert_not_awaited()

    async def test_timing_and_transient_errors_distinct_from_validation_failures(self):
        with self.assertRaises(TimeoutError):
            await self.generate(iter([TimeoutError()]))
        self.assertEqual(self.runtime.state.modelCalls, 1)
        self.assertIsNone(self.runtime.state.lastReport)
        with self.assertRaises(CareerContextTooLarge):
            await self.generate(iter([]), budget=8)
        self.assertEqual(self.runtime.state.modelCalls, 1)
        expired = self.runtime.state.model_copy(update={"startedAt": datetime.now(timezone.utc) - timedelta(seconds=301)})
        self.runtime = TrainingExecution(self.spec, expired, self.callbacks.training_runtime)
        with self.assertRaisesRegex(TrainingContractError, "时限"):
            await self.generate(iter([]))

    async def test_repeat_result_is_idempotent_and_model_cap_blocks_restart(self):
        operation = await self.runtime.reserve(model=True, repair=True)
        self.assertTrue(await self.runtime.verified(operation, None, schema_report(None)))
        self.assertFalse(await self.runtime.verified(operation, None, schema_report(None)))
        self.assertEqual(self.runtime.state.repairRounds, 1)
        progress = self.runtime.state.model_dump(mode="json")
        progress["modelCalls"] = self.spec.budget.maxModelCalls
        self.runtime = TrainingExecution(self.spec, TrainingProgress.model_validate(progress), self.callbacks.training_runtime)
        with self.assertRaises(TrainingContractError) as blocked:
            await self.runtime.reserve(model=True, repair=True)
        self.assertEqual(blocked.exception.code, "MODEL_BUDGET_EXHAUSTED")
        row = {"context_json": {"trainingContract": self.spec.model_dump(mode="json")}, "training_runtime_json": progress}
        self.assertEqual(retry_block(row).code, "MODEL_BUDGET_EXHAUSTED")
        row["training_runtime_json"]["modelCalls"] = 1
        row["training_runtime_json"]["repairRounds"] = self.spec.budget.maxRepairRounds
        self.assertEqual(retry_block(row).code, "REPAIR_BUDGET_EXHAUSTED")

    async def test_utility_changes_selected_plan_and_records_adoption(self):
        catalog = [*CATALOG, {"id": "redis-extra", "version": 1, "topic": "Redis"},
                   {"id": "mysql-extra", "version": 1, "topic": "MySQL"}]
        spec = contract({"questionCount": 3}).model_copy(update={"learningVersion": "objective-practice-v2-utility"})
        selections = []
        for correct in (False, True):
            attempts = [{"attemptId": f"a-{i}", "questionId": f"history-{i}", "questionVersion": 1, "topic": "Redis",
                         "submittedAt": NOW - timedelta(days=i), "correct": correct} for i in range(3)]
            evidence = learning_state(attempts, spec.requiredSkills, NOW)
            learning = with_training_utility(evidence, job_skills=spec.jobSkills, preferred=[], as_of=NOW,
                                             weights=TrainingUtilityWeights())
            utility = question_utilities(catalog, learning)
            ordered = order_questions(catalog, JOB, practice_targets=learning_candidates(catalog, learning), utility=utility)
            witness = []
            frozen = feasible_questions(spec, ordered, utility=utility, witness=witness)
            run = self.run.model_copy(update={"practiceLearning": learning, "trainingCatalog": frozen,
                                              "context": {**self.run.context, "trainingFeasibility": {"witness": witness}}})
            runtime = TrainingExecution(spec, None, self.callbacks.training_runtime)

            def bind(*args, tool_choice):
                async def invoke(messages):
                    data = json.loads(messages[-1].content)
                    self.assertIn("confidence", data["trainingPriorities"][0])
                    refs = data["context"]["trainingFeasibility"]["witness"]
                    draft = {"analysis": "按推荐训练", "experienceIds": [], "questions": refs,
                             "schedule": [{"title": "练习", "skill": None, "scheduledDate": None,
                                           "questionRefs": [ref["id"]]} for ref in refs]}
                    return AIMessage(content="", tool_calls=[{"name": tool_choice, "args": draft, "id": "fixture"}])

                return SimpleNamespace(ainvoke=invoke)

            self.model.bind_tools = bind
            await generate_verified_plan(run, self.model, self.trace, {"instructions": "测试"}, run.context, runtime, None)
            final = self.callbacks.plan.await_args.args[0]["questions"]
            selections.append({question_key(ref) for ref in final})
            self.assertEqual(explain_learning(final, frozen, learning, witness)["adoption"], {"accepted": 3, "recommended": 3})
            self.assertEqual(explain_learning(final[:2], frozen, learning, witness)["adoption"]["accepted"], 2)
        self.assertIn(("redis-extra", 1), selections[0] - selections[1])
        self.assertIn(("mysql-extra", 1), selections[1] - selections[0])
