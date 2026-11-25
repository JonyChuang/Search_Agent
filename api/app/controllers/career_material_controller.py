"""Resume studio, application history and workspace attachments."""

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app.controllers.career_records_controller import CareerRoute, Records
from app.core.exceptions import BizError
from app.core.response import success
from app.schemas.career_material_schema import (
    ApplicationEdit,
    ApplicationInput,
    Composition,
    ResumeInput,
    ResumeProfile,
    StageInput,
    WorkspaceInput,
)
from app.services.career_applications import MAX_FILE_BYTES, CareerApplications
from app.services.career_resumes import CareerResumes

router = APIRouter(prefix="/career", tags=["career"], route_class=CareerRoute)


@router.get("/resumes")
async def resumes(db: Records):
    return success(await CareerResumes(db).list())


@router.post("/resumes")
async def resume(body: ResumeInput, db: Records):
    return success(await CareerResumes(db).create(
        str(body.requestId), str(body.jobId), [str(record) for record in body.experienceIds],
    ))


@router.get("/resume-profile")
async def resume_profile(db: Records):
    return success(await CareerResumes(db).profile())


@router.put("/resume-profile")
async def save_resume_profile(body: ResumeProfile, db: Records):
    return success(await CareerResumes(db).save_profile(
        body.revision, body.content.model_dump(mode="json"),
        str(body.confirmExperienceId) if body.confirmExperienceId else None,
    ))


@router.post("/resumes/composed")
async def compose(body: Composition, db: Records):
    return success(await CareerResumes(db).compose(
        str(body.requestId), str(body.jobId) if body.jobId else None, body.revision,
    ))


@router.get("/resumes/{resume_id}/composition")
async def composition(resume_id: UUID, db: Records):
    return success(await CareerResumes(db).composition(str(resume_id)))


@router.get("/applications")
async def applications(db: Records):
    return success(await CareerApplications(db).list())


@router.post("/applications")
async def create_application(body: ApplicationInput, db: Records):
    return success(await CareerApplications(db).create(
        str(body.jobId), str(body.resumeId) if body.resumeId else None, (body.answers or "").strip(),
    ))


@router.put("/applications/{application_id}")
async def edit_application(application_id: UUID, body: ApplicationEdit, db: Records):
    return success(await CareerApplications(db).update(
        str(application_id), body.revision, str(body.resumeId) if body.resumeId else None,
        (body.answers or "").strip(),
    ))


@router.post("/applications/{application_id}/stage")
async def stage_application(application_id: UUID, body: StageInput, db: Records):
    return success(await CareerApplications(db).stage(
        str(application_id), body.revision, body.stage, body.note,
        body.receipt.model_dump(mode="json") if body.receipt else None,
    ))


@router.get("/applications/{application_id}/events")
async def application_events(application_id: UUID, db: Records):
    return success(await CareerApplications(db).events(str(application_id)))


@router.get("/jobs/{job_id}/application-workspace")
async def workspace(job_id: UUID, db: Records):
    return success(await CareerApplications(db).workspace(str(job_id)))


@router.put("/jobs/{job_id}/application-workspace")
async def save_workspace(job_id: UUID, request: Request, db: Records):
    async with request.form(max_files=7, max_fields=1) as form:
        drafts = form.getlist("draft")
        if len(drafts) != 1:
            raise BizError("请提供一份网申草稿", code=400)
        draft = drafts[0]
        value = await draft.read(128 * 1024 + 1) if isinstance(draft, UploadFile) else draft
        if len(value) > 128 * 1024:
            raise BizError("网申草稿内容过长", code=413, status_code=413)
        try:
            body = await run_in_threadpool(WorkspaceInput.model_validate_json, value)
        except ValidationError as error:
            raise BizError("网申草稿内容或字段格式无效", code=400) from error
        uploads = {}
        for key, part in form.multi_items():
            if key == "draft":
                continue
            if key in uploads or not isinstance(part, UploadFile):
                raise BizError("上传文件与草稿中的附件不匹配", code=400)
            value = await part.read(MAX_FILE_BYTES + 1)
            if len(value) > MAX_FILE_BYTES:
                raise BizError("单个附件最多 10 MB，请缩小文件后重试", code=413, status_code=413)
            uploads[key] = (part.filename, value)
    return success(await CareerApplications(db).save_workspace(
        str(job_id), str(body.requestId), body.revision, str(body.resumeId) if body.resumeId else None,
        (body.answers or "").strip(), body.content.model_dump(mode="json"), uploads,
    ))


@router.get("/applications/{application_id}/files/{file_id}")
async def application_file(application_id: UUID, file_id: UUID, db: Records):
    service = CareerApplications(db)
    await service.owned(str(application_id))
    file = await service.stored_file(str(application_id), str(file_id))
    if file is None:
        raise BizError("附件不存在", code=404, status_code=404)
    return Response(file.content, media_type="application/octet-stream", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file.name, safe='')}",
    })
