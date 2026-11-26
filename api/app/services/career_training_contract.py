"""Freeze training requirements before a worker can claim the task."""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.services.career_question_catalog import exact_skill, question_key, required_skills, skills_in

Skill = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
QuestionId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,64}$")]
OrderMode = Literal["FIRST_OCCURRENCE_ORDER", "STRICT_PHASE_ORDER"]
LearningVersion = Literal["objective-practice-v1", "objective-practice-v2", "objective-practice-v2-utility"]


class QuestionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: QuestionId
    version: int = Field(gt=0)


class TrainingRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)] | None = None
    requiredSkills: list[Skill] | None = Field(default=None, max_length=8)
    preferredSkills: list[Skill] = Field(default_factory=list, max_length=8)
    prioritySkills: list[Skill] | None = Field(default=None, max_length=8)
    orderMode: OrderMode | None = None
    deadline: date | None = None
    questionCount: int | None = Field(default=None, ge=1, le=8, strict=True)
    requiredQuestions: list[QuestionRef] = Field(default_factory=list, max_length=8)
    excludeCompleted: bool | None = None
    timeZone: str | None = Field(default=None, max_length=80)


class TrainingBudget(BaseModel):
    maxSeconds: int = 300
    maxModelCalls: int = 3
    maxTransientRetries: int = 2
    maxRepairRounds: int = 2
    maxInputTokens: int = 12000
    maxExternalToolCalls: Literal[0] = 0


class TrainingContract(BaseModel):
    id: str
    version: Literal[1, 2] = 1
    taskType: Literal["TRAINING"] = "TRAINING"
    harnessVersion: Literal["training-v2"] = "training-v2"
    verifierVersion: Literal["training-verifier-v1", "training-verifier-v2"] = "training-verifier-v1"
    repairVersion: Literal["local-v1", "regenerate-v1"]
    learningVersion: LearningVersion
    userId: str
    jobId: str
    conversationId: str | None
    createdAt: datetime
    startDate: date
    timeZone: str
    objective: str
    requiredSkills: list[str]
    jobSkills: list[str]
    preferredSkills: list[str] = Field(default_factory=list)
    prioritySkills: list[str]
    orderMode: OrderMode = "FIRST_OCCURRENCE_ORDER"
    deadline: date | None
    questionCount: int | None
    requiredQuestions: list[QuestionRef]
    excludeCompleted: bool
    preferences: list[str]
    sources: list[dict]
    budget: TrainingBudget = Field(default_factory=TrainingBudget)

    def prompt(self) -> dict:
        fields = {
            "objective", "startDate", "deadline", "requiredSkills", "jobSkills", "prioritySkills",
            "questionCount", "requiredQuestions", "excludeCompleted", "preferences",
        }
        if self.version == 2:
            fields.update({"orderMode", "preferredSkills"})
        return self.model_dump(mode="json", include=fields)


class TrainingContractError(ValueError):
    def __init__(self, message: str, code: str = "TASK_CONTRACT_UNSATISFIABLE"):
        super().__init__(message)
        self.code = code


_DATE = r"(?:\d{4}-\d{2}-\d{2}|(?:下|本|这)?周[一二三四五六日天]|今天|明天|后天)"
_COUNT = re.compile(r"(?:先)?(?:安排|选取|选|出题共|共|改成|改为)\s*([0-9一二两三四五六七八九十]+)\s*道(?:练习)?题目?")
_DEADLINE = re.compile(rf"(?:截止(?:日期|时间)?(?:改成|改为|设为|[到为是：:])?\s*({_DATE})|"
                       rf"({_DATE})\s*(?:之前|以前|前|截止)(?:完成(?:复习|训练|.+?(?:的)?复习))?)")
_PRIORITY = re.compile(r"(?:优先复习|先复习|优先学习|先学习)\s*(.+)")
_REQUIRED = re.compile(r"(?:必须覆盖|覆盖|复习)\s*(.+)")
_EXCLUDE = re.compile(r"(?:不要|别|不再)重复(?:已经|已)?(?:完成|做过)(?:的)?题目?")
_INCLUDE = re.compile(r"(?:允许|可以)重复(?:已经|已)?(?:完成|做过)(?:的)?题目?")
_CHINESE_NUMBERS = dict(zip("一二三四五六七八九十", range(1, 11)), 两=2)
_NEGATION = re.compile(r"不要|请勿|不需要|无需|不必|不用|不是|别")
_CONDITION = re.compile(r"如果|除非|倘若|要是|有时间(?:就|再)|假如")
_STRICT = re.compile(r"(?:先)?(?:完成|学完)\s*(.+?)(?:\s*(?:的复习|阶段))?\s*(?:之后|后)?\s*"
                     r"[，,]?\s*再(?:开始|复习|学习)\s*(.+)")
