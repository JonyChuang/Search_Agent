"""Representative question ordering for a job-scoped training catalog."""

import re

_ALIASES = {
    "Java": ("java", "jvm", "集合框架"),
    "Java 并发": ("java 并发", "并发编程", "线程池", "juc", "threadpool", "多线程"),
    "Spring": ("spring", "spring boot", "springboot", "spring cloud", "spring mvc"),
    "MySQL": ("mysql", "innodb", "sql", "索引", "数据库事务"),
    "Redis": ("redis", "缓存穿透", "缓存击穿", "缓存雪崩", "分布式缓存"),
    "消息队列": ("消息队列", "kafka", "rabbitmq", "rocketmq"),
    "Python": ("python", "fastapi", "django", "flask"),
    "Agent": ("agent", "智能体", "function calling", "工具调用", "mcp"),
    "RAG": ("rag", "检索增强生成", "向量检索", "重排序"),
    "机器学习": ("机器学习", "machine learning", "pytorch", "深度学习"),
}
_ALIAS_PATTERN = {
    skill: re.compile("|".join(
        rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])" if alias.isascii() else re.escape(alias)
        for alias in aliases
    ), re.IGNORECASE)
    for skill, aliases in _ALIASES.items()
}
_REQUIRED = re.compile(r"必备|必需|要求|熟练|掌握|必须|required|must", re.IGNORECASE)


def skills_in(value: str) -> set[str]:
    return {skill for skill, pattern in _ALIAS_PATTERN.items() if pattern.search(value)}


def required_skills(job: dict) -> set[str]:
    skills = skills_in(job.get("skills") or "")
    for line in re.split(r"[\n。；]", job.get("jd") or ""):
        if _REQUIRED.search(line):
            skills.update(skills_in(line))
    return skills


def question_key(question: dict) -> tuple[str, int]:
    return question["id"], question["version"]


def order_questions(
    catalog: list[dict], job: dict, preferred: str | None = None,
    practice_targets: dict[tuple[str, int], tuple[str, ...]] | None = None,
) -> list[dict]:
    """Keep the requested question, then cover as many required skills as possible."""
    needed = required_skills(job)
    pending = list(catalog)
    selected = []
    practice_targets = practice_targets or {}
    if preferred:
        requested = next((item for item in pending if item["id"] == preferred), None)
        if requested is not None:
            selected.append(requested)
            pending.remove(requested)
            needed -= skills_in(requested.get("topic", ""))
    while pending and needed:
        topics = [skills_in(item.get("topic", "")) & needed for item in pending]
        best = max(range(len(pending)), key=lambda index: (
            len(topics[index]),
            len(topics[index].intersection(practice_targets.get(question_key(pending[index]), ()))),
        ))
        if not topics[best]:
            break
        needed -= topics[best]
        selected.append(pending.pop(best))
    covered = {skill for item in selected for skill in practice_targets.get(question_key(item), ())}
    # Admit at most one extra representative per uncovered practice priority.
    for item in pending.copy():
        targets = set(practice_targets.get(question_key(item), ()))
        if targets - covered:
            covered.update(targets)
            selected.append(item)
            pending.remove(item)
    return [*selected, *pending]
