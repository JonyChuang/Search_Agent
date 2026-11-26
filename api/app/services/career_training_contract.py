"""Freeze training requirements before a worker can claim the task."""

import re
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.services.career_question_catalog import exact_skill, question_key, required_skills, skills_in

Skill = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
QuestionId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,64}$")]


class QuestionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: QuestionId
    version: int = Field(gt=0)


class TrainingRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)] | None = None
    requiredSkills: list[Skill] | None = Field(default=None, max_length=8)
    prioritySkills: list[Skill] | None = Field(default=None, max_length=8)
    deadline: date | None = None
    questionCount: int | None = Field(default=None, ge=1, le=8, strict=True)
    requiredQuestions: list[QuestionRef] = Field(default_factory=list, max_length=8)
    excludeCompleted: bool | None = None
    timeZone: str | None = Field(default=None, max_length=80)


class TrainingBudget(BaseModel):
    maxSeconds: int = 300
    maxModelCalls: int = 3
    maxRepairRounds: int = 2
    maxInputTokens: int = 12000
    maxExternalToolCalls: Literal[0] = 0


class TrainingContract(BaseModel):
    id: str
    version: Literal[1] = 1
    taskType: Literal["TRAINING"] = "TRAINING"
    harnessVersion: Literal["training-v2"] = "training-v2"
    verifierVersion: Literal["training-verifier-v1"] = "training-verifier-v1"
    repairVersion: Literal["local-v1", "regenerate-v1"]
    learningVersion: Literal["objective-practice-v1", "objective-practice-v2"]
    userId: str
    jobId: str
    conversationId: str | None
    createdAt: datetime
    startDate: date
    timeZone: str
    objective: str
    requiredSkills: list[str]
    jobSkills: list[str]
    prioritySkills: list[str]
    deadline: date | None
    questionCount: int | None
    requiredQuestions: list[QuestionRef]
    excludeCompleted: bool
    preferences: list[str]
    sources: list[dict]
    budget: TrainingBudget = Field(default_factory=TrainingBudget)

    def prompt(self) -> dict:
        return self.model_dump(mode="json", include={
            "objective", "startDate", "deadline", "requiredSkills", "jobSkills", "prioritySkills",
            "questionCount", "requiredQuestions", "excludeCompleted", "preferences",
        })


class TrainingContractError(ValueError):
    def __init__(self, message: str, code: str = "TASK_CONTRACT_UNSATISFIABLE"):
        super().__init__(message)
        self.code = code


_DATE = r"(?:\d{4}-\d{2}-\d{2}|(?:下|本|这)?周[一二三四五六日天]|今天|明天|后天)"
_COUNT = re.compile(r"(?:安排|选取|选|出题共|共)\s*([0-9一二两三四五六七八九十]+)\s*道(?:练习)?题目?$")
_DEADLINE = re.compile(rf"(?:截止(?:日期|时间)?[到为：:]?\s*({_DATE})|({_DATE})\s*(?:之前|以前|前|截止))")
_PRIORITY = re.compile(r"(?:优先复习|先复习|优先学习)\s*([^，,。；;！!]+)")
_REQUIRED = re.compile(r"(?:必须覆盖|覆盖|复习)\s*(.+)")
_EXCLUDE = re.compile(r"(?:不要|别|不再)重复(?:已经|已)?(?:完成|做过)(?:的)?题目?")
_INCLUDE = re.compile(r"(?:允许|可以)重复(?:已经|已)?(?:完成|做过)(?:的)?题目?")
_CHINESE_NUMBERS = dict(zip("一二三四五六七八九十", range(1, 11)), 两=2)


def _zone(name: str | None):
    try:
        return ZoneInfo(name or "UTC")
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise TrainingContractError("请提供有效的 IANA 时区。", "CONTRACT_CONFIRMATION_REQUIRED") from error


def _date(value: str, today: date, time_zone: str | None) -> date:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise TrainingContractError("请确认截止日期。", "CONTRACT_CONFIRMATION_REQUIRED") from error
    if not time_zone:
        raise TrainingContractError("相对截止日期需要时区，请提供时区或使用 YYYY-MM-DD。",
                                    "CONTRACT_CONFIRMATION_REQUIRED")
    if value in {"今天", "明天", "后天"}:
        return today + timedelta(days=["今天", "明天", "后天"].index(value))
    weekday = "一二三四五六日".index(value[-1].replace("天", "日"))
    delta = weekday - today.weekday()
    if value.startswith("下") or (value.startswith("周") and delta < 0):
        delta += 7
    return today + timedelta(days=delta)


