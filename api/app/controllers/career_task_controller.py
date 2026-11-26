"""Career task submission and state management on the native backend."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.controllers.career_records_controller import CareerRoute, Records
from app.core.exceptions import BizError
from app.core.response import success
from app.services.career_queue import PUBLIC_KINDS, CareerQueue, view
from app.services.career_training import OPEN_QUESTION, CareerTraining

router = APIRouter(prefix="/career/tasks", tags=["career"], route_class=CareerRoute)


class JobRequest(BaseModel):
    requestId: UUID
    jobId: UUID


class PreparationRequest(JobRequest):
    documentIds: list[UUID] | None = Field(default=None, max_length=3)
    skillId: UUID | None = None
    purpose: Literal["NOTES"] | None = None
    topic: str | None = Field(default=None, max_length=80)


class TrainingRequest(JobRequest):
    role: Literal["backend", "algorithm", "llm"] | None = None
    preparationId: UUID | None = None
    preferredQuestion: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,64}$")
    documentIds: list[UUID] | None = Field(default=None, max_length=3)
    skillId: UUID | None = None
    previousPlanId: UUID | None = None
    reviewTaskId: UUID | None = None


class InterviewRequest(JobRequest):
    questionId: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    questionVersion: int = Field(gt=0)
    answer: str = Field(min_length=1, max_length=6000)
    documentIds: list[UUID] | None = Field(default=None, max_length=3)
    skillId: UUID | None = None


class ReviewRequest(BaseModel):
    requestId: UUID
    planId: UUID


class TaskTransition(BaseModel):
    action: Literal["PAUSE", "RESUME", "CANCEL"]
    status: str = Field(min_length=1)
    generation: int = Field(ge=0)


@router.post("/discovery")
async def discover(body: JobRequest, db: Records):
    return await submit("DISCOVERY", body, db)


@router.post("/preparation")
async def prepare(body: PreparationRequest, db: Records):
    return await submit("PREPARATION", body, db)


@router.post("/training")
async def train(body: TrainingRequest, db: Records):
    return await submit("TRAINING", body, db)


@router.post("/interview")
async def interview(body: InterviewRequest, db: Records):
    if not body.answer.strip():
        raise BizError("请填写作答内容", code=400)
    return await submit("INTERVIEW", body, db)


@router.post("/review")
async def review(body: ReviewRequest, db: Records):
    queue = CareerQueue(db.db)
    request = body.model_dump(mode="json")
    existing = await queue.by_request(db.user, "REVIEW", request)
    if existing is not None:
        return success(view(existing))
    job_id, context = await CareerTraining(db).review_snapshot(str(body.planId))
    return success(view(await queue.insert(db.user, "REVIEW", job_id, request, context)))


async def submit(kind: str, body: JobRequest, db: Records, *, pinned: list[dict] | None = None) -> dict:
    queue = CareerQueue(db.db)
    request = body.model_dump(mode="json", exclude_none=True)
    if request.get("documentIds") == []:
        request.pop("documentIds")
    if isinstance(body, TrainingRequest):
        request.setdefault("role", None)
    existing = await queue.by_request(db.user, kind, request)
    if existing:
        return success(view(existing))
    job = await db.jobs().get(str(body.jobId))
    snapshot = {
        "label": f"{job['company']} · {job['title']}", "company": job["company"], "title": job["title"],
        "location": job["location"],
    }
    context: dict = {"job": snapshot}
    if not kind == "DISCOVERY":
        snapshot["jd"] = job["description"][:8000]
        snapshot["skills"] = job["skills"] or ""
        documents = request.get("documentIds", [])
        if len(set(documents)) != len(documents):
            raise BizError("备考资料不能重复", code=400)
        preferences = await db.job_notes(job["id"])
        if preferences["notes"] is not None:
            context["preferences"] = preferences
        for key in ("documentIds", "skillId", "purpose"):
            if key in request:
                context[key] = request[key]
        if isinstance(body, PreparationRequest):
            if body.purpose == "NOTES" and not documents:
                raise BizError("请先选择用于整理面经的资料", code=400)
            if body.topic and body.topic.strip():
                context["topic"] = body.topic.strip()
    if isinstance(body, TrainingRequest):
        if pinned:
            context["studyConstraints"] = pinned
        await CareerTraining(db).apply_training_snapshot(job["id"], request, context)
    if isinstance(body, InterviewRequest):
        service = CareerTraining(db)
        if OPEN_QUESTION.fullmatch(body.questionId):
            question = await service.open_question(job["id"], body.questionId, body.questionVersion)
        else:
            question = await service.practice.evidence_question(body.questionId, body.questionVersion)
        context["question"] = question
        context["answer"] = body.answer.strip()
    row = await queue.insert(db.user, kind, job["id"], request, context)
    return success(view(row))


@router.get("")
async def list_tasks(
    db: Records, kind: str, jobId: UUID | None = None, content: str | None = None, page: int = 1,
):
    if kind not in PUBLIC_KINDS or not 1 <= page <= 2147483647:
        raise BizError("任务类型或页码无效", code=400)
    if content is not None and (kind != "PREPARATION" or content not in {"notes", "questions"}):
        raise BizError("备考内容类型无效", code=400)
    return success(await CareerQueue(db.db).list(db.user, kind, str(jobId) if jobId else None, content, page))


@router.get("/{task_id}")
async def get_task(task_id: UUID, db: Records):
    return success(view(await CareerQueue(db.db).owned(db.user, str(task_id))))


@router.get("/{task_id}/events")
async def get_events(task_id: UUID, db: Records):
    return success(await CareerQueue(db.db).events(db.user, str(task_id)))


@router.get("/{task_id}/training-progress")
async def training_progress(task_id: UUID, db: Records):
    return success(await CareerTraining(db).progress(str(task_id)))


@router.post("/{task_id}/retry")
async def retry_task(task_id: UUID, db: Records):
    return success(view(await CareerQueue(db.db).retry(db.user, str(task_id))))


@router.post("/{task_id}/state")
async def change_task_state(task_id: UUID, body: TaskTransition, db: Records):
    row = await CareerQueue(db.db).change_state(db.user, str(task_id), **body.model_dump())
    return success(view(row))
