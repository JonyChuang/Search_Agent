"""Convert recent, graded practice into auditable training priorities."""

from collections import defaultdict

from app.services.career_learning_state import LEARNING_V2
from app.services.career_question_catalog import question_key, required_skills, skills_in
from app.services.career_training_contract import topic_skills

POLICY_VERSION = "objective-practice-v1"


def learn_from_attempts(attempts: list[dict], job: dict) -> dict | None:
    """Use the latest attempt per question, retaining exact versions for lookup."""
    required = required_skills(job)
    evidence = defaultdict(list)
    seen_questions = set()
    attempted = set()
    for attempt in attempts:
        question_id = attempt["questionId"]
        attempted.add((question_id, attempt["questionVersion"]))
        if question_id in seen_questions:
            continue
        seen_questions.add(question_id)
        for skill in required & skills_in(attempt["topic"]):
            evidence[skill].append(attempt)

    priorities = []
    for skill, records in evidence.items():
        misses = [record["attemptId"] for record in records if not record["correct"]]
        if len(misses) >= 2 and len(misses) * 2 >= len(records):
            priorities.append({"skill": skill, "misses": len(misses), "sampleSize": len(records), "evidence": misses})
    priorities.sort(key=lambda item: (-item["misses"] / item["sampleSize"], -item["misses"], item["skill"]))
    if not priorities:
        return None
    return {
        "policyVersion": POLICY_VERSION,
        "priorities": priorities[:3],
        "attempted": [list(key) for key in sorted(attempted)],
    }


def learning_candidates(catalog: list[dict], learning: dict | None) -> dict[tuple[str, int], tuple[str, ...]]:
    """Map eligible, unattempted question versions to current practice priorities."""
    if not learning or learning.get("policyVersion") not in {POLICY_VERSION, LEARNING_V2}:
        return {}
    attempted = {tuple(key) for key in learning["attempted"]}
    priorities = [item["skill"] for item in learning["priorities"]]
    due = {item["skill"] for item in learning["priorities"] if item.get("reviewDue")}
    priority_set = set(priorities)
    matches = {}
    for question in catalog:
        key = question_key(question)
        if question.get("kind") == "OPEN":
            continue
        eligible = due if key in attempted or question.get("practiceCompleted") else priority_set
        question_skills = topic_skills(question.get("topic", ""), eligible)
        topics = tuple(skill for skill in priorities if skill in question_skills)
        if topics:
            matches[key] = topics
    return matches


def explain_learning(questions: list[dict], catalog: list[dict], learning: dict) -> dict:
    candidates = learning_candidates(catalog, learning)
    selected = {skill for question in questions for skill in candidates.get(question_key(question), ())}
    available = {skill for skills in candidates.values() for skill in skills}
    return {
        "policyVersion": learning["policyVersion"],
        "priorities": [
            {**item, "status": "SELECTED" if item["skill"] in selected else
                "AVAILABLE" if item["skill"] in available else "NO_CANDIDATE"}
            for item in learning["priorities"]
        ],
    }
