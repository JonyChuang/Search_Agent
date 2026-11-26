"""Recheck a local fixture or an owner-scoped training diagnostic without a model call."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text

from app.db.career import career_transaction, close
from app.services.career_queue import TRAINING_EVENT_RETENTION_DAYS, CareerQueue
from app.services.career_training_contract import TrainingContract
from app.services.career_training_verifier import TrainingPlan, repair_locally, schema_report, verify_plan


def replay(value: dict) -> dict:
    contract = TrainingContract.model_validate(value["contract"])
    catalog = value["catalog"]
    evidence = set(value.get("confirmedExperienceIds", []))
    try:
        plan = TrainingPlan.model_validate(value["candidate"])
    except ValidationError as error:
        return {"validation": schema_report(error).public(), "repair": None}
    report = verify_plan(plan, contract, catalog, evidence)
    fixed = repair_locally(plan, report, contract, catalog) if contract.repairVersion == "local-v1" else None
    return {"validation": report.public(),
            "repair": verify_plan(fixed, contract, catalog, evidence).public() if fixed else None}


async def archived(owner: UUID, task_id: UUID) -> list[dict]:
    try:
        async with career_transaction() as db:
            queue = CareerQueue(db)
            task = await queue.owned(str(owner), str(task_id))
            contract = task["context_json"].get("trainingContract")
            if not contract:
                return []
            rows = (await db.execute(text("""
                SELECT generation, sequence_no, details_json FROM career_task_event
                WHERE task_id = :task AND details_json IS NOT NULL AND outcome = 'failed'
                    AND created_at >= TIMESTAMPADD(DAY, :retention, CURRENT_TIMESTAMP(6))
                    AND step IN ('training_generate', 'training_patch', 'training_regenerate', 'training_deterministic')
                ORDER BY generation, sequence_no LIMIT 30
            """), {"task": str(task_id), "retention": -TRAINING_EVENT_RETENTION_DAYS})).mappings().all()
            results = []
            for row in rows:
                details = json.loads(row["details_json"])
                original = details.get("validation")
                candidate = details.get("replay")
                rerun = replay({"contract": contract, "catalog": task["training_catalog_json"],
                                "candidate": candidate}) if candidate else None
                results.append({"generation": row["generation"], "sequence": row["sequence_no"],
                                "original": original, "replay": rerun})
            return results
    finally:
        await close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="JSON object with contract, catalog and candidate")
    source.add_argument("--task", type=UUID, help="Task ID in the explicitly selected database")
    parser.add_argument("--owner", type=UUID, help="Owner of the archived task")
    args = parser.parse_args()
    if args.task and not args.owner:
        parser.error("--task requires --owner")
    result = replay(json.loads(args.fixture.read_text(encoding="utf-8"))) if args.fixture else asyncio.run(
        archived(args.owner, args.task),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
