"""Native Python endpoints for job records and the applicant profile."""

import re
from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AfterValidator, BaseModel, Field, StringConstraints, field_validator, model_validator

from app.core.dependencies import get_current_user
from app.core.exceptions import BizError
from app.core.response import success
from app.db.career import career_transaction, verify_career_schema
from app.models.user_model import User
from app.services.career_records import CareerRecords


class CareerRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validate(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                message = error.errors()[0]["msg"]
                raise BizError(message.removeprefix("Value error, "), code=400) from error

        return validate


def non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("必填字段不能为空")
    return value


Text160 = Annotated[str, StringConstraints(max_length=160)]
RequiredText160 = Annotated[Text160, AfterValidator(non_blank)]
Month = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]


class JobInput(BaseModel):
    company: RequiredText160
    title: RequiredText160
    location: Text160 | None = None
    description: Annotated[str, StringConstraints(max_length=40000), AfterValidator(non_blank)]
    sourceName: RequiredText160
    sourceUrl: str | None = Field(default=None, max_length=2048)
    sourcedOn: date
    skills: str | None = Field(default=None, max_length=1000)

    @field_validator("sourceUrl")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            parsed = urlsplit(value)
            if re.search(r"\s|[\x00-\x1f\x7f]|%(?![0-9a-fA-F]{2})", value):
                raise ValueError
            host = parsed.hostname
        except ValueError:
            raise ValueError("请输入有效的招聘来源链接") from None
        if not host or parsed.username is not None or parsed.scheme not in {"http", "https"}:
            raise ValueError("来源链接须为 HTTP 或 HTTPS 地址")
        return value


class ExperienceInput(BaseModel):
    type: Literal["education", "research", "project", "internship"]
    title: RequiredText160
    organization: Text160 | None = None
    startMonth: Month | None = None
    endMonth: Month | None = None
    description: Annotated[str, StringConstraints(max_length=12000), AfterValidator(non_blank)]
    sourceNote: str | None = Field(default=None, max_length=500)
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_months(self):
        if self.startMonth and self.endMonth and self.endMonth < self.startMonth:
            raise ValueError("结束月份应晚于或等于起始月份")
        return self


class ProfileInput(BaseModel):
    targetRole: Text160 | None = None
    graduationMonth: Month | None = None
    preferences: str | None = Field(default=None, max_length=2000)


class ActiveJob(BaseModel):
    jobId: UUID | None = None


class JobNotesInput(BaseModel):
    revision: int = Field(ge=0, le=2147483647)
    notes: str | None = Field(default=None, max_length=3000)


async def records(user: Annotated[User, Depends(get_current_user)]):
    async with career_transaction() as connection:
        yield CareerRecords(connection, str(user.id))


Records = Annotated[CareerRecords, Depends(records)]
router = APIRouter(prefix="/career", tags=["career"], route_class=CareerRoute)


@router.get("/health")
async def health():
    try:
        await verify_career_schema()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "DOWN", "components": {"db": {"status": "DOWN"}}})
    return {"status": "UP", "components": {"db": {"status": "UP"}, "careerAgent": {"status": "UP"}}}


@router.get("/profile")
async def get_profile(db: Records):
    return success(await db.profile())


@router.put("/profile")
async def put_profile(body: ProfileInput, db: Records):
    return success(await db.save_profile(body.model_dump()))


@router.get("/jobs")
async def list_jobs(db: Records):
    return success(await db.jobs().all())


@router.post("/jobs", status_code=201)
async def create_job(body: JobInput, db: Records):
    return success(await db.jobs().create(body.model_dump()))


@router.get("/jobs/active")
async def active_job(db: Records):
    return success(await db.active_job())


@router.put("/jobs/active")
async def select_job(body: ActiveJob, db: Records):
    return success(await db.select_job(str(body.jobId) if body.jobId else None))


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: Records):
    return success(await db.jobs().get(job_id))


@router.put("/jobs/{job_id}")
async def update_job(job_id: str, body: JobInput, db: Records):
    return success(await db.jobs().update(job_id, body.model_dump()))


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, db: Records):
    await db.jobs().delete(job_id)
    return success()


@router.get("/jobs/{job_id}/memory")
async def get_job_notes(job_id: str, db: Records):
    return success(await db.job_notes(job_id))


@router.put("/jobs/{job_id}/memory")
async def put_job_notes(job_id: str, body: JobNotesInput, db: Records):
    return success(await db.save_job_notes(job_id, body.revision, body.notes))


@router.get("/experiences")
async def list_experiences(db: Records):
    return success(await db.experiences().all())


@router.post("/experiences", status_code=201)
async def create_experience(body: ExperienceInput, db: Records):
    return success(await db.experiences().create(body.model_dump()))


@router.get("/experiences/{experience_id}")
async def get_experience(experience_id: str, db: Records):
    return success(await db.experiences().get(experience_id))


@router.put("/experiences/{experience_id}")
async def update_experience(experience_id: str, body: ExperienceInput, db: Records):
    return success(await db.experiences().update(experience_id, body.model_dump()))


@router.delete("/experiences/{experience_id}")
async def delete_experience(experience_id: str, db: Records):
    await db.experiences().delete(experience_id)
    return success()
