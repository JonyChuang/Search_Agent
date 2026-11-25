"""Resume versions and revision-protected, user-confirmed profile evidence."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import timezone
from io import BytesIO
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import text

from app.core.exceptions import BizError
from app.services.career_queue import conflict
from app.services.career_records import CareerRecords

EMPTY = {"name": "", "phone": "", "email": "", "targetRole": "", "skills": "", "photo": None,
         "showPhoto": True, "template": "classic", "entries": []}
SELECT = """
    SELECT id, job_id AS jobId, company, job_title AS jobTitle, evidence_json AS evidence,
        created_at AS createdAt, profile_revision AS profileRevision, design_json->>'$.template' AS template
    FROM career_resume_version WHERE user_id = :user
"""


def _resume(row) -> dict:
    return dict(row, evidence=json.loads(row["evidence"]), createdAt=row["createdAt"].replace(tzinfo=timezone.utc))


def _validate_photo(value: str) -> None:
    header, _, encoded = value.partition(",")
    file_type = {"data:image/jpeg;base64": "JPEG", "data:image/png;base64": "PNG"}.get(header)
    if file_type:
        try:
            with Image.open(BytesIO(base64.b64decode(encoded, validate=True)), formats=[file_type]) as image:
                if max(image.size) <= 1024:
                    image.load()
                    return
        except (binascii.Error, OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            pass
    raise BizError("简历照片无效，请重新选择 JPG 或 PNG", code=400)


class CareerResumes:
    def __init__(self, records: CareerRecords):
        self.records = records
        self.user = records.user
        self.db = records.db

    async def execute(self, sql, **values):
        return await self.db.execute(text(sql), {"user": self.user, **values})

    async def find(self, resume_id: str, *, request=False) -> dict | None:
        where = " AND request_id = :id" if request else " AND id = :id"
        row = (await self.execute(SELECT + where, id=resume_id)).mappings().one_or_none()
        return _resume(row) if row is not None else None

    async def list(self) -> list[dict]:
        return [_resume(row) for row in (await self.execute(SELECT + " ORDER BY created_at DESC, id DESC")).mappings()]

    async def profile(self, *, lock=False) -> dict:
        sql = "SELECT revision, content_json FROM career_resume_profile WHERE user_id = :user"
        row = (await self.execute(sql + (" FOR UPDATE" if lock else ""))).one_or_none()
        return {"revision": row.revision, "content": json.loads(row.content_json)} if row else {"revision": 0, "content": EMPTY}

    async def save_profile(self, revision: int, content: dict, confirm: str | None) -> dict:
        ids = [entry["id"] for entry in content["entries"]]
        if len(set(ids)) != len(ids):
            raise BizError("简历经历不能重复", code=400)
        if any(entry["endMonth"] and entry["endMonth"] < entry["startMonth"] for entry in content["entries"]):
            raise BizError("结束月份应晚于或等于起始月份", code=400)
        if content["photo"] is not None:
            _validate_photo(content["photo"])
        await self.execute("""
            INSERT INTO career_resume_profile (user_id, revision, content_json) VALUES (:user, 0, :content)
            ON DUPLICATE KEY UPDATE user_id = user_id
        """, content=json.dumps(EMPTY, ensure_ascii=False))
        current = await self.profile(lock=True)
        same = current["revision"] > 0 and current["content"] == content
        if not same and current["revision"] != revision:
            raise conflict("简历资料已在其他页面更新，请重新打开后再编辑")
        if confirm:
            await self.confirm_experience(content, confirm)
        if same:
            return current
        await self.execute("""
            UPDATE career_resume_profile SET content_json = :content, revision = :revision WHERE user_id = :user
        """, content=json.dumps(content, ensure_ascii=False), revision=revision + 1)
        return {"revision": revision + 1, "content": content}

    async def confirm_experience(self, content: dict, confirm: str) -> None:
        entry = next((entry for entry in content["entries"] if entry["id"] == confirm), None)
        if entry is None:
            raise BizError("请先填写要确认的经历", code=400)
        if entry["kind"] == "award" or not entry["description"].strip():
            raise BizError("请为教育、项目、科研或实习经历填写实际内容", code=400)
        description = entry["description"]
        if entry["role"].strip():
            description = f"担任角色：{entry['role']}\n{description}"
        if len(description) > 12000:
            raise BizError("经历描述与担任角色合计最多 12000 字", code=400)
        values = {
            "type": entry["kind"], "title": entry["title"], "description": description, "confirmed": True,
            **{key: entry[key] if (entry[key] or "").strip() else None
               for key in ("organization", "startMonth", "endMonth", "sourceNote")},
        }
        await self.execute("""
            INSERT INTO career_experience
                (user_id, id, type, title, organization, start_month, end_month, description, source_note, confirmed)
            VALUES (:user, :id, :type, :title, :organization, :startMonth, :endMonth, :description, :sourceNote, TRUE)
            ON DUPLICATE KEY UPDATE id = id
        """, id=confirm, **values)
        await self.records.experiences().update(confirm, values)

    async def create(self, request: str, job_id: str, experience_ids: list[str]) -> dict:
        existing = await self.find(request, request=True)
        if existing is None:
            job = await self.records.jobs().get(job_id)
            if len(set(experience_ids)) != len(experience_ids):
                raise BizError("经历不能重复", code=400)
            evidence = [await self.records.experiences().get(record) for record in experience_ids]
            if any(not item["confirmed"] for item in evidence):
                raise BizError("简历只能使用已确认的经历", code=400)
            await self._insert(request, job_id, job["company"], job["title"], evidence, None, None)
            existing = await self.find(request, request=True)
        if existing is None or existing["profileRevision"] is not None or existing["jobId"] != job_id \
                or [item["id"] for item in existing["evidence"]] != experience_ids:
            raise conflict("版本编号已用于另一份简历")
        return existing

    async def compose(self, request: str, job_id: str | None, revision: int) -> dict:
        saved = await self.find(request, request=True)
        if saved is None:
            profile = await self.profile()
            if profile["revision"] != revision:
                saved = await self.find(request, request=True)
                if saved is None:
                    raise conflict("简历资料已更新，请核对后重新生成")
            else:
                content = dict(profile["content"])
                if not content["name"].strip() or not content["entries"]:
                    raise BizError("请填写姓名并添加至少一条经历", code=400)
                job = await self.records.jobs().get(job_id) if job_id else None
                title = job["title"] if job else content["targetRole"].strip() or "通用简历"
                if not content["showPhoto"]:
                    content["photo"] = None
                if job and not content["targetRole"].strip():
                    content["targetRole"] = title
                await self._insert(request, job_id, job["company"] if job else "", title, [], revision, content)
                saved = await self.find(request, request=True)
        if saved is None or saved["jobId"] != job_id or saved["profileRevision"] != revision:
            raise conflict("版本编号已用于另一份简历")
        return saved

    async def _insert(self, request, job_id, company, title, evidence, revision, design):
        await self.execute("""
            INSERT INTO career_resume_version
                (id, user_id, job_id, company, job_title, request_id, evidence_json, profile_revision, design_json)
            VALUES (:id, :user, :job, :company, :title, :request, :evidence, :revision, :design)
            ON DUPLICATE KEY UPDATE id = id
        """, id=str(uuid4()), request=request, job=job_id, company=company, title=title,
            evidence=json.dumps(evidence, ensure_ascii=False), revision=revision,
            design=json.dumps(design, ensure_ascii=False) if design is not None else None)

    async def composition(self, resume_id: str) -> dict:
        value = (await self.execute("""
            SELECT design_json FROM career_resume_version WHERE user_id = :user AND id = :id
        """, id=resume_id)).scalar_one_or_none()
        if value is None:
            raise BizError("找不到该简历版本", code=404, status_code=404)
        return json.loads(value)