_ENDS = re.compile(r"[。；;！!\n]")
_INTRO = re.compile(r"^(?:(?:请|帮我|并且|同时|务必)\s*)+")


@dataclass(frozen=True)
class ConstraintReading:
    field: str
    status: Literal["CONFIRMED", "NEGATED", "AMBIGUOUS", "CONFLICTING", "UNSUPPORTED"]
    raw: str
    value: object = None
    clarify: bool = False


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
    if not re.fullmatch(_DATE, value):
        raise TrainingContractError("请用 YYYY-MM-DD 明确备考截止日期。", "CONTRACT_CONFIRMATION_REQUIRED")
    if value in {"今天", "明天", "后天"}:
        return today + timedelta(days=["今天", "明天", "后天"].index(value))
    weekday = "一二三四五六日".index(value[-1].replace("天", "日"))
    delta = weekday - today.weekday()
    if value.startswith("下") or (value.startswith("周") and delta < 0):
        delta += 7
    return today + timedelta(days=delta)


def fixed_deadline(value: str, instant: datetime, time_zone: str | None) -> dict:
    if not re.fullmatch(_DATE, value):
        raise TrainingContractError("请确认一个固定的截止日期，格式为 YYYY-MM-DD。", "CONTRACT_CONFIRMATION_REQUIRED")
    anchor = instant.astimezone(_zone(time_zone))
    return {"rawValue": value, "normalizedValue": _date(value, anchor.date(), time_zone).isoformat(),
            "timeZone": time_zone, "resolvedAt": anchor.isoformat()}


def _known_skills(value: str) -> list[str]:
    value = re.sub(r"^(?:先(?:复习|学习)?\s*)", "", value.strip())
    parts = re.split(r"(?:和|与|、|以及|\s*→\s*|\s*->\s*|[，,]?\s*(?:再|然后)(?:复习|学习)?)", value)
    matched = [exact_skill(part) for part in parts]
    return list(dict.fromkeys(matched)) if all(matched) else []


def _priority_value(raw: str) -> tuple[list[str], OrderMode]:
    if strict := _STRICT.fullmatch(raw):
        first, last = map(_known_skills, strict.groups())
        if first and last:
            return [*first, *last], "STRICT_PHASE_ORDER"
    return _known_skills(raw), "FIRST_OCCURRENCE_ORDER"


