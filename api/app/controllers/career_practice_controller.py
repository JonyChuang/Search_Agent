"""Question bank and versioned objective practice API."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.controllers.career_records_controller import CareerRoute, Records
from app.core.exceptions import BizError
from app.core.response import success
from app.services.career_practice import CareerPractice

router = APIRouter(prefix="/career", tags=["career"], route_class=CareerRoute)


class Submission(BaseModel):
    requestId: UUID
    questionId: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    questionVersion: int = Field(gt=0)
    answer: Literal["A", "B", "C", "D"]
    jobId: UUID | None = None


@router.get("/interview-notes")
async def interview_notes(db: Records):
    return success(await CareerPractice(db).notes())


@router.get("/recommendations")
async def recommendations(jobId: UUID, db: Records):
    job = await db.jobs().get(str(jobId))
    practice = CareerPractice(db)
    content = " ".join(str(job.get(key) or "") for key in ("title", "description", "skills")).lower()
    notes = [
        note for note in await practice.notes()
        if note["company"].lower() == job["company"].lower() or note["role"].lower() in content
    ]
    questions = await practice.matching_questions({**job, "jd": job["description"]})
    return success({"notes": notes[:12], "questions": questions[:30]})


@router.get("/questions")
async def list_questions(db: Records, role: str | None = None):
    return success(await CareerPractice(db).questions(role))


@router.get("/questions/{question_id}")
async def get_question(question_id: str, db: Records, version: int | None = None):
    return success(await CareerPractice(db).question(question_id, version))


@router.get("/practice/attempts")
async def get_attempts(db: Records, page: int = 1, jobId: UUID | None = None):
    if not 1 <= page <= 2147483647:
        raise BizError("页码须为正整数", code=400)
    return success(await CareerPractice(db).attempts(str(jobId) if jobId else None, page))


@router.post("/practice/attempts")
async def submit_attempt(body: Submission, db: Records):
    return success(await CareerPractice(db).submit(body.model_dump(mode="json")))


@router.get("/practice/wrong-questions")
async def wrong_questions(db: Records, jobId: UUID | None = None):
    return success(await CareerPractice(db).wrong_questions(str(jobId) if jobId else None))
