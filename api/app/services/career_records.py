"""User-owned career records shared by the API and model workflows."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.exceptions import BizError

JOB_FIELDS = {
    "company": "company", "title": "title", "location": "location",
    "description": "description", "sourceName": "source_name", "sourceUrl": "source_url",
    "sourcedOn": "sourced_on", "skills": "skills",
}
EXPERIENCE_FIELDS = {
    "type": "type", "title": "title", "organization": "organization",
    "startMonth": "start_month", "endMonth": "end_month", "description": "description",
    "sourceNote": "source_note", "confirmed": "confirmed",
}


class CareerRecords:
    def __init__(self, db: AsyncConnection, user: str):
        self.db = db
        self.user = user

    async def _execute(self, sql: str, **values):
        return await self.db.execute(text(sql), {"user": self.user, **values})

    async def profile(self) -> dict | None:
        row = (await self._execute("""
            SELECT target_role AS targetRole, graduation_month AS graduationMonth, preferences
            FROM career_profile WHERE user_id = :user
        """)).mappings().one_or_none()
        return dict(row) if row is not None else None

    async def save_profile(self, profile: dict) -> dict:
        await self._execute("""
            INSERT INTO career_profile (user_id, target_role, graduation_month, preferences)
            VALUES (:user, :targetRole, :graduationMonth, :preferences) AS incoming
            ON DUPLICATE KEY UPDATE target_role = incoming.target_role,
                graduation_month = incoming.graduation_month, preferences = incoming.preferences
        """, **profile)
        return profile

    async def active_job(self) -> dict:
        job_id = (await self._execute(
            "SELECT active_job_id FROM career_profile WHERE user_id = :user"
        )).scalar_one_or_none()
        return {"jobId": job_id}

    async def select_job(self, job_id: str | None) -> dict:
        if job_id is None:
            await self._execute(
                "UPDATE career_profile SET active_job_id = NULL WHERE user_id = :user"
            )
        else:
            await self._execute("""
                INSERT INTO career_profile (user_id, active_job_id)
                SELECT user_id, id FROM career_job WHERE user_id = :user AND id = :id
                ON DUPLICATE KEY UPDATE active_job_id = :id
            """, id=job_id)
            if (await self.active_job())["jobId"] != job_id:
                self.jobs().missing()
        return {"jobId": job_id}

    def jobs(self) -> "OwnedRecords":
        return OwnedRecords(self, "career_job", JOB_FIELDS, "岗位不存在")

    def experiences(self) -> "OwnedRecords":
        return OwnedRecords(self, "career_experience", EXPERIENCE_FIELDS, "经历不存在")

    async def job_notes(self, job: str) -> dict:
        await self.jobs().get(job)
        row = (await self._execute("""
            SELECT revision, notes FROM career_job_memory WHERE user_id = :user AND job_id = :job
        """, job=job)).mappings().one_or_none()
        return dict(row) if row is not None else {"revision": 0, "notes": None}

    async def save_job_notes(self, job: str, revision: int, notes: str | None) -> dict:
        await self.jobs().get(job, lock=True)
        notes = notes.strip() or None if notes else None
        if revision == 0:
            await self._execute("""
                INSERT INTO career_job_memory (user_id, job_id, revision)
                VALUES (:user, :job, 0) ON DUPLICATE KEY UPDATE revision = revision
            """, job=job)
        changed = await self._execute("""
            UPDATE career_job_memory SET notes = :notes, revision = revision + 1,
                updated_at = CURRENT_TIMESTAMP(6)
            WHERE user_id = :user AND job_id = :job AND revision = :revision
        """, job=job, revision=revision, notes=notes)
        if changed.rowcount != 1:
            raise BizError("备考偏好已更新，请重新读取后再保存", code=409, status_code=409)
        return {"revision": revision + 1, "notes": notes}


class OwnedRecords:
    def __init__(self, owner: CareerRecords, table: str, fields: dict[str, str], not_found: str):
        # These identifiers come exclusively from the server declarations above.
        self.owner = owner
        self.table = table
        self.fields = fields
        self.not_found = not_found
        columns = ", ".join(f"{col} AS {key}" for key, col in fields.items())
        self.select = f"SELECT id, {columns} FROM {table} WHERE user_id = :user"

    def missing(self) -> None:
        raise BizError(self.not_found, code=404, status_code=404)

    def _entry(self, row) -> dict:
        entry = dict(row)
        if "confirmed" in self.fields:
            entry["confirmed"] = bool(entry["confirmed"])
        return entry

    async def all(self) -> list[dict]:
        rows = await self.owner._execute(self.select + " ORDER BY created_at DESC, id DESC")
        return [self._entry(row) for row in rows.mappings()]

    async def get(self, record_id: str, *, lock: bool = False) -> dict:
        query = self.select + " AND id = :id" + (" FOR UPDATE" if lock else "")
        row = (await self.owner._execute(query, id=record_id)).mappings().one_or_none()
        if row is None:
            self.missing()
        return self._entry(row)

    async def create(self, values: dict) -> dict:
        record_id = str(uuid4())
        columns = ", ".join(self.fields.values())
        placeholders = ", ".join(f":{key}" for key in self.fields)
        await self.owner._execute(
            f"INSERT INTO {self.table} (user_id, id, {columns}) VALUES (:user, :id, {placeholders})",
            id=record_id, **values,
        )
        return await self.get(record_id)

    async def update(self, record_id: str, values: dict) -> dict:
        assignments = ", ".join(f"{col} = :{key}" for key, col in self.fields.items())
        await self.owner._execute(
            f"UPDATE {self.table} SET {assignments} WHERE user_id = :user AND id = :id",
            id=record_id, **values,
        )
        return await self.get(record_id)

    async def delete(self, record_id: str) -> None:
        result = await self.owner._execute(
            f"DELETE FROM {self.table} WHERE user_id = :user AND id = :id", id=record_id,
        )
        if result.rowcount != 1:
            self.missing()
