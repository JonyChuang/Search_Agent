"""Replay deterministic training-catalog cases with and without practice feedback."""

import argparse
import json
from datetime import datetime, timedelta, timezone

from app.services.career_learning_state import TrainingUtilityWeights, learning_state, with_training_utility
from app.services.career_question_catalog import order_questions, question_key, required_skills, skills_in
from app.services.career_training_contract import TrainingRequirements, build_contract, feasible_questions
from app.services.career_training_harness import learn_from_attempts, learning_candidates, question_utilities

CASES = (
    ("Java", "Redis", "Spring"),
    ("Java 并发", "MySQL", "Kafka"),
    ("MySQL", "Spring", "Redis"),
    ("Redis", "Java", "MySQL"),
    ("消息队列", "Spring", "Redis"),
    ("Python", "RAG", "Agent"),
    ("RAG", "Agent", "Python"),
    ("Agent", "RAG", "机器学习"),
)


def run() -> dict:
    metrics = {name: {"weakTopicNextQuestion": 0, "requiredSkillsCovered": 0, "pinnedRetained": 0}
               for name in ("baseline", "harness")}
    total_skills = 0
    for index, (weak, *other) in enumerate(CASES):
        job = {"skills": " / ".join(other + [weak])}
        topics = [*other, weak, weak, *other, weak]
        catalog = [{"id": f"q{i}", "version": 1, "topic": topic} for i, topic in enumerate(topics)]
        if index % 4 == 0:
            catalog.insert(2, catalog.pop())  # Existing relevance order already picks a fresh weak-topic question.
        misses = [
            {"attemptId": f"attempt-{i}", "questionId": f"q{i}", "questionVersion": 1,
             "correct": False, "topic": weak}
            for i in (2, 3)
        ]
        learned = learn_from_attempts(misses, job)
        targets = learning_candidates(catalog, learned)
        needed = required_skills(job)
        total_skills += len(needed)
        for name, policy in (("baseline", {}), ("harness", targets)):
            shortlist = order_questions(catalog, job, "q0", policy)[:4]
            coverage = set().union(*(skills_in(item["topic"]) for item in shortlist))
            metrics[name]["requiredSkillsCovered"] += len(coverage & needed)
            metrics[name]["pinnedRetained"] += shortlist[0]["id"] == "q0"
            metrics[name]["weakTopicNextQuestion"] += any(item["id"] == "q6" for item in shortlist)
    return {"scenarioCount": len(CASES), "requiredSkillTotal": total_skills, "topK": 4, **metrics}


