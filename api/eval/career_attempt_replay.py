"""Replay archived plans and graded practice using a chronological holdout."""

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import text

from app.db.career import career_transaction, close
from app.services.career_question_catalog import question_key, skills_in
from app.services.career_training_harness import learn_from_attempts, learning_candidates


async def replay(user: UUID, job: UUID) -> dict:
    metrics = {"plans": 0, "plans_with_signal": 0, "weak_skills": 0, "covered_weak_skills": 0,
               "followup_attempts": 0, "followup_correct": 0}
    bind = {"user": str(user), "job": str(job)}
    async with career_transaction() as db:
        plans = (await db.execute(text("""
            SELECT created_at, context_json, training_catalog_json, result_json FROM career_task
            WHERE user_id = :user AND job_id = :job AND kind = 'TRAINING' AND status = 'SUCCEEDED'
              AND training_catalog_json IS NOT NULL AND result_json IS NOT NULL
            ORDER BY created_at DESC LIMIT 50
        """), bind)).mappings().all()
        attempt_sql = """
            SELECT a.request_id AS attemptId, a.question_id AS questionId, a.question_version AS questionVersion,
                a.correct, q.topic FROM career_practice_attempt a JOIN career_question_version q
                ON (q.id, q.version) = (a.question_id, a.question_version)
            WHERE a.user_id = :user AND a.job_id = :job AND
        """
        for plan in plans:
            metrics["plans"] += 1
            params = {**bind, "created": plan["created_at"]}
            earlier = (await db.execute(text(attempt_sql + """
                a.submitted_at < :created AND a.submitted_at >= TIMESTAMPADD(DAY, -30, :created)
                ORDER BY a.sequence_id DESC LIMIT 60
            """), params)).mappings().all()
            learning = learn_from_attempts([dict(item) for item in earlier], json.loads(plan["context_json"])["job"])
            if not learning:
                continue
            metrics["plans_with_signal"] += 1
            targets = learning_candidates(json.loads(plan["training_catalog_json"]), learning)
            chosen = {question_key(item) for item in json.loads(plan["result_json"])["questions"]}
            weak = {item["skill"] for item in learning["priorities"]}
            covered = {skill for key in chosen for skill in targets.get(key, ())}
            metrics["weak_skills"] += len(weak)
            metrics["covered_weak_skills"] += len(covered)
            later = (await db.execute(text(attempt_sql + """
                a.submitted_at >= :created AND a.submitted_at < TIMESTAMPADD(DAY, 30, :created)
                ORDER BY a.sequence_id ASC LIMIT 150
            """), params)).mappings().all()
            seen = set()
            for item in later:
                key = item["questionId"], item["questionVersion"]
                if key in seen or key not in chosen or not (skills_in(item["topic"]) & weak):
                    continue
                seen.add(key)
                metrics["followup_attempts"] += 1
                metrics["followup_correct"] += bool(item["correct"])
    return metrics


async def _main(user, job):
    try:
        print(json.dumps(await replay(user, job), indent=2))
    finally:
        await close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, type=UUID)
    parser.add_argument("--job", required=True, type=UUID)
    args = parser.parse_args()
    asyncio.run(_main(args.user, args.job))
