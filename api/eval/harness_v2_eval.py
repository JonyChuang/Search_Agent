"""Compare production TRAINING execution paths with fixed, synthetic case inputs."""

import argparse
import asyncio
import copy
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import perf_counter
from types import SimpleNamespace
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage
from openai import APIError

from app.config import settings
from app.core.agent.loop.models import RubricDef, RubricDim
from app.core.agent.loop.verifier import build_verifier
from app.core.llm.chat_model import build_default_chat_model, chat_context_budget
from app.db.postgres import SessionLocal, close
from app.services.career_context import CareerContextTooLarge
from app.services.career_learning_state import LEARNING_V2, learning_state
from app.services.career_question_catalog import order_questions, question_key
from app.services.career_task_service import (
    CareerRun,
    CareerTrace,
    InvalidCareerToolResponse,
    execute_training,
    generate_verified_plan,
)
from app.services.career_training_contract import (
    TrainingContractError,
    TrainingRequirements,
    build_contract,
    feasible_questions,
    topic_skills,
)
from app.services.career_training_harness import POLICY_VERSION, learn_from_attempts, learning_candidates
from app.services.career_training_runtime import TrainingExecution, TrainingProgress
from app.services.career_training_verifier import TrainingPlan, verify_plan

CREATED = datetime(2026, 11, 26, 8, tzinfo=timezone.utc)
JOB = {"title": "后端工程师", "skills": "Redis / MySQL", "jd": "维护缓存和数据库"}
CATALOG = [
    {"id": identifier, "version": version, "topic": topic, "prompt": f"解释 {topic} 示例 {identifier} 的原理"}
    for identifier, version, topic in (("redis-1", 2, "Redis"), ("mysql-1", 1, "MySQL"),
                                       ("redis-2", 1, "Redis"), ("mysql-2", 1, "MySQL"), ("redis-3", 1, "Redis"))
]
PIN = {"id": "redis-1", "version": 2}


@dataclass
class Case:
    name: str
    requirements: dict = field(default_factory=dict)
    fault: str | None = None
    recovery: bool = False
    history: str | None = None
    request_text: str = ""
    pinned: list[dict] = field(default_factory=list)
    expected: str = "success"


CASES = (
    Case("normal"), Case("question_count", {"questionCount": 3}, "count"),
    Case("deadline", {"deadline": "2026-11-27"}, "no_date"),
    Case("priority_order", {"prioritySkills": ["MySQL", "Redis"]}, "order"),
    Case("unknown_question", fault="unknown"), Case("duplicate_question", fault="duplicate"),
    Case("pinned_question", {"requiredQuestions": [PIN]}, "pinned"), Case("missing_skill", fault="coverage"),
    Case("late_step", {"deadline": "2026-11-27"}, "late"),
    Case("infeasible_catalog", {"requiredSkills": ["Spring"]}, expected="reject"),
    Case("context_budget", fault="budget", expected="budget"),
    Case("exit_during_repair", fault="unknown", recovery=True),
    Case("takeover_verified_checkpoint", fault="version", recovery=True),
    Case("weak_evidence", {"questionCount": 3, "requiredQuestions": [PIN]}, history="weak"),
    Case("cold_start", history="cold"), Case("recent_improvement", history="improved"),
    Case("malformed_tool", fault="schema"), Case("unknown_version", fault="version"),
    Case("completed_question", {"excludeCompleted": True}, "completed"),
)

EXTENDED_CASES = (
    Case("negated_count", request_text="不用安排五道题"),
    Case("conditional_count", request_text="如果有时间，安排五道题"),
    Case("range_requires_confirmation", request_text="安排三到五道题", expected="clarify"),
    Case("corrected_deadline", {"timeZone": "Asia/Shanghai"}, request_text="截止日期改为明天",
         pinned=[{"field": "截止时间", "value": "下周一", "normalizedValue": "2026-11-30", "confirmed": True}]),
    Case("strict_interleaving", {"questionCount": 3}, "interleave",
         request_text="先完成 Redis 阶段后再复习 MySQL"),
    Case("long_context_fallback", fault="long_context"),
)


