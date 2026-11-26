"""Replay the same model faults against either Harness V2 revision with identical budgets."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.services.career_task_service import CareerRun, CareerTrace, generate_verified_plan
from app.services.career_training_contract import TrainingContractError, TrainingRequirements, build_contract
from app.services.career_training_runtime import TrainingExecution, TrainingProgress
from eval.harness_v2_eval import CATALOG, CREATED, JOB, plan_for


SCENARIOS = {
    "initial_timeout": ("timeout", "good"),
    "repair_timeout": ("invalid", "timeout", "good"),
    "repair_timeout_then_throttle": ("invalid", "timeout", "throttle", "good"),
    "repair_candidates_invalid": ("invalid", "invalid", "invalid"),
    "reservation_interrupted_during_repair": ("invalid", "interrupted", "good"),
}


async def execute_case(name, outputs):
    spec = build_contract(
        user="fixture", job_id="fixture", conversation=None, job=JOB, preferred=None,
        requirements=TrainingRequirements(questionCount=2), request_text="", pinned=[], created_at=CREATED,
        repair="local-v1", learning="objective-practice-v1",
    )
    spec.budget = spec.budget.model_copy(update={"maxModelCalls": 5, "maxRepairRounds": 2})
    run = CareerRun(id=uuid4(), lease=uuid4(), userId=uuid4(), kind="TRAINING", context={"job": JOB}, trainingCatalog=CATALOG)
    output_queue = iter(outputs)
    good = plan_for(CATALOG, spec)
    invalid = deepcopy(good)
    invalid["questions"][0]["id"] = "unlisted"
    state, saved = {}, []
    repair_candidates = retries = recoveries = 0

    async def checkpoint(value):
        state.update(deepcopy(value))

    async def record_event(event):
        pass

    async def save(value):
        saved.append(value)

    class Throttle(Exception):
        pass

    def bind(*args, tool_choice):
        async def invoke(messages):
            nonlocal repair_candidates
            action = next(output_queue)
            if action == "interrupted":
                raise asyncio.CancelledError()
            if action == "timeout":
                raise TimeoutError()
            if action == "throttle":
                raise Throttle()
            repair_candidates += bool(state.get("lastReport"))
            plan = deepcopy(good if action == "good" else invalid)
            if tool_choice == "TrainingPlanPatch":
                plan = {key: plan[key] for key in ("questions", "schedule")}
            return AIMessage(content="", tool_calls=[{"name": tool_choice, "args": plan, "id": "fixture"}])

        return SimpleNamespace(ainvoke=invoke)

    callbacks = SimpleNamespace(plan=save, record_event=record_event)
    model = SimpleNamespace(bind_tools=bind, model_name="fault-injection-fixture")
    error = None
    while not saved:
        runtime = TrainingExecution(spec, TrainingProgress.model_validate(state) if state else None, checkpoint)
        try:
            await generate_verified_plan(run, model, CareerTrace(run, callbacks), {"instructions": "生成训练计划。"},
                                         run.context, runtime, None)
        except (TimeoutError, Throttle):
            if retries >= 2:
                error = "TRANSIENT_MODEL_ERROR"
                break
            retries += 1
        except asyncio.CancelledError:
            recoveries += 1
        except TrainingContractError as exc:
            error = exc.code
            break
    return {"case": name, "success": len(saved) == 1, "error": error,
            "modelAttempts": state.get("modelCalls", 0), "effectiveRepairRounds": repair_candidates,
            "persistedRepairRounds": state.get("repairRounds", 0), "transientRetries": retries, "recoveries": recoveries}


async def main():
    rows = [await execute_case(name, outputs) for name, outputs in SCENARIOS.items()]
    print(json.dumps({"usage": None, "modelAttemptLimit": 5, "repairLimit": 2, "transientRetryLimit": 2,
                      "runCount": len(rows), "successes": sum(row["success"] for row in rows), "cases": rows}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