def read_requirements(text: str) -> list[ConstraintReading]:
    readings = []
    for sentence in _ENDS.split(text):
        sentence_start = len(readings)
        conditional = False
        # Keep structured phrases together when a comma expresses succession.
        sentence = re.sub(r"([，,])\s*(?=再(?:开始|学习|复习))", "", sentence)
        for raw in filter(None, (part.strip() for part in re.split(r"[，,]", sentence))):
            clause = _INTRO.sub("", raw)
            conditional = conditional or bool(_CONDITION.search(clause))
            field = value = None
            status, clarify = "CONFIRMED", False
            completed = _EXCLUDE.fullmatch(clause) or _INCLUDE.fullmatch(clause)
            strict = _STRICT.fullmatch(clause)
            priority = _PRIORITY.fullmatch(clause)
            deadline = _DEADLINE.fullmatch(clause)
            count = _COUNT.fullmatch(clause)
            if completed:
                field, value = "excludeCompleted", bool(_EXCLUDE.fullmatch(clause))
            elif count:
                field = "questionCount"
                token = count[1]
                value = int(token) if token.isascii() else _CHINESE_NUMBERS.get(token)
            elif strict or priority:
                field = "prioritySkills"
                value = _priority_value(clause if strict else priority[1])
                if not value[0]:
                    value = None
            elif deadline:
                field, value = "deadline", deadline[1] or deadline[2]
                if target := re.fullmatch(rf"{_DATE}(?:之前|以前|前)完成\s*(.+?)(?:的)?复习", clause):
                    skills = _known_skills(target[1])
                    if skills and not conditional and not _NEGATION.search(clause):
                        readings.append(ConstraintReading("requiredSkills", "CONFIRMED", raw, skills))
            elif mandatory := _REQUIRED.fullmatch(clause) or re.fullmatch(r"完成\s*(.+?)(?:的)?复习", clause):
                field, value = "requiredSkills", _known_skills(mandatory[1]) or None
            elif re.search(r"[0-9一二两三四五六七八九十]+\s*道(?:练习)?题", clause):
                field = "questionCount"
                clarify = bool(re.search(r"最多|至少|不要?超过|不少于|到|至|以内|以上|以下", clause))
            elif _PRIORITY.search(clause) or "复习顺序" in clause:
                field = "prioritySkills"
            elif re.fullmatch(_DATE, clause) and any(item.field == "deadline" for item in readings[sentence_start:]):
                field, clarify = "deadline", True
            elif (_DEADLINE.search(clause) or re.search(r"截止(?:日期|时间)?|(?:周|月|日|号|天)(?:前|之前|内)", clause)
                  or re.search(rf"{_DATE}.*完成", clause)) and not re.search(r"^(?:按照|根据)(?:新的?|当前的?)?截止", clause):
                field, clarify = "deadline", True
            elif _REQUIRED.search(clause):
                field = "requiredSkills"
            if field is None:
                continue
            if not completed and _NEGATION.search(clause) and not (field == "questionCount" and "不要超过" in clause):
                status, value, clarify = "NEGATED", None, False
                negated_count = _COUNT.fullmatch(_NEGATION.sub("", clause, count=1)) if field == "questionCount" else None
                if negated_count:
                    token = negated_count[1]
                    value = int(token) if token.isascii() else _CHINESE_NUMBERS.get(token)
            elif conditional or raw.endswith(("？", "?")) or re.search(r"或者|还是|可能|大概|左右", clause):
                status, value = "AMBIGUOUS", None
                clarify = field == "deadline"
            elif value is None:
                status = "UNSUPPORTED"
            readings.append(ConstraintReading(field, status, raw, value, clarify))
    return readings


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
    repair: Literal["local-v1", "regenerate-v1"], learning: LearningVersion,
) -> TrainingContract:
    if len(request_text) > 800:
        raise TrainingContractError("请将本轮备考要求缩短到 800 字以内。", "CONTRACT_CONFIRMATION_REQUIRED")
    zone = _zone(requirements.timeZone)
    today = created_at.astimezone(zone).date()
    properties = ("deadline", "questionCount", "excludeCompleted", "prioritySkills", "requiredSkills")
    active = {item["field"]: item for item in pinned if item.get("value")}
    sources = [{"type": "job", "id": job_id}, {"type": "request"}]
    preferences = [request_text] if request_text else []
    readings = read_requirements(request_text)
    resolved = {}
    for field in properties:
        batch = [item for item in readings if item.field == field]
        explicit = getattr(requirements, field)
        known = [item for item in batch if item.status == "CONFIRMED"]
        if field == "questionCount" and any(re.match(r"^(?:请)?改(?:为|成)", item.raw) for item in known):
            known = known[-1:]
        conflict = (field != "requiredSkills" and len({repr(item.value) for item in known}) > 1) or any(
            item.status == "NEGATED" and item.value is not None and any(item.value == match.value for match in known)
            for item in batch
        )
        for item in batch:
            sources.append({"type": "natural", "field": field, "raw": item.raw,
                            "status": "CONFLICTING" if conflict and item in known else item.status,
                            "used": explicit is None and not conflict and item in known})
        if explicit is not None:
            sources.append({"type": "structured", "field": field, "used": True})
            resolved[field] = explicit
        elif conflict or any(item.clarify for item in batch):
            message = ("请确认一个固定的截止日期，格式为 YYYY-MM-DD。" if field == "deadline" else
                       "请确认本轮要求。题量请使用 1 至 8 的精确数量。" if field == "questionCount" else
                       "本轮有互相冲突的训练要求，请确认后重新提交。")
            raise TrainingContractError(message, "CONTRACT_CONFIRMATION_REQUIRED")
        elif known:
            resolved[field] = [skill for item in known for skill in item.value] if field == "requiredSkills" else known[-1].value

    deadline = resolved.get("deadline")
    if isinstance(deadline, str):
        deadline = _date(deadline, today, requirements.timeZone)
    deny_pinned_deadline = any(item.field == "deadline" and item.status == "NEGATED" for item in readings)
    if deadline is None and not deny_pinned_deadline and (pinned_deadline := active.get("截止时间")):
        fixed = (pinned_deadline.get("normalizedValue") or pinned_deadline["value"]).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fixed) or not pinned_deadline.get("confirmed"):
            raise TrainingContractError("历史截止日期需要重新确认，请在上下文约束中保存固定日期。",
                                        "CONTRACT_CONFIRMATION_REQUIRED")
        if pinned_zone := pinned_deadline.get("timeZone"):
            zone = _zone(pinned_zone)
            today = created_at.astimezone(zone).date()
        deadline = _date(fixed, today, requirements.timeZone)
    if deadline is not None and deadline < today:
        raise TrainingContractError("备考截止日期早于任务创建日期。")
    count = resolved.get("questionCount")
    if count is not None and not 1 <= count <= 8:
        raise TrainingContractError("备考计划需要安排 1 至 8 道题。")
    priority = resolved.get("prioritySkills")
    mode = "FIRST_OCCURRENCE_ORDER"
    if isinstance(priority, tuple):
        priority, mode = priority
    if priority is None:
        pinned_order = active.get("复习顺序", {})
        if pinned_order.get("confirmed") and not any(item.field == "prioritySkills" for item in readings):
            priority, mode = _priority_value(pinned_order["value"])
            if not priority:
                preferences.append("复习顺序 " + pinned_order["value"])
        else:
            priority = []
    priority = _canonical(priority)
    mandatory = resolved.get("requiredSkills", [])
    job_skills = sorted(required_skills(job))
    refs = list(requirements.requiredQuestions)
    if preferred and not any(ref.id == preferred for ref in refs):
        refs.append(QuestionRef(id=preferred, version=1))
    if preferred and any(ref.id == preferred and ref.version != 1 for ref in refs):
        raise TrainingContractError("指定模拟题与明确要求的题目版本冲突。")
    if len({ref.id for ref in refs}) != len(refs) or len(refs) > (count or 8):
        raise TrainingContractError("指定题目重复、版本冲突或超过计划题量。")
    sources.extend({"type": "pinned", **{key: item.get(key) for key in (
        "field", "source_message_id", "version", "rawValue", "normalizedValue", "timeZone", "resolvedAt",
    )}}
                   for item in active.values())
    return TrainingContract(
        version=2, verifierVersion="training-verifier-v2", budget=TrainingBudget(maxModelCalls=5),
        id=str(uuid4()), userId=user, jobId=job_id, conversationId=conversation, createdAt=created_at,
        startDate=today, timeZone=zone.key, objective=requirements.objective or "制定当前岗位的备考计划",
        requiredSkills=sorted(set(job_skills) | set(_canonical(mandatory)) | set(priority)), jobSkills=job_skills,
        preferredSkills=_canonical(requirements.preferredSkills),
        prioritySkills=priority, orderMode=requirements.orderMode or mode, deadline=deadline, questionCount=count,
        requiredQuestions=refs, excludeCompleted=resolved.get("excludeCompleted", False), preferences=preferences, sources=sources,
        repairVersion=repair, learningVersion=learning,
    )