def attempts_for(history: str | None) -> list[dict]:
    outcomes = {"weak": [(1, False), (3, False)], "improved": [(1, True), (3, True), (1, False), (3, False)]}
    return [{"questionId": f"redis-{index}", "questionVersion": 2 if index == 1 else 1, "topic": "Redis",
             "attemptId": f"fixture-{offset}", "correct": correct, "submittedAt": CREATED - timedelta(days=offset + 1)}
            for offset, (index, correct) in enumerate(outcomes.get(history, []))]


def plan_for(catalog: list[dict], contract, *, analysis="按顺序练习岗位相关主题") -> dict:
    chosen = list(catalog[:contract.questionCount or 2])
    order = contract.prioritySkills
    chosen.sort(key=lambda item: order.index(item["topic"]) if item["topic"] in order else len(order))
    return {
        "analysis": analysis, "experienceIds": [],
        "questions": [{"id": item["id"], "version": item["version"]} for item in chosen],
        "schedule": [
            {"title": f"练习 {item['topic']}", "skill": item["topic"], "questionRefs": [item["id"]],
             "scheduledDate": contract.startDate.isoformat()}
            for item in chosen
        ],
    }


def inject(plan: dict, case: Case, contract_visible: bool) -> dict:
    draft = copy.deepcopy(plan)
    first = draft["questions"][0]
    match case.fault:
        case "count" if not contract_visible:
            draft["questions"].pop()
            draft["schedule"].pop()
        case "no_date" if not contract_visible:
            draft["schedule"][0]["scheduledDate"] = None
        case "order" if not contract_visible:
            draft["questions"].reverse()
            draft["schedule"].reverse()
        case "unknown":
            first["id"] = "outside-catalog"
        case "duplicate":
            draft["questions"].append(first.copy())
        case "pinned":
            draft["questions"][0] = {"id": "redis-3", "version": 1}
            draft["schedule"][0]["questionRefs"] = ["redis-3"]
        case "coverage":
            draft["questions"][1] = {"id": "redis-3", "version": 1}
            draft["schedule"][1].update(skill="Redis", questionRefs=["redis-3"])
        case "late":
            draft["schedule"][0]["scheduledDate"] = "2026-12-01"
        case "version":
            first["version"] = 9
        case "schema":
            return {}
        case "completed":
            draft["questions"][0] = {"id": "redis-3", "version": 1}
            draft["schedule"][0]["questionRefs"] = ["redis-3"]
        case "interleave":
            draft["schedule"][1], draft["schedule"][2] = draft["schedule"][2], draft["schedule"][1]
            draft["questions"][1], draft["questions"][2] = draft["questions"][2], draft["questions"][1]
    return draft


class ScriptedModel:
    model_name = "scripted-training-fixture"

    def __init__(self, clean: dict, first: dict, *, legacy_interrupt=False):
        self.clean = clean
        self.first = first
        self.calls = 0
        self.legacy_interrupt = legacy_interrupt

    def bind_tools(self, tools, *, tool_choice):
        async def invoke(messages):
            self.calls += 1
            if self.legacy_interrupt and self.calls == 2:
                raise InterruptedError("simulated exit during legacy repair")
            output = copy.deepcopy(self.first if self.calls == 1 else self.clean)
            if output and tool_choice == "create_training_plan":
                output = {"analysis": output["analysis"], "questions": output["questions"], "steps": [
                    f"{step['scheduledDate'] or '待定'} {step['title']}" for step in output["schedule"]
                ]}
            if tool_choice == "TrainingPlanPatch":
                output = {key: output[key] for key in ("questions", "schedule")}
            if self.calls > 1 and output and tool_choice != "TrainingPlanPatch":
                output["analysis"] = "重新生成的岗位分析"
            return AIMessage(content="", tool_calls=[{"name": tool_choice, "args": output, "id": "fixture"}])

        return SimpleNamespace(ainvoke=invoke)


def observe_legacy(result: dict) -> TrainingPlan:
    steps = result["steps"]
    schedule = []
    for index, choice in enumerate(result["questions"]):
        title = steps[index] if index < len(steps) else "练习"
        when = re.match(r"^\d{4}-\d{2}-\d{2}", title)
        schedule.append({"title": title, "skill": None, "scheduledDate": when[0] if when else None,
                         "questionRefs": [choice["id"]]})
    return TrainingPlan.model_validate({"analysis": result["analysis"], "questions": result["questions"],
                                        "schedule": schedule, "experienceIds": []})


