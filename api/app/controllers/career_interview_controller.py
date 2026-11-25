"""Public endpoints for the mock interview lifecycle."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.controllers.career_records_controller import CareerRoute, Records
from app.core.exceptions import BizError
from app.core.response import success
from app.services.career_interviews import CareerInterviews

router = APIRouter(prefix="/career/interviews", tags=["career"], route_class=CareerRoute)


class Start(BaseModel):
    requestId: UUID
    jobId: UUID
    mode: Literal["VIDEO", "VOICE", "TEXT"]
    count: Literal[3, 5, 8]


class Answer(BaseModel):
    requestId: UUID
    revision: int = Field(ge=0)
    answer: str = Field(max_length=4000)


class Decision(BaseModel):
    taskId: UUID
    skipFailed: bool = False


class Status(BaseModel):
    revision: int = Field(ge=0)
    status: Literal["ACTIVE", "PAUSED", "FINISHED"]


@router.get("")
async def list_sessions(db: Records, page: int = 1):
    if not 1 <= page <= 2147483647:
        raise BizError("页码须为正整数", code=400)
    return success(await CareerInterviews(db).list_page(page))


@router.post("")
async def start(body: Start, db: Records):
    return success(await CareerInterviews(db).start(str(body.requestId), str(body.jobId), body.mode, body.count))


@router.get("/{session_id}")
async def get(session_id: UUID, db: Records):
    service = CareerInterviews(db)
    return success(await service.view(await service.owned(str(session_id))))


@router.post("/{session_id}/answer")
async def answer(session_id: UUID, body: Answer, db: Records):
    value = body.answer.strip()
    if not value:
        raise BizError("请输入本题回答", code=400)
    return success(await CareerInterviews(db).answer(str(session_id), str(body.requestId), body.revision, value))


@router.post("/{session_id}/retry")
async def retry(session_id: UUID, body: Decision, db: Records):
    return success(await CareerInterviews(db).decision(str(session_id), str(body.taskId), retry=True))


@router.post("/{session_id}/advance")
async def advance(session_id: UUID, body: Decision, db: Records):
    return success(await CareerInterviews(db).decision(str(session_id), str(body.taskId), skip_failed=body.skipFailed))


@router.post("/{session_id}/status")
async def status(session_id: UUID, body: Status, db: Records):
    return success(await CareerInterviews(db).status(str(session_id), body.revision, body.status))
