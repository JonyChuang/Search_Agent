"""Estimate skill mastery from the latest graded evidence for each distinct question."""

from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.services.career_training_contract import topic_skills

LEARNING_V2 = "objective-practice-v2"
LEARNING_UTILITY = "objective-practice-v2-utility"
HALF_LIFE_DAYS = 14


class TrainingUtilityWeights(BaseModel):
    weak: float = Field(default=2.0, gt=0, le=10)
    evidenceGap: float = Field(default=2.0, ge=0, le=10)
    explore: float = Field(default=1.4, gt=0, le=10)
    uncertainty: float = Field(default=0.6, ge=0, le=10)
    consolidate: float = Field(default=0.7, gt=0, le=10)
    dueReview: float = Field(default=0.8, ge=0, le=10)
    recency: float = Field(default=0.5, ge=0, le=10)
    jobSkill: float = Field(default=0.2, ge=0, le=10)
    preference: float = Field(default=0.25, ge=0, le=10)


def _timestamp(value: datetime | str) -> datetime:
    instant = datetime.fromisoformat(value) if isinstance(value, str) else value
    return instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc)


def learning_state(attempts: list[dict], skills: list[str], as_of: datetime) -> dict:
    evidence = defaultdict(list)
    scoped_skills = set(skills)
    seen = set()
    attempted = set()
    for attempt in sorted(attempts, key=lambda item: _timestamp(item["submittedAt"]), reverse=True):
        instant = _timestamp(attempt["submittedAt"])
        if instant > as_of:
            continue
        identifier, version = attempt["questionId"], attempt["questionVersion"]
        attempted.add((identifier, version))
        if identifier in seen:
            continue
        seen.add(identifier)
        weight = 0.5 ** ((as_of - instant).total_seconds() / (HALF_LIFE_DAYS * 86400))
        if attempt.get("currentVersion", version) != version:
            weight *= 0.5
        for skill in topic_skills(attempt["topic"], scoped_skills):
            evidence[skill].append((attempt, instant, weight))

    priorities = []
    for skill in skills:
        records = evidence[skill]
        total = sum(weight for _, _, weight in records)
        correct = sum(weight for attempt, _, weight in records if attempt["correct"])
        estimate = (1 + correct) / (2 + total)
        misses = sum(not attempt["correct"] for attempt, _, _ in records)
        if total < 1.5 or len(records) < 2:
            status, reason = "EXPLORE", "近期有效练习证据不足，建议先做题测评。"
        elif misses >= 2 and estimate < 0.45:
            status, reason = "WEAK", "近期多道不同题目回答错误，建议优先补强。"
        else:
            status, reason = "CONSOLIDATE", "根据已有答题证据安排巩固练习。"
        priorities.append({
            "skill": skill, "sampleSize": len(records), "misses": misses, "correctCount": len(records) - misses,
            "masteryScore": round(estimate, 4), "effectiveSampleSize": round(total, 4),
            "confidence": round(total / (2 + total), 4), "masteryStatus": status, "reason": reason,
            "lastPracticedAt": records[0][1].isoformat() if records else None,
            "reviewDue": bool(status == "CONSOLIDATE" and records and (as_of - records[0][1]).days >= 7),
            "evidence": [attempt["attemptId"] for attempt, _, _ in records],
        })
    priorities.sort(key=lambda item: (
        ("WEAK", "EXPLORE", "CONSOLIDATE").index(item["masteryStatus"]), item["masteryScore"], item["skill"],
    ))
    return {"policyVersion": LEARNING_V2, "priorities": priorities, "attempted": [list(key) for key in sorted(attempted)]}


def with_training_utility(
    learning: dict, *, job_skills: list[str], preferred: list[str], as_of: datetime, weights: TrainingUtilityWeights,
) -> dict:
    priorities = []
    for item in learning["priorities"]:
        status = item["masteryStatus"]
        confidence = item["confidence"]
        last = item["lastPracticedAt"]
        age = min(30, max(0, (as_of - _timestamp(last)).days)) / 30 if last else 0
        if status == "WEAK":
            score = weights.weak + weights.evidenceGap * confidence * (1 - item["masteryScore"])
        elif status == "EXPLORE":
            score = weights.explore + weights.uncertainty * (1 - confidence)
        else:
            score = weights.consolidate + weights.dueReview * item["reviewDue"]
        score += weights.recency * age
        score += weights.jobSkill * (item["skill"] in job_skills) + weights.preference * (item["skill"] in preferred)
        priorities.append({**item, "trainingUtility": round(score, 4)})
    priorities.sort(key=lambda item: (-item["trainingUtility"], item["skill"]))
    return {**learning, "policyVersion": LEARNING_UTILITY, "priorities": priorities, "utilityWeights": weights.model_dump()}