async def execute_case(case: Case, group: str, real_model=None, model_budget=None, judge=None) -> dict:
    started = perf_counter()
    user, job, task = uuid4(), uuid4(), uuid4()
    report = {"case": case.name, "expected": case.expected, "saved": False, "success": False, "accepted": False,
              "calls": 0, "recordedUsage": [], "firstPass": None, "repair": None, "recovery": None,
              "required": [0, 0], "weak": [0, int(case.history == "weak")], "pinned": [0, 0],
              "analysisKept": None, "validQuestionRetention": None}
    try:
        spec = build_contract(
            user=str(user), job_id=str(job), conversation=None, job=JOB, preferred=None,
            requirements=TrainingRequirements.model_validate(case.requirements), request_text=case.request_text,
            pinned=case.pinned, created_at=CREATED, repair="regenerate-v1" if group == "C" else "local-v1",
            learning=LEARNING_V2 if group == "E" else POLICY_VERSION,
        )
    except TrainingContractError as error:
        return {**report, "error": error.code, "elapsedMs": (perf_counter() - started) * 1000}
    attempts = attempts_for(case.history)
    learning = (learning_state(attempts, spec.requiredSkills, CREATED) if group == "E"
                else learn_from_attempts(attempts, JOB))
    catalog = [{**item, "practiceCompleted": True} if case.fault == "completed" and item["id"] == "redis-3" else item
               for item in CATALOG]
    report.update(required=[0, len(spec.requiredSkills)], pinned=[0, len(spec.requiredQuestions)])
    targets = learning_candidates(catalog, learning)
    ordered = order_questions(catalog, JOB, PIN["id"] if spec.requiredQuestions else None, targets)
    try:
        if group != "A":
            ordered = feasible_questions(spec, ordered)
    except TrainingContractError as error:
        return {**report, "error": error.code, "elapsedMs": (perf_counter() - started) * 1000}
    clean = plan_for(ordered, spec)
    initial = inject(clean, case, group != "A")
    interrupt_legacy = group in {"A", "B"} and case.name == "exit_during_repair"
    model = real_model or ScriptedModel(clean, initial, legacy_interrupt=interrupt_legacy)
    model_budget = 500 if case.fault == "budget" else model_budget
    run = CareerRun(id=task, lease=uuid4(), userId=user, kind="TRAINING", context={"job": JOB},
                    trainingCatalog=ordered, practiceLearning=learning)
    if case.fault == "long_context":
        run.context["documents"] = [{"excerpt": "可选资料 " * 4000}]
        model_budget = min(2200, model_budget) if model_budget else 2200
    if spec.requiredQuestions:
        run.context["preferredQuestion"] = PIN["id"]
    if group == "B":
        run.context["taskContract"] = spec.prompt()
    recovery_target = "VERIFIED" if case.name == "takeover_verified_checkpoint" else "REPAIRING"
    durable, events, saved = {}, [], []
    interrupted = False

    async def checkpoint(value):
        nonlocal interrupted
        durable.update(copy.deepcopy(value))
        if real_model is None and case.recovery and value["stage"] == recovery_target and not interrupted:
            interrupted = True
            raise InterruptedError("simulated worker exit after commit")

    async def event(value):
        events.append(value)

    async def save(value):
        nonlocal interrupted
        saved.append(value)
        if real_model is None and group in {"A", "B"} and case.name == "takeover_verified_checkpoint":
            interrupted = True
            raise InterruptedError("simulated exit after saving legacy draft")

    callbacks = SimpleNamespace(plan=save, record_event=event)
    trace = CareerTrace(run, callbacks)
    try:
        if group in {"A", "B"}:
            try:
                await execute_training(run, model, callbacks, "生成岗位训练计划。", trace,
                                       native_catalog=True, model_budget=model_budget)
            except InterruptedError:
                interrupted = True
                if not saved:
                    await execute_training(run, model, callbacks, "生成岗位训练计划。", trace,
                                           native_catalog=True, model_budget=model_budget)
        else:
            state = TrainingExecution(spec, None, checkpoint)
            try:
                await generate_verified_plan(run, model, trace, {"instructions": "生成岗位训练计划。"},
                                             run.context, state, model_budget)
            except InterruptedError:
                state = TrainingExecution(spec, TrainingProgress.model_validate(durable), checkpoint)
                if state.state.stage == "VERIFIED":
                    await callbacks.plan(state.state.candidate.draft())
                else:
                    await generate_verified_plan(run, model, trace, {"instructions": "生成岗位训练计划。"},
                                                 run.context, state, model_budget)
    except (InvalidCareerToolResponse, TrainingContractError, CareerContextTooLarge, APIError, TimeoutError) as error:
        report["error"] = getattr(error, "code", type(error).__name__)
    call_events = [item for item in events if item["step"] not in {"list_training_questions", "training_deterministic"}]
    report["calls"] = durable.get("modelCalls", len(call_events)) if real_model else model.calls
    report["recordedUsage"] = [item["inputTokens"] + item["outputTokens"] for item in call_events
                               if item["inputTokens"] is not None and item["outputTokens"] is not None]
    if report["calls"]:
        if real_model is None and group in {"A", "B"}:
            report["firstPass"] = bool(initial and verify_plan(TrainingPlan.model_validate(initial), spec, catalog, set()).passed)
        else:
            report["firstPass"] = bool(call_events and call_events[0]["outcome"] == "succeeded")
    if saved:
        final = (observe_legacy(saved[0]) if group in {"A", "B"} else TrainingPlan.model_validate(
            {key: value for key, value in saved[0].items() if key != "steps"},
        ))
        checked = verify_plan(final, spec, catalog, set())
        if judge and checked.passed:
            rubric = RubricDef(name="career_training", dims=[
                RubricDim(key="practicality", label="可执行性", weight=0.34, desc="步骤具体、节奏可行"),
                RubricDim(key="relevance", label="岗位相关性", weight=0.33, desc="对应岗位职责与技能"),
                RubricDim(key="learning", label="复习与反馈", weight=0.33, desc="利用可用练习证据并安排合理顺序"),
            ])
            score = await judge.verify(topic=JOB["title"], rubric=rubric, artifact={
                "job": JOB, "requirements": spec.prompt(), "plan": final.draft(),
                "practice": [{"skill": item["skill"], "misses": item["misses"], "sampleSize": item["sampleSize"]}
                             for item in (learning or {}).get("priorities", [])],
            })
            report["semanticScore"] = score.total if score.feedback.get("summary") else None
        selected = {(ref.id, ref.version) for ref in final.questions}
        chosen = [item for item in catalog if question_key(item) in selected]
        covered = set().union(*(topic_skills(item["topic"], set(spec.requiredSkills)) for item in chosen))
        report.update(saved=True, success=checked.passed, accepted=checked.passed,
                      required=[len(covered), len(spec.requiredSkills)],
                      pinned=[sum((ref.id, ref.version) in selected for ref in spec.requiredQuestions), len(spec.requiredQuestions)],
                      weak=[int(case.history == "weak" and ("redis-2", 1) in selected), int(case.history == "weak")])
        if not checked.passed:
            report["error"] = [issue.code for issue in checked.errors]
        if real_model is None and initial and report["firstPass"] is False:
            initially_valid = {(item["id"], item["version"]) for item in initial["questions"]} & {
                question_key(item) for item in catalog if not item.get("practiceCompleted")
            }
            report["validQuestionRetention"] = [len(selected & initially_valid), len(initially_valid)]
            report["analysisKept"] = final.analysis == initial["analysis"]
    if report["firstPass"] is False:
        report["repair"] = report["success"]
    if interrupted:
        report["recovery"] = report["success"]
    report["modelReservations"] = durable.get("modelCalls", report["calls"])
    report["repairRounds"] = durable.get("repairRounds")
    report["transientRetries"] = durable.get("transientRetries", 0)
    report["elapsedMs"] = (perf_counter() - started) * 1000
    return report


