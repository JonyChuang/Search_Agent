"""Validate the structured plan against frozen business evidence."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.services.career_question_catalog import question_key
from app.services.career_training_contract import QuestionId, QuestionRef, TrainingContract, priority_order_matches, topic_skills


class StudyStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    skill: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None
    scheduledDate: date | None
    questionRefs: list[QuestionId] = Field(min_length=1, max_length=8)


class TrainingPlanPatch(BaseModel):
    """Replace only the linked question selection and study schedule."""

    model_config = ConfigDict(extra="forbid")

    questions: list[QuestionRef] = Field(min_length=1, max_length=8)
    schedule: list[StudyStep] = Field(min_length=1, max_length=8)


class TrainingPlan(TrainingPlanPatch):
    """Submit the training plan, including question references and dated steps."""

    analysis: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    experienceIds: list[Annotated[str, StringConstraints(pattern=r"^[0-9a-f-]{36}$")]] = Field(max_length=10)

    def draft(self) -> dict:
        result = self.model_dump(mode="json")
        result["steps"] = [f"{step.scheduledDate.isoformat()} · {step.title}" if step.scheduledDate else step.title
                           for step in self.schedule]
        return result


class ValidationIssue(BaseModel):
    code: str
    field: str
    message: str
    repairable: bool = True
    context: dict = Field(default_factory=dict)


class VerificationReport(BaseModel):
    validator: str
    errors: list[ValidationIssue] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def add(self, code: str, field: str, message: str, *, context: dict | None = None) -> None:
        self.errors.append(ValidationIssue(code=code, field=field, message=message, context=context or {}))

    def public(self) -> dict:
        return {"validator": self.validator, "passed": self.passed,
                "errors": [issue.model_dump() for issue in self.errors[:24]]}


def schema_report(error: ValidationError | None) -> VerificationReport:
    report = VerificationReport(validator="schema")
    if error is None:
        report.add("INVALID_SCHEMA", "toolCall", "必须且只能调用一次指定的工具。")
    else:
        valid_fields = {"schedule", "questions", "analysis", "experienceIds", "scheduledDate", "questionRefs",
                        "version", "id", "title", "skill"}
        for item in error.errors(include_input=False, include_context=False, include_url=False)[:24]:
            field = ".".join(str(part) for part in item["loc"] if isinstance(part, int) or part in valid_fields)
            report.add("INVALID_SCHEMA", field or "toolArguments", "字段缺失、类型错误或超出允许范围。")
    return report


def verify_plan(
    plan: TrainingPlan, contract: TrainingContract, catalog: list[dict], confirmed_experiences: set[str],
) -> VerificationReport:
    report = VerificationReport(validator="business")
    allowed = {question_key(item): item for item in catalog}
    catalog_ids = {key[0] for key in allowed}
    chosen: dict[str, set[str]] = {}
    topics_by_id = {}
    refs = set()
    ids = set()
    required = set(contract.requiredSkills)
    for index, ref in enumerate(plan.questions):
        key, field = (ref.id, ref.version), f"questions.{index}"
        if ref.id in ids:
            report.add("DUPLICATE_QUESTION", field, "同一题目只能安排一次。")
        ids.add(ref.id)
        item = allowed.get(key)
        if item is None:
            if ref.id in catalog_ids:
                report.add("QUESTION_VERSION_MISMATCH", field + ".version", "使用已冻结题库中的版本。",
                           context={"versions": sorted(version for identifier, version in allowed if identifier == ref.id)})
            else:
                report.add("QUESTION_NOT_FOUND", field + ".id", "使用已冻结题库中的题目。")
            continue
        if contract.excludeCompleted and item.get("practiceCompleted"):
            report.add("QUESTION_ALREADY_COMPLETED", field, "该题在提交任务时已完成。")
        chosen[ref.id] = topic_skills(item.get("topic", ""), required)
        topics_by_id[ref.id] = item.get("topic", "")
        refs.add(key)
    if contract.questionCount is not None and len(plan.questions) != contract.questionCount:
        report.add("QUESTION_COUNT_MISMATCH", "questions", f"计划须包含 {contract.questionCount} 道题。",
                   context={"expected": contract.questionCount, "actual": len(plan.questions)})
    missing_refs = [ref.model_dump() for ref in contract.requiredQuestions if (ref.id, ref.version) not in refs]
    if missing_refs:
        report.add("REQUIRED_QUESTION_MISSING", "questions", "计划未包含全部指定题目和版本。",
                   context={"requiredQuestions": missing_refs})
    if missing_skills := required - set().union(*chosen.values()):
        report.add("REQUIRED_SKILL_MISSING", "questions", "计划选题未覆盖全部必备技能。",
                   context={"skills": sorted(missing_skills)})
    if set(plan.experienceIds) - confirmed_experiences:
        report.add("UNCONFIRMED_EXPERIENCE", "experienceIds", "引用经历不属于提交时的已确认经历。")

    previous = contract.startDate
    scheduled = set()
    starts = {}
    first_unprioritized = None
    priority_set = set(contract.prioritySkills)
    position = 0
    for index, step in enumerate(plan.schedule):
        field = f"schedule.{index}"
        when = step.scheduledDate
        if when is None and contract.deadline:
            report.add("MISSING_SCHEDULE_DATE", field + ".scheduledDate", "有截止日期时每个步骤须明确日期。")
        if when is not None:
            if contract.deadline and when > contract.deadline:
                report.add("DEADLINE_EXCEEDED", field + ".scheduledDate", "学习步骤超过任务截止日期。",
                           context={"deadline": contract.deadline.isoformat()})
            if when < previous:
                report.add("INVALID_DATE_ORDER", field + ".scheduledDate", "步骤日期须按创建日或之后的顺序排列。")
            previous = max(previous, when)
        assigned = set(step.questionRefs)
        if assigned - ids or assigned & scheduled or len(assigned) != len(step.questionRefs):
            report.add("INVALID_STEP_REFERENCE", field + ".questionRefs", "所选每道题须且只须安排一次。")
        scheduled.update(assigned)
        for identifier in step.questionRefs:
            topics = chosen.get(identifier, set()) & priority_set
            if first_unprioritized is None and not topics:
                first_unprioritized = position
            for skill in topics:
                starts.setdefault(skill, position)
            position += 1
        if step.skill and not any(topic_skills(
            allowed[key].get("topic", ""), {step.skill},
        ) for key in refs if key[0] in assigned):
            report.add("STEP_SKILL_MISMATCH", field + ".skill", "步骤技能须与引用题目的主题匹配。")
    if ids - scheduled:
        report.add("UNSCHEDULED_QUESTION", "schedule", "每道选中题目都必须出现在学习步骤中。")
    priorities = [starts[skill] for skill in contract.prioritySkills if skill in starts]
    mismatch = priorities != sorted(priorities) or (priorities and first_unprioritized is not None
                                                     and max(priorities) > first_unprioritized)
    if contract.version == 2:
        topics = [topics_by_id.get(identifier, "") for step in plan.schedule for identifier in step.questionRefs]
        mismatch = len(topics_by_id) == len(ids) and not priority_order_matches(contract, topics)
    if mismatch:
        details = {"prioritySkills": contract.prioritySkills}
        if contract.version == 2:
            details["orderMode"] = contract.orderMode
        report.add("PRIORITY_ORDER_MISMATCH", "schedule", "学习步骤须遵守优先技能的顺序。",
                   context=details)
    return report


def replay_snapshot(plan: TrainingPlan, catalog: list[dict], evidence: set[str]) -> dict:
    """Keep only the fields needed to reproduce a failed business check."""
    data = plan.model_dump(mode="json")
    data["analysis"] = "replay"
    data["experienceIds"] = ["00000000-0000-0000-0000-000000000000"] if set(plan.experienceIds) - evidence else []
    known = {item["id"] for item in catalog}
    topics = {item.get("topic", "") for item in catalog}
    unknown = {}

    def question_id(identifier):
        if identifier in known:
            return identifier
        if identifier not in unknown:
            index = len(unknown)
            while f"unlisted-{index}" in known or f"unlisted-{index}" in unknown.values():
                index += 1
            unknown[identifier] = f"unlisted-{index}"
        return unknown[identifier]

    for ref in data["questions"]:
        ref["id"] = question_id(ref["id"])
    for step in data["schedule"]:
        step["title"] = "replay"
        step["questionRefs"] = [question_id(ref) for ref in step["questionRefs"]]
        if step["skill"] and not any(topic_skills(topic, {step["skill"]}) for topic in topics):
            step["skill"] = "unlisted-skill"
    return data


_DATE_CODES = {"DEADLINE_EXCEEDED", "INVALID_DATE_ORDER", "MISSING_SCHEDULE_DATE"}


def repair_locally(
    plan: TrainingPlan, report: VerificationReport, contract: TrainingContract, catalog: list[dict],
) -> TrainingPlan | None:
    codes = {error.code for error in report.errors}
    if not codes or not codes <= _DATE_CODES | {"QUESTION_VERSION_MISMATCH", "REQUIRED_QUESTION_MISSING",
                                              "STEP_SKILL_MISMATCH", "REQUIRED_SKILL_MISSING"}:
        return None
    data = plan.model_dump(mode="json")
    changed = False
    if "QUESTION_VERSION_MISMATCH" in codes:
        by_id: dict[str, list[int]] = {}
        for item in catalog:
            by_id.setdefault(item["id"], []).append(item["version"])
        pinned = {ref.id: ref.version for ref in contract.requiredQuestions}
        for ref in data["questions"]:
            versions = by_id.get(ref["id"], [])
            if len(versions) == 1 and ref["version"] not in versions:
                ref["version"] = pinned.get(ref["id"], versions[0])
                changed = True
    if codes & _DATE_CODES:
        previous = contract.startDate
        for step in data["schedule"]:
            when = max(previous, date.fromisoformat(step["scheduledDate"])) if step["scheduledDate"] else previous
            when = min(when, contract.deadline) if contract.deadline else when
            if step["scheduledDate"] is not None or contract.deadline is not None:
                step["scheduledDate"] = when.isoformat()
            previous = when
        changed = True
    return TrainingPlan.model_validate(data) if changed else None