def _known_skills(value: str) -> list[str]:
    value = re.sub(r"^(?:先(?:复习|学习)?\s*)", "", value.strip())
    parts = re.split(r"(?:和|与|、|以及|\s*→\s*|\s*->\s*|再(?:复习)?|然后(?:复习)?)", value)
    matched = [exact_skill(part) for part in parts]
    return list(dict.fromkeys(matched)) if all(matched) else []


def _canonical(values: list[str]) -> list[str]:
    return list(dict.fromkeys(exact_skill(value) or value for value in values))


def topic_skills(topic: str, skills: set[str]) -> set[str]:
    known = skills_in(topic)
    return {skill for skill in skills if skill in known or re.search(
        rf"(?<![a-z0-9]){re.escape(skill)}(?![a-z0-9])", topic, re.IGNORECASE,
    )}


def build_contract(
    *, user: str, job_id: str, conversation: str | None, job: dict, preferred: str | None,
    requirements: TrainingRequirements, request_text: str, pinned: list[dict], created_at: datetime,
    repair: Literal["local-v1", "regenerate-v1"], learning: Literal["objective-practice-v1", "objective-practice-v2"],
) -> TrainingContract:
    if len(request_text) > 800:
        raise TrainingContractError("请将本轮备考要求缩短到 800 字以内。", "CONTRACT_CONFIRMATION_REQUIRED")
    zone = _zone(requirements.timeZone)
    today = created_at.astimezone(zone).date()
    deadline, count, exclude = requirements.deadline, requirements.questionCount, requirements.excludeCompleted
    priority, mandatory = requirements.prioritySkills, requirements.requiredSkills
    active = {item["field"]: item for item in pinned if item.get("confirmed") and item.get("value")}
    clauses = [clause.strip() for clause in re.split(r"[，,。；;！!\n]", request_text) if clause.strip()]
    preferences = [request_text] if request_text else []
    if deadline is None:
        if any(("截止" in clause or _DEADLINE.search(clause)) and re.search(r"或者|或|可能|大概|左右", clause)
               for clause in clauses):
            raise TrainingContractError("请确认一个明确的备考截止日期。", "CONTRACT_CONFIRMATION_REQUIRED")
        dates = {value for match in _DEADLINE.finditer(request_text) for value in match.groups() if value}
        if len(dates) > 1:
            raise TrainingContractError("本轮有多个截止日期，请明确一个日期。", "CONTRACT_CONFIRMATION_REQUIRED")
        pinned_deadline = active.get("截止时间", {}).get("value", "").strip()
        unresolved = not dates and (
            pinned_deadline or re.search(r"截止(?:日期|时间)?|(?:周|月|日|号|天)(?:前|之前|内)", request_text)
        )
        value = next(iter(dates), pinned_deadline)
        if value and re.fullmatch(_DATE, value):
            deadline = _date(value, today, requirements.timeZone)
        elif unresolved:
            raise TrainingContractError("请用 YYYY-MM-DD 明确备考截止日期。", "CONTRACT_CONFIRMATION_REQUIRED")
    if deadline is not None and deadline < today:
        raise TrainingContractError("备考截止日期早于任务创建日期。")
    if count is None:
        counts = {int(value) if value.isascii() else _CHINESE_NUMBERS.get(value, 0)
                  for clause in clauses for value in _COUNT.findall(clause)}
        if len(counts) > 1:
            raise TrainingContractError("本轮有多个题目数量，请明确一个数量。", "CONTRACT_CONFIRMATION_REQUIRED")
        count = next(iter(counts), None)
        if count is not None and not 1 <= count <= 8:
            raise TrainingContractError("备考计划需要安排 1 至 8 道题。")
    if exclude is None:
        excludes, includes = bool(_EXCLUDE.search(request_text)), bool(_INCLUDE.search(request_text))
        if excludes and includes:
            raise TrainingContractError("请确认是否排除已完成的题目。", "CONTRACT_CONFIRMATION_REQUIRED")
        exclude = excludes
    if priority is None:
        ordered = [skill for clause in clauses for match in [_PRIORITY.fullmatch(clause)]
                   if match for skill in _known_skills(match[1])]
        has_override = any(_PRIORITY.fullmatch(clause) for clause in clauses)
        pinned_order = active.get("复习顺序", {}).get("value", "")
        priority = ordered if has_override else _known_skills(pinned_order)
        if not has_override and pinned_order and not priority:
            preferences.append("复习顺序 " + pinned_order)
    if mandatory is None:
        mandatory = [skill for clause in clauses if not _PRIORITY.fullmatch(clause)
                     for match in [_REQUIRED.search(clause)] if match
                     for skill in _known_skills(re.sub(rf"^{_DATE}(?:之前|以前|前)完成|(?:的)?复习$", "", match[1]))]
        for clause in clauses:
            if match := re.fullmatch(rf"(?:{_DATE}(?:之前|以前|前))?完成\s*(.+?)(?:的)?复习", clause):
                mandatory.extend(_known_skills(match[1]))
    priority = _canonical(priority)
    job_skills = sorted(required_skills(job))
    refs = list(requirements.requiredQuestions)
    if preferred and not any(ref.id == preferred for ref in refs):
        refs.append(QuestionRef(id=preferred, version=1))
    if preferred and any(ref.id == preferred and ref.version != 1 for ref in refs):
        raise TrainingContractError("指定模拟题与明确要求的题目版本冲突。")
    if len({ref.id for ref in refs}) != len(refs) or len(refs) > (count or 8):
        raise TrainingContractError("指定题目重复、版本冲突或超过计划题量。")
    sources = [{"type": "job", "id": job_id}, {"type": "request"}]
    sources.extend({"type": "pinned", **{key: item.get(key) for key in ("field", "source_message_id", "version")}}
                   for item in active.values())
    return TrainingContract(
        id=str(uuid4()), userId=user, jobId=job_id, conversationId=conversation, createdAt=created_at,
        startDate=today, timeZone=zone.key, objective=requirements.objective or "制定当前岗位的备考计划",
        requiredSkills=sorted(set(job_skills) | set(_canonical(mandatory)) | set(priority)), jobSkills=job_skills,
        prioritySkills=priority, deadline=deadline, questionCount=count, requiredQuestions=refs,
        excludeCompleted=exclude, preferences=preferences, sources=sources,
        repairVersion=repair, learningVersion=learning,
    )


