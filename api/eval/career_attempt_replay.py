"""Replay archived plans and graded practice using a chronological holdout."""

import argparse
import asyncio
import json
from datetime import timezone
from uuid import UUID

from sqlalchemy import text

from app.db.career import career_transaction, close
from app.services.career_learning_state import learning_state
from app.services.career_question_catalog import order_questions, question_key, required_skills, skills_in
from app.services.career_training_harness import learn_from_attempts, learning_candidates


async def replay(user: UUID, job: UUID) -> dict:
    metrics = {"mode": "historical_observation", "plans": 0, "plans_with_signal": 0,
               "weak_skills": 0, "covered_weak_skills": 0, "control_covered_weak_skills": 0,
               "followup_attempts": 0, "followup_correct": 0,
               "v1_prioritized_weak_skills": 0, "v2_prioritized_weak_skills": 0,
               "v1_top_k_weak_covered": 0, "v2_top_k_weak_covered": 0, "v2_exploration_skills": 0}
    bind = {"user": str(user), "job": str(job)}
    async with career_transaction() as db:
        plans = (await db.execute(text("""
            SELECT created_at, training_draft_at, context_json, training_catalog_json, result_json FROM career_task
            WHERE user_id = :user AND job_id = :job AND kind = 'TRAINING' AND status = 'SUCCEEDED'
              AND training_catalog_json IS NOT NULL AND result_json IS NOT NULL
            ORDER BY created_at DESC LIMIT 50
        """), bind)).mappings().all()
        attempt_sql = """
            SELECT a.request_id AS attemptId, a.question_id AS questionId, a.question_version AS questionVersion,
                a.correct, q.topic, a.submitted_at AS submittedAt FROM career_practice_attempt a JOIN career_question_version q
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
            context = json.loads(plan["context_json"])
            catalog = json.loads(plan["training_catalog_json"])
            history = [dict(item) for item in earlier]
            control_v1 = learn_from_attempts(history, context["job"])
            skills = (context.get("trainingContract") or {}).get("requiredSkills") or sorted(required_skills(context["job"]))
            control_v2 = learning_state(history, skills, plan["created_at"].replace(tzinfo=timezone.utc))
            chosen = {question_key(item) for item in json.loads(plan["result_json"])["questions"]}
            for version, policy in (("v1", control_v1), ("v2", control_v2)):
                priorities = (policy or {}).get("priorities", [])
                weak = {item["skill"] for item in priorities if item.get("masteryStatus", "WEAK") == "WEAK"}
                ranked_targets = learning_candidates(catalog, policy)
                ordered = order_questions(sorted(catalog, key=question_key), context["job"],
                                          context.get("preferredQuestion"), ranked_targets)
                metrics[f"{version}_prioritized_weak_skills"] += len(weak)
                metrics[f"{version}_top_k_weak_covered"] += len(weak & {
                    skill for item in ordered[:len(chosen)] for skill in ranked_targets.get(question_key(item), ())
                })
            metrics["v2_exploration_skills"] += sum(item["masteryStatus"] == "EXPLORE" for item in control_v2["priorities"])
            learning = context.get("practiceLearning") or control_v1
            if not learning:
                continue
            metrics["plans_with_signal"] += 1
            targets = learning_candidates(catalog, learning)
            # The control uses the same archived candidates and plan size with practice priorities disabled.
            control = order_questions(sorted(catalog, key=question_key), context["job"], context.get("preferredQuestion"))
            weak = {item["skill"] for item in learning["priorities"] if item.get("masteryStatus", "WEAK") == "WEAK"}
            covered = weak & {skill for key in chosen for skill in targets.get(key, ())}
            metrics["weak_skills"] += len(weak)
            metrics["covered_weak_skills"] += len(covered)
            metrics["control_covered_weak_skills"] += len(weak & {
                skill for item in control[:len(chosen)] for skill in targets.get(question_key(item), ())
            })
            later = (await db.execute(text(attempt_sql + """
                a.submitted_at >= :available AND a.submitted_at < TIMESTAMPADD(DAY, 30, :available)
                ORDER BY a.sequence_id ASC LIMIT 150
            """), {**params, "available": plan["training_draft_at"] or plan["created_at"]})).mappings().all()
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
