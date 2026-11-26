"""Measure validated final answers and checkpoint reuse in the training workflow."""

import argparse
import asyncio
import json
import re
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage
from openai import APIError

from app.core.llm.chat_model import build_default_chat_model, chat_context_budget
from app.db.postgres import SessionLocal, close
from app.services.career_context import CareerContextTooLarge
from app.services.career_question_catalog import required_skills, skills_in
from app.services.career_task_service import CareerRun, CareerTrace, InvalidCareerToolResponse, execute_training

CASES = (("Redis", "MySQL"), ("Java", "Spring"), ("Python", "RAG"), ("Agent", "消息队列"))


def _scripted_model(plan: dict, repair: bool):
    def response(value):
        return AIMessage(content="", tool_calls=[{"name": "create_training_plan", "args": value, "id": "eval-plan"}])

    model = Mock(model_name="eval-fixture")
    answers = [response(plan)]
    if repair:
        answers.insert(0, response({**plan, "questions": [{"id": "outside-catalog", "version": 3}]}))
    model.bind_tools.return_value.ainvoke = AsyncMock(side_effect=answers)
    return model


async def run(model=None, *, model_budget: int | None = None) -> dict:
    tasks = successes = satisfied = correct_calls = calls = recovered = recovery_cases = 0
    failures = []
    input_tokens = output_tokens = measured_calls = 0
    deadline_total = deadline_met = 0
    for index, (first, second) in enumerate(CASES):
        catalog = [{"id": key, "version": version, "topic": topic, "prompt": f"解释 {topic} 的原理"}
                   for key, version, topic in (("first", 2, first), ("second", 1, second))]
        resume = index % 2 == 1
        context = {"job": {"skills": f"{first} / {second}"}, "preferredQuestion": "first"}
        check_deadline = index in {0, 1}
        if check_deadline:
            deadline_total += 1
            context["studyConstraints"] = [{"field": "截止时间", "value": "周五", "confirmed": True, "version": 1}]
        run = CareerRun(id=uuid4(), lease=uuid4(), userId=uuid4(), kind="TRAINING", context=context,
                        trainingCatalog=catalog if resume else None)
        plan = {"analysis": "覆盖岗位技能", "steps": ["周五前逐项练习" if check_deadline else "逐项练习"],
                "questions": [{"id": item["id"], "version": item["version"]} for item in catalog]}
        callbacks = Mock(questions=AsyncMock(return_value=catalog), plan=AsyncMock(), record_event=AsyncMock())
        tasks += 1
        recovery_cases += resume
        try:
            await execute_training(run, model or _scripted_model(plan, repair=not resume), callbacks,
                                   "生成可执行的备考计划。", CareerTrace(run, callbacks), native_catalog=True,
                                   model_budget=model_budget)
        except (CareerContextTooLarge, InvalidCareerToolResponse, TimeoutError, APIError) as error:
            failures.append({"case": index + 1, "reason": type(error).__name__, "resume": resume})
        for event in callbacks.record_event.await_args_list:
            data = event.args[0]
            if data["step"] == "create_training_plan":
                calls += 1
                correct_calls += data["outcome"] == "succeeded"
                if data["inputTokens"] is not None and data["outputTokens"] is not None:
                    measured_calls += 1
                    input_tokens += data["inputTokens"]
                    output_tokens += data["outputTokens"]
        if callbacks.plan.await_count != 1:
            continue
        result = callbacks.plan.await_args.args[0]
        directory = {(item["id"], item["version"]): item["topic"] for item in catalog}
        refs = {(item["id"], item["version"]) for item in result["questions"]}
        valid = refs <= directory.keys() and ("first", 2) in refs and len(refs) == len(result["questions"])
        deadline_ok = not check_deadline or bool(re.search(r"周五|星期五|礼拜五", " ".join(result["steps"])))
        deadline_met += int(check_deadline and deadline_ok)
        valid = valid and deadline_ok
        satisfied += valid
        covered = set().union(*(skills_in(directory[ref]) for ref in refs if ref in directory))
        success = valid and required_skills(run.context["job"]) <= covered
        successes += success
        recovered += resume and success and callbacks.questions.await_count == 0
        if not success:
            reason = "deadline_missing" if not deadline_ok else "constraints" if not valid else "skill_coverage"
            failures.append({"case": index + 1, "reason": reason,
                             "resume": resume})
    return {
        "mode": "live_model" if model else "scripted_model",
        "constraints": [satisfied, tasks], "task_success": [successes, tasks],
        "correct_tool_calls": [correct_calls, calls], "checkpoint_recovery": [recovered, recovery_cases],
        "deadline_mentioned_in_steps": [deadline_met, deadline_total],
        "failure_cases": failures, "token_usage_calls": measured_calls,
        "tokens": {"input": input_tokens, "output": output_tokens} if measured_calls else None,
        "database_checkpoints": False,
    }


async def _main(user: UUID | None):
    if user is None:
        print(json.dumps(await run(), indent=2))
        return
    try:
        async with SessionLocal() as session:
            model, config = await build_default_chat_model(session, user, temperature=0.2, streaming=False,
                                                           deepseek_tool_mode=True)
        budget = None
        if config.context_window_tokens:
            window, reserve = chat_context_budget(config, career=True)
            model.max_tokens = reserve
            budget = window - reserve
        async with asyncio.timeout(180):
            print(json.dumps(await run(model, model_budget=budget), indent=2))
    finally:
        await close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-user", type=UUID, help="将合成评测问题发送给指定本地账户配置的模型")
    asyncio.run(_main(parser.parse_args().live_user))