def summarize(rows: list[dict]) -> dict:
    def boolean_metric(key):
        values = [row[key] for row in rows if row[key] is not None]
        return [sum(values), len(values)]

    def coverage(key):
        values = [row[key] for row in rows if row[key] is not None]
        return [sum(value[0] for value in values), sum(value[1] for value in values)]

    count = len(rows)
    calls = sum(row["calls"] for row in rows)
    usage = [tokens for row in rows for tokens in row["recordedUsage"]]
    scores = [row["semanticScore"] for row in rows if row.get("semanticScore") is not None]
    latencies = sorted(row["elapsedMs"] for row in rows)
    possible = [row for row in rows if row["expected"] == "success"]
    saved = [row for row in rows if row["saved"]]
    expected_rejections = {"reject": "TASK_CONTRACT_UNSATISFIABLE", "clarify": "CONTRACT_CONFIRMATION_REQUIRED",
                           "budget": "CareerContextTooLarge"}
    rejected = [row for row in rows if row["expected"] in expected_rejections]
    return {
        "taskSuccess": boolean_metric("success"), "constraintSatisfaction": [sum(row["accepted"] for row in rows),
                                                                          sum(row["saved"] for row in rows)],
        "firstPass": boolean_metric("firstPass"), "repairSuccess": boolean_metric("repair"),
        "avgLlmCalls": round(calls / count, 3), "modelCalls": calls,
        "usageCalls": [len(usage), calls], "avgTokensPerMeasuredCall": round(sum(usage) / len(usage), 3) if usage else None,
        "p95LatencyMs": round(latencies[math.ceil(count * 0.95) - 1], 3), "requiredSkillCoverage": coverage("required"),
        "weakSkillCoverage": coverage("weak"), "pinnedQuestionRetention": coverage("pinned"),
        "checkpointRecovery": boolean_metric("recovery"), "validQuestionRetention": coverage("validQuestionRetention"),
        "analysisRetention": boolean_metric("analysisKept"),
        "semanticMean": round(sum(scores) / len(scores), 4) if scores else None, "semanticSamples": len(scores),
        "feasibleSuccess": [sum(row["success"] for row in possible), len(possible)],
        "falseAcceptances": [sum(not row["accepted"] for row in saved), len(saved)],
        "falseRejections": [sum(not row["saved"] for row in possible), len(possible)],
        "correctRejections": [sum(row.get("error") == expected_rejections[row["expected"]] for row in rejected), len(rejected)],
        "effectiveRepairRounds": sum(row.get("repairRounds") or 0 for row in rows),
        "transientRetries": sum(row.get("transientRetries", 0) for row in rows),
        "failures": {row["case"]: row.get("error") for row in rows if not row["success"]},
    }


