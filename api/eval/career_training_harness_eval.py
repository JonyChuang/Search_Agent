"""Replay deterministic training-catalog cases with and without practice feedback."""

import json

from app.services.career_question_catalog import order_questions, required_skills, skills_in
from app.services.career_training_harness import learn_from_attempts, learning_candidates

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


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
