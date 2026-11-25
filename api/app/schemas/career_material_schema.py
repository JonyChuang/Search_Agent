"""Validation for resume and application forms."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, Field, StringConstraints


def non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("请填写必填字段")
    return value


Text160 = Annotated[str, StringConstraints(max_length=160)]
Required160 = Annotated[Text160, AfterValidator(non_blank)]
Month = Annotated[str, StringConstraints(pattern=r"^(?:|[0-9]{4}-(?:0[1-9]|1[0-2]))$")]
Email = Annotated[str, StringConstraints(pattern=r"^(?:|[^@\s]+@[^@\s]+)$", max_length=160)]
Stage = Literal["DRAFT", "SUBMITTED", "SCREENING", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"]


class ResumeEntry(BaseModel):
    id: UUID
    kind: Literal["education", "project", "internship", "research", "award"]
    title: Required160
    organization: Text160
    role: Text160
    startMonth: Month
    endMonth: Month
    description: str = Field(max_length=12000)
    sourceNote: str | None = Field(default=None, max_length=500)


class ResumeContent(BaseModel):
    name: str = Field(max_length=80)
    phone: str = Field(max_length=40)
    email: Email
    targetRole: Text160
    skills: str = Field(max_length=1000)
    photo: str | None = Field(default=None, max_length=700000)
    showPhoto: bool
    template: Literal["classic", "tech", "campus", "modern", "academic", "mono"]
    entries: list[ResumeEntry] = Field(max_length=40)


class ResumeProfile(BaseModel):
    revision: int = Field(ge=0)
    content: ResumeContent
    confirmExperienceId: UUID | None = None


class ResumeInput(BaseModel):
    requestId: UUID
    jobId: UUID
    experienceIds: list[UUID] = Field(min_length=1, max_length=12)


class Composition(BaseModel):
    requestId: UUID
    jobId: UUID | None = None
    revision: int = Field(gt=0)


class ApplicationDraft(BaseModel):
    resumeId: UUID | None = None
    answers: str | None = Field(default=None, max_length=12000)


class ApplicationInput(ApplicationDraft):
    jobId: UUID


class ApplicationEdit(ApplicationDraft):
    revision: int = Field(gt=0)


class Attachment(BaseModel):
    id: UUID
    kind: Literal["FILE", "LINK"]
    label: Annotated[str, StringConstraints(max_length=100), AfterValidator(non_blank)]
    required: bool = False
    fileId: UUID | None = None
    url: str | None = Field(default=None, max_length=2048)


class Question(BaseModel):
    id: UUID
    label: Required160
    required: bool = False
    answer: str | None = Field(default=None, max_length=2500)


class FormAnswers(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    email: Email | None = None
    education: str | None = Field(default=None, max_length=2000)
    startDate: date | None = None
    weeklyDays: int | None = Field(default=None, ge=1, le=7)
    duration: str | None = Field(default=None, max_length=80)
    motivation: str | None = Field(default=None, max_length=2500)
    questions: list[Question] = Field(max_length=12)


class Workspace(BaseModel):
    form: FormAnswers
    attachments: list[Attachment] = Field(max_length=12)


class WorkspaceInput(ApplicationDraft):
    requestId: UUID
    revision: int = Field(ge=0)
    content: Workspace


class Receipt(BaseModel):
    submittedAt: AwareDatetime
    applicationNumber: Text160 | None = None


class StageInput(BaseModel):
    revision: int = Field(gt=0)
    stage: Stage
    note: str | None = Field(default=None, max_length=1000)
    receipt: Receipt | None = None
