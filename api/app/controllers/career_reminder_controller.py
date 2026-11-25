"""Job preparation reminder API."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.controllers.career_records_controller import CareerRoute, Records
from app.core.response import success
from app.services.career_reminders import CareerReminders

router = APIRouter(prefix="/career/reminders", tags=["career"], route_class=CareerRoute)


class Reminder(BaseModel):
    jobId: UUID | None = None
    type: Literal["REVIEW", "INTERVIEW", "APPLICATION"]
    title: str = Field(max_length=160)
    dueAt: AwareDatetime
    externalDelivery: bool = False

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写提醒标题")
        return value.strip()

    def values(self) -> dict:
        result = self.model_dump()
        result["jobId"] = str(self.jobId) if self.jobId else None
        return result


class Create(BaseModel):
    requestId: UUID
    reminder: Reminder


class Edit(BaseModel):
    revision: int = Field(gt=0)
    reminder: Reminder


class Transition(BaseModel):
    revision: int = Field(gt=0)
    status: Literal["DONE", "CANCELLED"]


@router.get("")
async def list_reminders(db: Records, jobId: UUID | None = None):
    return success(await CareerReminders(db).list(str(jobId) if jobId else None))


@router.get("/due-count")
async def due_count(db: Records):
    return success(await CareerReminders(db).due_count())


@router.post("")
async def create_reminder(body: Create, db: Records):
    return success(await CareerReminders(db).save(str(body.requestId), body.reminder.values()))


@router.put("/{reminder_id}")
async def edit_reminder(reminder_id: UUID, body: Edit, db: Records):
    return success(await CareerReminders(db).save(str(reminder_id), body.reminder.values(), body.revision))


@router.post("/{reminder_id}/state")
async def change_reminder(reminder_id: UUID, body: Transition, db: Records):
    return success(await CareerReminders(db).change(str(reminder_id), body.status, body.revision))