async def main(user: UUID | None, *, semantic: bool, groups="ABCDE", repeat=1, extended=False, details=False):
    model = budget = judge = None
    try:
        if user:
            async with SessionLocal() as session:
                model, config = await build_default_chat_model(session, user, temperature=0.2, streaming=False,
                                                               deepseek_tool_mode=True, max_retries=0)
                if semantic:
                    judge = await build_verifier(session, user, kind=settings.loop_verifier_kind, generator_model=model)
            window, reserve = chat_context_budget(config, career=True)
            model.max_tokens, budget = reserve, window - reserve
        cases = (*CASES, *EXTENDED_CASES) if extended else CASES
        for group in groups:
            rows = [{**await execute_case(case, group, model, budget, judge), "repeat": iteration + 1}
                    for iteration in range(repeat) for case in cases]
            runs = [summarize(rows[i:i + len(cases)])["feasibleSuccess"] for i in range(0, len(rows), len(cases))]
            print(json.dumps({"mode": "real_model" if user else "simulated_model", "group": group,
                              "model": model.model_name if model else ScriptedModel.model_name,
                              "temperature": 0.2 if model else None, "cases": len(rows), "feasibleSuccessPerRun": runs,
                              **summarize(rows), **({"caseDetails": rows} if details else {})}, ensure_ascii=False), flush=True)
    finally:
        if user:
            await close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-user", type=UUID, help="显式授权使用此测试账户配置的模型，仅发送合成输入。")
    parser.add_argument("--semantic", action="store_true", help="另行调用配置的 Verifier，对通过业务校验的结果评分。")
    parser.add_argument("--groups", default="ABCDE")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--extended", action="store_true")
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()
    if args.semantic and not args.live_user:
        parser.error("--semantic requires --live-user")
    if not 1 <= args.repeat <= 20 or not args.groups or any(group not in "ABCDE" for group in args.groups):
        parser.error("--repeat must be 1–20 and --groups must contain only A–E")
    asyncio.run(main(args.live_user, semantic=args.semantic, groups=args.groups, repeat=args.repeat,
                     extended=args.extended, details=args.details))
