"""Short-lived browser tickets bound to an applicant-approved draft revision."""

import base64
import binascii
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import compare_digest, token_bytes
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.controllers.career_records_controller import CareerRoute, Records
from app.core.exceptions import BizError
from app.core.response import success
from app.db.career import career_transaction
from app.services.career_applications import CareerApplications
from app.services.career_queue import conflict
from app.services.career_records import CareerRecords

router = APIRouter(prefix="/career/application-browser", tags=["career"], route_class=CareerRoute)


class Applicant(BaseModel):
    firstName: str = Field(max_length=80)
    lastName: str = Field(max_length=80)


class Event(BaseModel):
    action: Literal["REVIEW", "PERMIT", "CONFIRM"]
    url: str = Field(min_length=1, max_length=2048)
    applicationNumber: str | None = Field(default=None, max_length=160)


def target_path(url: str | None) -> str:
    try:
        parsed = urlsplit(url or "")
        if parsed.scheme == "https" and parsed.netloc == "job-boards.greenhouse.io":
            path = unquote(parsed.path)
            if re.fullmatch(r"/[a-zA-Z0-9_-]{1,100}/jobs/[0-9]{1,20}/?", path):
                return path.rstrip("/")
    except ValueError:
        pass
    raise BizError("请使用 job-boards.greenhouse.io 上的岗位申请链接", code=400)


def missing():
    return BizError("浏览器填表凭证不存在或已过期", code=404, status_code=404)


def changed():
    return conflict("投递状态或材料已变化，请返回网申助手核对")


@router.post("/applications/{application_id}/ticket")
async def ticket(application_id: UUID, body: Applicant, db: Records):
    if not body.firstName.strip() or not body.lastName.strip():
        raise BizError("请填写用于官网申请的姓名", code=400)
    service = CareerApplications(db)
    app = await service.find(str(application_id), lock=True)
    if app is None:
        raise missing()
    if app["stage"] != "DRAFT" or app["resumeId"] is None:
        raise conflict("请先保存待投递的简历版本和网申草稿")
    prior = (await service.execute("""
        SELECT state FROM career_application_browser WHERE application_id = :id
    """, id=app["id"])).scalar_one_or_none()
    if prior in {"VERIFYING", "CONFIRMED"}:
        raise conflict("已有投递正在核对，请先查看原申请结果")
    source = (await db.jobs().get(app["jobId"]))["sourceUrl"]
    target = target_path(source)
    workspace, _ = await service.raw_workspace(app["id"])
    form = workspace["form"]
    if not (form["email"] or "").strip():
        raise BizError("请先在网申材料填好邮箱并保存", code=400)
    token, ticket_id = token_bytes(32), str(uuid4())
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    await service.execute("""
        INSERT INTO career_application_browser
            (application_id, id, revision, token_hash, target_path, state, expires_at)
        VALUES (:application, :id, :revision, :hash, :target, 'PREPARED', :expires) AS incoming
        ON DUPLICATE KEY UPDATE id = incoming.id, revision = incoming.revision, token_hash = incoming.token_hash,
            target_path = incoming.target_path, state = 'PREPARED', expires_at = incoming.expires_at,
            requested_at = NULL, evidence_url = NULL
    """, application=app["id"], id=ticket_id, revision=app["revision"],
        hash=sha256(token).hexdigest(), target=target, expires=expires.replace(tzinfo=None))
    return success({
        "id": ticket_id, "token": base64.urlsafe_b64encode(token).decode().rstrip("="), "target": source,
        "firstName": body.firstName.strip(), "lastName": body.lastName.strip(),
        "answers": {"email": form["email"], "phone": form["phone"]}, "expiresAt": expires,
    })


@router.get("/applications/{application_id}/status")
async def status(application_id: UUID, db: Records):
    service = CareerApplications(db)
    if await service.find(str(application_id)) is None:
        raise missing()
    state = (await service.execute("""
        SELECT state FROM career_application_browser WHERE application_id = :id
    """, id=str(application_id))).scalar_one_or_none()
    return success(state or "NONE")


@router.post("/applications/{application_id}/release")
async def release(application_id: UUID, db: Records):
    service = CareerApplications(db)
    app = await service.find(str(application_id), lock=True)
    if app is None:
        raise missing()
    if app["stage"] != "DRAFT":
        raise changed()
    row = await service.execute("""
        UPDATE career_application_browser SET state = 'RELEASED' WHERE application_id = :id AND state = 'VERIFYING'
    """, id=app["id"])
    if row.rowcount != 1:
        raise changed()
    return success("RELEASED")


@router.post("/runs/{ticket_id}/event")
async def callback(ticket_id: UUID, body: Event, token: Annotated[str, Header(alias="X-Application-Run")] = ""):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise missing()
    try:
        digest = sha256(base64.b64decode(token + "=", altchars=b"-_", validate=True)).hexdigest()
    except (ValueError, binascii.Error):
        raise missing() from None
    async with career_transaction() as connection:
        sql = """
            SELECT b.application_id, a.user_id AS owner, b.revision, b.token_hash, b.target_path,
                b.state, b.requested_at, b.expires_at
            FROM career_application_browser b JOIN career_application a ON a.id = b.application_id WHERE b.id = :id
        """
        params = {"id": str(ticket_id)}
        prior = (await connection.execute(text(sql), params)).one_or_none()
        if prior is None:
            raise missing()
        records = CareerRecords(connection, prior.owner)
        service = CareerApplications(records)
        app = await service.find(prior.application_id, lock=True)
        current = (await connection.execute(text(sql + " FOR UPDATE"), params)).one_or_none()
        if app is None or current is None or not compare_digest(current.token_hash, digest) \
                or current.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
            raise missing()
        if current.target_path != target_path(body.url):
            raise conflict("当前页面不属于此岗位")
        if body.action == "CONFIRM" and current.state == "CONFIRMED":
            return success(current.state)
        if app["revision"] != current.revision:
            raise changed()
        if body.action == "REVIEW":
            if current.state not in {"PREPARED", "NEEDS_USER"}:
                raise changed()
            state = "NEEDS_USER"
        elif body.action == "PERMIT":
            if current.state != "NEEDS_USER" or app["stage"] != "DRAFT":
                raise changed()
            source = (await records.jobs().get(app["jobId"]))["sourceUrl"]
            if current.target_path != target_path(source):
                raise changed()
            await service.execute("""
                UPDATE career_application_browser SET requested_at = CURRENT_TIMESTAMP(6) WHERE id = :id
            """, **params)
            state = "VERIFYING"
        else:
            if current.state != "VERIFYING" or app["stage"] != "DRAFT" or current.requested_at is None:
                raise changed()
            await service.stage(app["id"], app["revision"], "SUBMITTED", "Greenhouse 招聘页确认", {
                "submittedAt": current.requested_at.replace(tzinfo=timezone.utc).isoformat(),
                "applicationNumber": body.applicationNumber,
            })
            await service.execute("""
                UPDATE career_application_browser SET evidence_url = :url WHERE id = :id
            """, **params, url=body.url)
            state = "CONFIRMED"
        await service.execute("UPDATE career_application_browser SET state = :state WHERE id = :id", **params, state=state)
        return success(state)