def compare_policies() -> dict:
    """Compare selection using annotated evidence and a common hard-constraint solver."""
    now = datetime(2026, 11, 26, 8, tzinfo=timezone.utc)
    skill_names = {"r": "Redis", "m": "MySQL", "p": "Python", "s": "Spring"}
    base = [{"id": f"{prefix}-{n}", "version": 2 if n == 0 else 1, "topic": name}
            for prefix, name in skill_names.items() for n in range(6)]
    base.append({"id": "multi", "version": 1, "topic": "Redis MySQL"})

    def attempts(prefix, ages, correct, *, old=False):
        for n, age in enumerate(ages):
            yield {"attemptId": f"{prefix}-{n}-{age}", "questionId": f"{prefix}-{n}",
                   "questionVersion": 1 if old or n else 2, "currentVersion": 2 if n == 0 else 1,
                   "correct": correct, "topic": skill_names[prefix], "submittedAt": now - timedelta(days=age)}

    weak_r = list(attempts("r", [0, 1, 2], False))
    weak_m = list(attempts("m", [0, 1, 3], False))
    improving = [*attempts("r", [0, 1, 2], True), *attempts("r", [8, 9, 10], False), *weak_m]
    consolidate = list(attempts("r", [8, 9, 10, 11], True))
    repeated = [{**weak_r[0], "attemptId": f"dup-{age}", "submittedAt": now - timedelta(days=age)} for age in range(8)]
    samples = [
        ("cold", [], "Redis MySQL Python", 4, (), ("Redis", "MySQL", "Python"), (), False),
        ("multiple_weak", [*weak_r, *weak_m], "Redis MySQL Python", 5, ("Redis", "MySQL"), ("Python",), (), False),
        ("recent_improvement", improving, "Redis MySQL Python", 5, ("MySQL",), ("Python",), (), False),
        ("stale", list(attempts("r", [25, 26, 27], False)), "Redis MySQL Python", 4, (), ("Redis",), (), False),
        ("insufficient", weak_r[:1], "Redis MySQL Python", 4, (), ("Redis",), (), False),
        ("repeated", repeated, "Redis MySQL Python", 4, (), ("Redis",), (), False),
        ("version", list(attempts("r", [0, 26], False, old=True)), "Redis MySQL Python", 4, (), ("Redis",), (), False),
        ("changed_job", weak_r, "Spring MySQL Python", 4, (), ("Spring", "MySQL", "Python"), (), False),
        ("limited_slots", [*weak_r, *weak_m], "Redis MySQL Python", 3, ("Redis", "MySQL"), ("Python",), (), True),
        ("due_consolidation", [*consolidate, *weak_m], "Redis MySQL Python", 5, ("MySQL",), ("Python",), ("Redis",), False),
    ]
    metrics = {group: {name: [0, 0] for name in ("required", "weakFresh", "exploreFresh", "dueReview",
                                                     "pinned", "freshRelevant", "repeated", "weakExtraSlots")}
               for group in "ABCD"}
    rows = []
    for name, history, skills, count, weak, explore, due, exclude in samples:
        job = {"skills": skills}
        history.sort(key=lambda item: item["submittedAt"], reverse=True)
        attempted = {(item["questionId"], item["questionVersion"]) for item in history}
        catalog = [{**item, "practiceCompleted": question_key(item) in attempted} for item in base
                   if skills_in(item["topic"]) & required_skills(job)]
        spec = build_contract(
            user="fixture", job_id="fixture", conversation=None, job=job, preferred=None,
            requirements=TrainingRequirements(questionCount=count, requiredQuestions=[{"id": "p-5", "version": 1}],
                                               excludeCompleted=exclude), request_text="", pinned=[], created_at=now,
            repair="local-v1", learning="objective-practice-v1",
        )
        original = learning_state(history, spec.requiredSkills, now)
        weighted = with_training_utility(original, job_skills=spec.jobSkills, preferred=[], as_of=now,
                                         weights=TrainingUtilityWeights())
        row = {"case": name, "selections": {}}
        for group, policy in zip("ABCD", (None, learn_from_attempts(history, job), original, weighted), strict=True):
            targets = learning_candidates(catalog, policy)
            utility = question_utilities(catalog, policy)
            ordered = order_questions(catalog, job, "p-5", targets, utility=utility)
            selected = []
            feasible_questions(spec, ordered, utility=utility, witness=selected)
            items = {question_key(item): skills_in(item["topic"]) for item in catalog}
            picked = {question_key(item) for item in selected}
            fresh = picked - attempted
            fresh_topics = set().union(*(items[key] for key in fresh))
            repeated_topics = set().union(*(items[key] for key in picked & attempted))
            covered = fresh_topics | repeated_topics
            values = {
                "required": (len(covered & set(spec.requiredSkills)), len(spec.requiredSkills)),
                "weakFresh": (len(fresh_topics & set(weak)), len(weak)),
                "exploreFresh": (len(fresh_topics & set(explore)), len(explore)),
                "dueReview": (len(repeated_topics & set(due)), len(due)),
                "pinned": (int(("p-5", 1) in picked), 1),
                "freshRelevant": (sum(bool(items[key] & set(spec.requiredSkills)) for key in fresh), count),
                "repeated": (len(picked & attempted), count),
                "weakExtraSlots": (max(0, sum(bool(items[key] & set(weak)) for key in fresh) - len(weak)), count),
            }
            for key, (numerator, denominator) in values.items():
                metrics[group][key][0] += numerator
                metrics[group][key][1] += denominator
            row["selections"][group] = [q["id"] for q in selected]
        rows.append(row)
    return {"mode": "deterministic_selection", "cases": len(samples), "metrics": metrics, "caseDetails": rows,
            "modelAdoption": None, "unseenQuestionTransfer": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policies", action="store_true", help="Compare four learning policies using a common selector.")
    print(json.dumps(compare_policies() if parser.parse_args().policies else run(), ensure_ascii=False, indent=2))