def _legacy_feasible_questions(contract: TrainingContract, catalog: list[dict]) -> list[dict]:
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


MAX_FEASIBILITY_STEPS = 200_000


def _phase_mask(topic: str, priorities: list[str]) -> int:
    matched = topic_skills(topic, set(priorities))
    return sum(1 << position for position, skill in enumerate(priorities) if skill in matched)


def _phase(mask: int, total: int) -> int:
    return (mask & -mask).bit_length() - 1 if mask else total


def _advance_priority(seen: int, mask: int, goal: int) -> int | None:
    combined = seen | mask
    if (mask or seen == goal) and combined & (combined + 1) == 0:
        return combined
    return None


def priority_order_matches(contract: TrainingContract, topics: list[str]) -> bool:
    priorities = contract.prioritySkills
    if not priorities:
        return True
    masks = [_phase_mask(topic, priorities) for topic in topics]
    if contract.orderMode == "STRICT_PHASE_ORDER":
        phases = [_phase(mask, len(priorities)) for mask in masks]
        return phases == sorted(phases) and set(range(len(priorities))) <= set(phases)
    seen, goal = 0, (1 << len(priorities)) - 1
    for mask in masks:
        seen = _advance_priority(seen, mask, goal)
        if seen is None:
            return False
    return seen == goal


def _ordered_witness(contract: TrainingContract, picked: tuple[int, ...], masks: list[int]) -> tuple[int, ...] | None:
    size = len(contract.prioritySkills)
    if not size:
        return tuple(sorted(picked))
    if contract.orderMode == "STRICT_PHASE_ORDER":
        return tuple(sorted(picked, key=lambda index: _phase(masks[index], size)))
    goal = (1 << size) - 1
    failed = set()

    def visit(pending: tuple[int, ...], seen: int):
        if not pending:
            return () if seen == goal else None
        if pending in failed:
            return None
        for index in pending:
            advanced = _advance_priority(seen, masks[index], goal)
            if advanced is not None and (rest := visit(tuple(item for item in pending if item != index), advanced)) is not None:
                return (index, *rest)
        failed.add(pending)
        return None

    return visit(picked, 0)


