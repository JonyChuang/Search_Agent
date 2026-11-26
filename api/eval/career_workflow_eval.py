"""Measure validated final answers and checkpoint reuse in the training workflow."""

import argparse
import asyncio
import json
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage

from app.core.llm.chat_model import build_default_chat_model
from app.db.postgres import SessionLocal, close
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


async def run(model=None) -> dict:
    tasks = successes = satisfied = correct_calls = calls = recovered = recovery_cases = 0
    for index, (first, second) in enumerate(CASES):
        catalog = [{"id": key, "version": version, "topic": topic, "prompt": f"解释 {topic} 的原理"}
                   for key, version, topic in (("first", 2, first), ("second", 1, second))]
        resume = index % 2 == 1
        run = CareerRun(id=uuid4(), lease=uuid4(), userId=uuid4(), kind="TRAINING",
                        context={"job": {"skills": f"{first} / {second}"}, "preferredQuestion": "first"},
                        trainingCatalog=catalog if resume else None)
        plan = {"analysis": "覆盖岗位技能", "steps": ["逐项练习"],
                "questions": [{"id": item["id"], "version": item["version"]} for item in catalog]}
        callbacks = Mock(questions=AsyncMock(return_value=catalog), plan=AsyncMock(), record_event=AsyncMock())
        tasks += 1
        recovery_cases += resume
        try:
            await execute_training(run, model or _scripted_model(plan, repair=not resume), callbacks,
                                   "生成可执行的备考计划。", CareerTrace(run, callbacks), native_catalog=True)
        except (InvalidCareerToolResponse, TimeoutError):
            pass
        for event in callbacks.record_event.await_args_list:
            data = event.args[0]
            if data["step"] == "create_training_plan":
                calls += 1
                correct_calls += data["outcome"] == "succeeded"
        if callbacks.plan.await_count != 1:
            continue
        result = callbacks.plan.await_args.args[0]
        directory = {(item["id"], item["version"]): item["topic"] for item in catalog}
        refs = {(item["id"], item["version"]) for item in result["questions"]}
        valid = refs <= directory.keys() and ("first", 2) in refs and len(refs) == len(result["questions"])
        satisfied += valid
        covered = set().union(*(skills_in(directory[ref]) for ref in refs if ref in directory))
        success = valid and required_skills(run.context["job"]) <= covered
        successes += success
        recovered += resume and success and callbacks.questions.await_count == 0
    return {
        "mode": "live_model" if model else "scripted_model",
        "constraints": [satisfied, tasks], "task_success": [successes, tasks],
        "correct_tool_calls": [correct_calls, calls], "checkpoint_recovery": [recovered, recovery_cases],
    }


async def _main(user: UUID | None):
    if user is None:
        print(json.dumps(await run(), indent=2))
        return
    try:
        async with SessionLocal() as session:
            model, _ = await build_default_chat_model(session, user, temperature=0.2, streaming=False,
                                                      deepseek_tool_mode=True)
        async with asyncio.timeout(180):
            print(json.dumps(await run(model), indent=2))
    finally:
        await close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-user", type=UUID, help="将合成评测问题发送给指定本地账户配置的模型")
    asyncio.run(_main(parser.parse_args().live_user))