def feasible_questions(contract: TrainingContract, catalog: list[dict]) -> list[dict]:
    """Keep a feasible set of question references at the head of the frozen catalog."""
    eligible = [item for item in catalog if not (contract.excludeCompleted and item.get("practiceCompleted"))]
    refs = {(ref.id, ref.version) for ref in contract.requiredQuestions}
    skills = set(contract.requiredSkills)
    selected = [item for item in eligible if question_key(item) in refs]
    remaining = [item for item in eligible if item["id"] not in {q["id"] for q in selected}]
    limit = contract.questionCount or 8
    if len(selected) != len(refs) or len({item["id"] for item in eligible}) < (contract.questionCount or 1):
        raise TrainingContractError("题库无法提供指定题目、版本或所需题量，请调整要求。")
    needed = frozenset(skills - set().union(*(topic_skills(q.get("topic", ""), skills) for q in selected)))
    missing = needed - set().union(*(topic_skills(q.get("topic", ""), needed) for q in remaining))
    if missing:
        raise TrainingContractError("题库缺少必备技能的题目：" + "、".join(sorted(missing)))
    # Cover the requirements within the question count, using each ID at most once.
    groups: dict[str, list[tuple[int, frozenset[str]]]] = {}
    seen_masks = set()
    for index, item in enumerate(remaining):
        covered = frozenset(topic_skills(item.get("topic", ""), needed))
        if covered and (item["id"], covered) not in seen_masks:
            groups.setdefault(item["id"], []).append((index, covered))
            seen_masks.add((item["id"], covered))
    slots = limit - len(selected)
    max_cover = max((len(mask) for _, mask in seen_masks), default=0)
    if len(needed) > slots * max_cover:
        raise TrainingContractError("所需题量不足以覆盖指定题目和全部必备技能。")
    choices: dict[frozenset[str], tuple[int, ...]] = {frozenset(): ()}
    for group in groups.values():
        for covered, picked in list(choices.items()):
            if len(picked) >= slots:
                continue
            for index, topics in group:
                union = covered | topics
                candidate = (*picked, index)
                if union not in choices or (len(candidate), candidate) < (len(choices[union]), choices[union]):
                    choices[union] = candidate
        if needed in choices and len(choices[needed]) == 1:
            break
    if needed not in choices:
        raise TrainingContractError("所需题量不足以覆盖指定题目和全部必备技能。")
    selected.extend(remaining[index] for index in choices[needed])
    ids = {item["id"] for item in selected}
    if contract.questionCount:
        for item in remaining:
            if len(selected) >= contract.questionCount:
                break
            if item["id"] not in ids:
                selected.append(item)
                ids.add(item["id"])
    keys = {question_key(item) for item in selected}
    return [*selected, *(item for item in eligible if question_key(item) not in keys)]
