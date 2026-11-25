"""Revisioned application drafts, immutable receipts and retained attachments."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import bindparam, text

from app.core.exceptions import BizError
from app.schemas.career_material_schema import FormAnswers, Workspace
from app.services.career_queue import conflict
from app.services.career_records import CareerRecords
from app.services.career_resumes import CareerResumes

SELECT = """
    SELECT id, job_id AS jobId, company, job_title AS jobTitle, source_url AS sourceUrl, resume_id AS resumeId,
        answers, stage, revision, created_at AS createdAt, updated_at AS updatedAt
    FROM career_application WHERE user_id = :user
"""
EMPTY = Workspace(form=FormAnswers(questions=[]), attachments=[]).model_dump(mode="json")
MAX_FILE_BYTES = 10 * 1024 * 1024
SIGNATURES = {"pdf": b"%PDF-", "jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff", "png": b"\x89PNG\r\n\x1a\n"}


def _view(row) -> dict:
    return dict(row, **{key: row[key].replace(tzinfo=timezone.utc) for key in ("createdAt", "updatedAt")})


def _file_ids(content: dict) -> list[str]:
    return [item["fileId"] for item in content["attachments"] if item["fileId"]]


def _validate_content(content: dict) -> list[str]:
    attachments = content["attachments"]
    file_ids = _file_ids(content)
    if len(file_ids) > 6 or len(set(file_ids)) != len(file_ids):
        raise BizError("每份草稿最多保存 6 个文件，附件不能重复", code=400)
    if len({item["id"] for item in attachments}) != len(attachments):
        raise BizError("附件项目不能重复", code=400)
    for item in attachments:
        value = (item["url"] or "").strip()
        if (item["kind"] == "FILE" and value) or (item["kind"] == "LINK" and item["fileId"]):
            raise BizError("附件类型与内容不一致", code=400)
        if value:
            try:
                url = urlsplit(value)
                if url.hostname and url.scheme in {"http", "https"} and url.username is None:
                    continue
            except ValueError:
                pass
            raise BizError("附件链接须为 HTTP 或 HTTPS 地址", code=400)
    questions = content["form"]["questions"]
    if len({question["id"] for question in questions}) != len(questions):
        raise BizError("岗位问题不能重复", code=400)
    return file_ids


class CareerApplications:
    def __init__(self, records: CareerRecords):
        self.records = records
        self.db = records.db
        self.user = records.user
        self.resumes = CareerResumes(records)

    async def execute(self, sql, **values):
        return await self.db.execute(text(sql), {"user": self.user, **values})

    async def find(self, identity: str, *, job=False, lock=False) -> dict | None:
        where = " AND job_id = :id" if job else " AND id = :id"
        row = (await self.execute(SELECT + where + (" FOR UPDATE" if lock else ""),
                                  id=identity)).mappings().one_or_none()
        return _view(row) if row is not None else None

    async def owned(self, application_id: str, *, lock=False) -> dict:
        app = await self.find(application_id, lock=lock)
        if app is None:
            raise BizError("投递记录不存在", code=404, status_code=404)
        return app

    async def list(self) -> list[dict]:
        return [_view(row) for row in (await self.execute(SELECT + " ORDER BY updated_at DESC, id DESC")).mappings()]

    async def validate_resume(self, job: str, resume: str | None) -> None:
        if resume:
            selected = await self.resumes.find(resume)
            if selected is None or selected["jobId"] != job:
                raise BizError("请选择此岗位自己的简历版本", code=400)

    async def create(self, job_id: str, resume: str | None, answers: str) -> dict:
        found = await self.find(job_id, job=True)
        if found:
            return found
        job = await self.records.jobs().get(job_id)
        await self.validate_resume(job_id, resume)
        draft, _ = await self.insert_draft(job, resume, answers)
        return draft

    async def insert_draft(self, job: dict, resume: str | None, answers: str) -> tuple[dict, bool]:
        application_id = str(uuid4())
        await self.execute("""
            INSERT INTO career_application (id, user_id, job_id, company, job_title, source_url, resume_id, answers)
            VALUES (:id, :user, :job, :company, :title, :source, :resume, :answers)
            ON DUPLICATE KEY UPDATE id = id
        """, id=application_id, job=job["id"], company=job["company"], title=job["title"],
            source=job["sourceUrl"], resume=resume, answers=answers)
        saved = await self.find(job["id"], job=True, lock=True)
        created = saved["id"] == application_id
        if created:
            await self.event(application_id, 1, "DRAFT")
        return saved, created

    @staticmethod
    def require_revision(actual: int, requested: int) -> None:
        if actual != requested:
            raise conflict("记录已更新，请刷新后重试")

    async def require_editable(self, application: str) -> None:
        row = (await self.execute("""
            SELECT 1 FROM career_application_browser WHERE application_id = :id AND state = 'VERIFYING' LIMIT 1
        """, id=application)).scalar_one_or_none()
        if row:
            raise conflict("官网投递结果待核对，请先查看回执或确认未投递")

    async def update(self, application: str, revision: int, resume: str | None, answers: str) -> dict:
        current = await self.owned(application, lock=True)
        await self.validate_resume(current["jobId"], resume)
        self.require_revision(current["revision"], revision)
        if current["resumeId"] == resume and current["answers"] == answers:
            return current
        await self.require_editable(application)
        await self.execute("""
            UPDATE career_application SET resume_id = :resume, answers = :answers, revision = revision + 1
            WHERE id = :id AND user_id = :user
        """, id=application, resume=resume, answers=answers)
        updated = await self.owned(application)
        await self.record_materials_update(updated)
        return updated

    async def stage(
        self, application: str, revision: int, stage: str, note: str | None, receipt: dict | None,
    ) -> dict:
        current = await self.owned(application, lock=True)
        if receipt is not None and stage != "SUBMITTED":
            raise BizError("仅在记录已投递时填写回执", code=400)
        if current["stage"] == stage:
            if receipt is not None:
                prior = await self.latest_receipt(application)
                if prior and self.same_receipt(prior, receipt):
                    return current
                raise conflict("此岗位的投递状态已更新，请查看阶段历史")
            return current
        self.require_revision(current["revision"], revision)
        await self.execute("""
            UPDATE career_application SET stage = :stage, revision = revision + 1 WHERE id = :id AND user_id = :user
        """, id=application, stage=stage)
        snapshot = await self.materials(current) if stage == "SUBMITTED" else None
        await self.event(application, revision + 1, stage, note, snapshot, receipt)
        if stage == "SUBMITTED" and receipt is not None:
            await self.execute("""
                UPDATE career_application_browser SET state = 'CONFIRMED'
                WHERE application_id = :id AND state = 'VERIFYING'
            """, id=application)
        return await self.owned(application)

    @staticmethod
    def same_receipt(first: dict, second: dict) -> bool:
        return first.get("applicationNumber") == second.get("applicationNumber") and (
            datetime.fromisoformat(first["submittedAt"]) == datetime.fromisoformat(second["submittedAt"])
        )

    async def event(self, application, revision, stage, note=None, materials=None, receipt=None, kind="STAGE"):
        await self.execute("""
            INSERT INTO career_application_event
                (application_id, revision, stage, note, material_snapshot, receipt_json, event_type)
            VALUES (:id, :revision, :stage, :note, :material, :receipt, :kind)
        """, id=application, revision=revision, stage=stage, note=note, kind=kind,
            material=json.dumps(jsonable_encoder(materials), ensure_ascii=False) if materials is not None else None,
            receipt=json.dumps(receipt, ensure_ascii=False) if receipt is not None else None)

    async def events(self, application: str) -> list[dict]:
        await self.owned(application)
        rows = await self.execute("""
            SELECT stage, note, created_at AS createdAt, event_type AS eventType,
                material_snapshot AS materials, receipt_json AS receipt
            FROM career_application_event WHERE application_id = :id ORDER BY revision DESC
        """, id=application)
        return [dict(row, createdAt=row["createdAt"].replace(tzinfo=timezone.utc),
                     **{key: json.loads(row[key]) if row[key] is not None else None for key in ("materials", "receipt")})
                for row in rows.mappings()]

    async def latest_receipt(self, application: str) -> dict | None:
        raw = (await self.execute("""
            SELECT receipt_json FROM career_application_event
            WHERE application_id = :id AND receipt_json IS NOT NULL ORDER BY revision DESC LIMIT 1
        """, id=application)).scalar_one_or_none()
        return json.loads(raw) if raw is not None else None

    async def raw_workspace(self, application: str) -> tuple[dict, str | None]:
        row = (await self.execute("""
            SELECT workspace_json, workspace_request_id FROM career_application WHERE id = :id AND user_id = :user
        """, id=application)).one()
        return json.loads(row.workspace_json) if row.workspace_json is not None else EMPTY, row.workspace_request_id

    async def files(self, application: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        rows = await self.db.execute(text("""
            SELECT id, file_name AS name, file_size AS size
            FROM career_application_file WHERE application_id = :id AND id IN :files
        """).bindparams(bindparam("files", expanding=True)), {"id": application, "files": ids})
        return [dict(row) for row in rows.mappings()]

    async def workspace(self, job: str) -> dict:
        current = await self.find(job, job=True)
        if current is None:
            await self.records.jobs().get(job)
            return {"application": None, "workspace": {"content": EMPTY, "files": []}, "receipt": None}
        return await self.workspace_state(current)

    async def workspace_state(self, app: dict) -> dict:
        content, _ = await self.raw_workspace(app["id"])
        return {"application": app, "workspace": {"content": content, "files": await self.files(app["id"], _file_ids(content))},
                "receipt": await self.latest_receipt(app["id"])}

    async def save_workspace(
        self, job: str, request: str, revision: int, resume: str | None, answers: str, content: dict, uploads: dict,
    ) -> dict:
        current = await self.find(job, job=True, lock=True)
        if current is None and revision != 0:
            raise conflict("记录已更新，请刷新后重试")
        await self.validate_resume(job, resume)
        created = False
        if current is None:
            current, created = await self.insert_draft(await self.records.jobs().get(job), resume, answers)
        application = current["id"]
        existing, previous = await self.raw_workspace(application)
        if previous == request:
            if (current["resumeId"], current["answers"], existing) != (resume, answers, content):
                raise conflict("保存编号已使用，请重新保存")
            await self.store_files(application, content, uploads)
            return await self.workspace_state(current)
        if not created:
            self.require_revision(current["revision"], revision)
        await self.require_editable(application)
        await self.store_files(application, content, uploads)
        await self.execute("""
            UPDATE career_application SET resume_id = :resume, answers = :answers, workspace_json = :content,
                workspace_request_id = :request, revision = revision + 1
            WHERE id = :id AND user_id = :user
        """, id=application, resume=resume, answers=answers,
            content=json.dumps(content, ensure_ascii=False), request=request)
        purge = "DELETE FROM career_application_file WHERE application_id = :id AND retained = FALSE"
        ids = _file_ids(content)
        if ids:
            await self.db.execute(text(purge + " AND id NOT IN :files").bindparams(bindparam("files", expanding=True)),
                                  {"id": application, "files": ids})
        else:
            await self.execute(purge, id=application)
        updated = await self.owned(application)
        await self.record_materials_update(updated)
        return await self.workspace_state(updated)

    async def stored_file(self, application: str, file_id: str):
        return (await self.execute("""
            SELECT file_name AS name, content FROM career_application_file WHERE application_id = :id AND id = :file
        """, id=application, file=file_id)).one_or_none()

    async def store_files(self, application: str, content: dict, uploads: dict) -> None:
        ids = _validate_content(content)
        if set(uploads) - set(ids):
            raise BizError("上传文件与草稿中的附件不匹配", code=400)
        for key, (original, value) in uploads.items():
            name = (original or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
            if not name or len(name) > 255 or re.search(r"[\x00-\x1f\x7f-\x9f]", name):
                raise BizError("附件文件名无效", code=400)
            if not value or len(value) > MAX_FILE_BYTES:
                raise BizError("请添加不超过 10 MB 的有效文件", code=400)
            extension = name.rsplit(".", 1)[-1].lower()
            if extension not in SIGNATURES:
                raise BizError("附件支持 PDF、JPG 和 PNG", code=400)
            if not value.startswith(SIGNATURES[extension]):
                raise BizError("附件内容与文件格式不匹配", code=400)
            existing = await self.stored_file(application, key)
            if existing is not None:
                if (existing.name, existing.content) != (name, value):
                    raise conflict("文件编号已使用，请重新添加附件")
            else:
                await self.execute("""
                    INSERT INTO career_application_file (application_id, id, file_name, file_size, content)
                    VALUES (:id, :file, :name, :size, :data)
                """, id=application, file=key, name=name, size=len(value), data=value)
        if len(await self.files(application, ids)) != len(ids):
            raise BizError("找不到所选文件，请重新添加附件", code=400)

    async def materials(self, app: dict) -> dict:
        resume = await self.resumes.find(app["resumeId"]) if app["resumeId"] else None
        app_id = app["id"]
        content, _ = await self.raw_workspace(app_id)
        files = await self.files(app_id, _file_ids(content))
        if files:
            await self.db.execute(text("""
                UPDATE career_application_file SET retained = TRUE WHERE application_id = :id AND id IN :files
            """).bindparams(bindparam("files", expanding=True)), {"id": app_id, "files": [file["id"] for file in files]})
        return {
            "resumeId": app["resumeId"], "resumeTitle": resume["jobTitle"] if resume else None,
            "resumeCreatedAt": resume["createdAt"] if resume else None, "answers": app["answers"],
            "workspace": {"content": content, "files": files},
        }

    async def record_materials_update(self, app: dict) -> None:
        if app["stage"] != "DRAFT":
            await self.event(app["id"], app["revision"], app["stage"], materials=await self.materials(app),
                             kind="MATERIALS_UPDATED")
