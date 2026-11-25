"""Reminder state and fenced notification delivery."""

import asyncio
import logging
from datetime import timezone
from uuid import UUID

from sqlalchemy import text

from app.core.exceptions import BizError
from app.db.career import career_transaction
from app.db.postgres import SessionLocal
from app.services.career_queue import conflict
from app.services.career_records import CareerRecords
from app.services.notify_service import NotifyService

logger = logging.getLogger(__name__)
TITLES = {"REVIEW": "复习提醒", "INTERVIEW": "面试提醒", "APPLICATION": "投递截止提醒"}
SELECT = """
    SELECT id, job_id AS jobId, type, title, due_at AS dueAt, status, revision,
        external_delivery AS externalDelivery, delivery_state AS deliveryState,
        (status = 'PENDING' AND due_at <= CURRENT_TIMESTAMP(6)) AS due
    FROM career_reminder WHERE user_id = :user
"""


async def push_reminder(user: UUID, reminder_type: str) -> int:
    async with SessionLocal() as session:
        return await NotifyService(session).push_to_user(
            user, TITLES[reminder_type], "你的求职提醒已到时间，请打开计划与提醒查看。",
        )


def _view(row) -> dict:
    return dict(row, dueAt=row["dueAt"].replace(tzinfo=timezone.utc),
                due=bool(row["due"]), externalDelivery=bool(row["externalDelivery"]))


class CareerReminders:
    def __init__(self, records: CareerRecords):
        self.records = records
        self.db = records.db
        self.user = records.user

    async def execute(self, sql, **values):
        return await self.db.execute(text(sql), {"user": self.user, **values})

    async def list(self, job: str | None):
        rows = await self.execute(SELECT + """
            AND (:job IS NULL OR job_id = :job)
            ORDER BY (status = 'PENDING') DESC, due_at ASC, id ASC LIMIT 100
        """, job=job)
        return [_view(row) for row in rows.mappings()]

    async def due_count(self) -> int:
        return (await self.execute("""
            SELECT COUNT(*) FROM career_reminder WHERE user_id = :user AND status = 'PENDING'
                AND due_at <= CURRENT_TIMESTAMP(6)
        """)).scalar_one()

    async def get(self, reminder_id: str) -> dict:
        row = (await self.execute(SELECT + " AND id = :id", id=reminder_id)).mappings().one_or_none()
        if row is None:
            raise BizError("提醒不存在", code=404, status_code=404)
        return _view(row)

    async def save(self, reminder_id: str, reminder: dict, revision: int | None = None) -> dict:
        if revision is not None:
            await self.get(reminder_id)
        if reminder["jobId"]:
            await self.records.jobs().get(reminder["jobId"], lock=True)
        values = {**reminder, "id": reminder_id,
                  "dueAt": reminder["dueAt"].astimezone(timezone.utc).replace(tzinfo=None),
                  "delivery": "READY" if reminder["externalDelivery"] else "IN_APP"}
        if revision is None:
            await self.execute("""
                INSERT INTO career_reminder (id, user_id, job_id, type, title, due_at, external_delivery, delivery_state)
                VALUES (:id, :user, :jobId, :type, :title, :dueAt, :externalDelivery, :delivery)
                ON DUPLICATE KEY UPDATE id = id
            """, **values)
            row = await self.get(reminder_id)
            if any(row[key] != reminder[key] for key in reminder):
                raise conflict("此编号已用于另一条提醒")
            return row
        result = await self.execute("""
            UPDATE career_reminder SET job_id = :jobId, type = :type, title = :title,
                delivery_state = CASE WHEN delivery_state IN ('SENT', 'UNDELIVERED') AND due_at = :dueAt
                    THEN delivery_state ELSE :delivery END,
                due_at = :dueAt, revision = revision + 1, external_delivery = :externalDelivery, delivery_started_at = NULL
            WHERE id = :id AND user_id = :user AND status = 'PENDING' AND revision = :revision
                AND delivery_state NOT IN ('SENDING', 'UNKNOWN')
                AND (delivery_state NOT IN ('SENT', 'UNDELIVERED') OR due_at = :dueAt OR :dueAt > CURRENT_TIMESTAMP(6))
        """, **values, revision=revision)
        if result.rowcount != 1:
            raise conflict("提醒已更新，请刷新后重试")
        return await self.get(reminder_id)

    async def change(self, reminder_id: str, status: str, revision: int) -> dict:
        row = await self.get(reminder_id)
        if row["status"] == status and row["revision"] == revision + 1:
            return row
        changed = await self.execute("""
            UPDATE career_reminder SET status = :status, revision = revision + 1
            WHERE id = :id AND user_id = :user AND status = 'PENDING' AND revision = :revision
        """, id=reminder_id, status=status, revision=revision)
        if changed.rowcount != 1:
            raise conflict("提醒已更新，请刷新后重试")
        return await self.get(reminder_id)


async def deliver_reminders() -> None:
    async with career_transaction() as db:
        await db.execute(text("""
            UPDATE career_reminder SET delivery_state = 'UNKNOWN'
            WHERE delivery_state = 'SENDING' AND delivery_started_at < CURRENT_TIMESTAMP - INTERVAL 2 MINUTE
        """))
        eligible = (await db.execute(text("""
            SELECT id, user_id, type, revision FROM career_reminder
            WHERE status = 'PENDING' AND delivery_state = 'READY' AND due_at <= CURRENT_TIMESTAMP(6)
            ORDER BY due_at ASC LIMIT 10
        """))).mappings().all()
    for reminder in eligible:
        async with career_transaction() as db:
            claimed = await db.execute(text("""
                UPDATE career_reminder SET delivery_state = 'SENDING', delivery_started_at = CURRENT_TIMESTAMP(6)
                WHERE id = :id AND revision = :revision AND delivery_state = 'READY' AND status = 'PENDING'
                    AND due_at <= CURRENT_TIMESTAMP(6)
            """), dict(reminder))
        if claimed.rowcount != 1:
            continue
        try:
            async with asyncio.timeout(25):
                count = await push_reminder(UUID(reminder["user_id"]), reminder["type"])
            state = "SENT" if count else "UNDELIVERED"
        except Exception as error:
            logger.warning("Career reminder %s delivery uncertain: %s", reminder["id"], type(error).__name__)
            state = "UNKNOWN"
        async with career_transaction() as db:
            await db.execute(text("""
                UPDATE career_reminder SET delivery_state = :state WHERE id = :id AND delivery_state = 'SENDING'
            """), {"id": reminder["id"], "state": state})


async def poll_reminders() -> None:
    while True:
        try:
            await deliver_reminders()
        except Exception:
            logger.exception("Career reminder poll failed")
        await asyncio.sleep(30)