def feasible_questions(
    contract: TrainingContract, catalog: list[dict], *, utility: dict[tuple[str, int], tuple[str, float]] | None = None,
    witness: list[dict] | None = None,
) -> list[dict]:
    """Find a legal scheduled selection, keeping its exact references in the snapshot."""
    if contract.version == 1:
        return _legacy_feasible_questions(contract, catalog)
    if contract.deadline and contract.deadline < contract.startDate:
        raise TrainingContractError("备考截止日期早于任务创建日期。")
    eligible = list({question_key(item): item for item in catalog
                     if not (contract.excludeCompleted and item.get("practiceCompleted"))}.values())
    required = {(ref.id, ref.version) for ref in contract.requiredQuestions}
    mandatory = tuple(index for index, item in enumerate(eligible) if question_key(item) in required)
    limit = contract.questionCount or 8
    if len(mandatory) != len(required) or len({item["id"] for item in eligible}) < (contract.questionCount or 1):
        raise TrainingContractError("题库无法提供指定题目、版本或所需题量，请调整要求。")
    skills = set(contract.requiredSkills)
    phase_masks = [_phase_mask(item.get("topic", ""), contract.prioritySkills) for item in eligible]
    features = [set(("skill", name) for name in topic_skills(item.get("topic", ""), skills)) for item in eligible]
    needed = {("skill", name) for name in skills}
    if contract.orderMode == "STRICT_PHASE_ORDER":
        total = len(contract.prioritySkills)
        needed.update(("phase", phase) for phase in range(total))
        for index, mask in enumerate(phase_masks):
            features[index].add(("phase", _phase(mask, total)))
    missing = needed - set().union(*features)
    if missing:
        names = [name for kind, name in missing if kind == "skill"]
        message = "题库缺少必备技能的题目：" + "、".join(sorted(names)) if names else "题库缺少可独立安排的复习阶段题目。"
        raise TrainingContractError(message)

    utility = utility or {}
    soft_slots = min(5, len({item["id"] for item in eligible})) if utility and contract.questionCount is None else 1
    ranks = [utility.get(question_key(item), (None, 0.0)) for item in eligible]
    visited: set[tuple[int, ...]] = set()
    steps = 0

    def visit(picked: tuple[int, ...], missing_features: set):
        nonlocal steps
        steps += max(1, len(eligible) * max(1, len(missing_features)))
        if steps > MAX_FEASIBILITY_STEPS:
            raise TrainingContractError("题库组合过多，暂时无法确定可行性。请缩小技能或题库范围。",
                                        "TASK_CONTRACT_FEASIBILITY_UNDETERMINED")
        selected_key = tuple(sorted(picked))
        if selected_key in visited:
            return None
        visited.add(selected_key)
        sized = len(picked) == limit if contract.questionCount else len(picked) >= soft_slots
        if sized and not missing_features:
            if (schedule := _ordered_witness(contract, picked, phase_masks)) is not None:
                return schedule
        if len(picked) >= limit:
            return None
        used_ids = {eligible[index]["id"] for index in picked}
        available = [i for i, item in enumerate(eligible) if item["id"] not in used_ids]
        if missing_features:
            # Try all questions covering the scarcest unmet requirement before allocating free slots.
            alternatives = min(([i for i in available if feature in features[i]] for feature in sorted(missing_features)),
                               key=len)
        else:
            alternatives = available
        exposures = [ranks[i][0] for i in picked if ranks[i][0]]
        if utility:
            alternatives = sorted(alternatives, key=lambda i: (-ranks[i][1] / (1 + 0.65 * exposures.count(ranks[i][0])), i))
        else:
            alternatives = sorted(alternatives, key=lambda i: (-len(features[i] & missing_features), i))
        for candidate in alternatives:
            result = visit((*picked, candidate), missing_features - features[candidate])
            if result is not None:
                return result
        return None

    selection = visit(mandatory, needed - set().union(*(features[index] for index in mandatory)))
    if selection is None:
        raise TrainingContractError("现有题库和题量无法同时满足必备技能、指定题目与复习顺序。")
    chosen = set(selection)
    if witness is not None:
        witness.extend({"id": eligible[index]["id"], "version": eligible[index]["version"]} for index in selection)
    return [*(eligible[index] for index in selection), *(item for index, item in enumerate(eligible) if index not in chosen)]
