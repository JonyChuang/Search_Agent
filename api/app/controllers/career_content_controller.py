"""Curator-approved public notes and immutable versions of objective questions."""

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import md5
from typing import Annotated, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from celery.schedules import crontab
from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text

from app.config import settings
from app.controllers.career_records_controller import CareerRoute, Records
from app.core.exceptions import BizError
from app.core.response import success
from app.db.career import career_transaction
from app.services.career_queue import conflict

router = APIRouter(prefix="/career/content-review", tags=["career"], route_class=CareerRoute)
logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
SELECT = """
    SELECT id, kind, status, payload AS content, base_version AS baseVersion, revision, updated_at AS updatedAt
    FROM career_content_draft
"""
MAX_FEED_SIZE = 512 * 1024


class Content(BaseModel):
    targetId: str | None = Field(default=None, max_length=64)
    role: str = Field(max_length=24)
    topic: str | None = Field(default=None, max_length=80)
    title: str = Field(max_length=1000)
    explanation: str = Field(max_length=6000)
    company: str | None = Field(default=None, max_length=160)
    options: list[Annotated[str, StringConstraints(max_length=500)]] | None = Field(default=None, max_length=4)
    correctAnswer: str | None = Field(default=None, max_length=1)
    sourceName: str = Field(max_length=160)
    sourceUrl: str = Field(max_length=2048)
    publishedOn: date | None = None

    def clean(self) -> dict:
        value = self.model_dump(mode="json")
        for key in ("role", "topic", "title", "explanation", "company", "sourceName", "sourceUrl"):
            value[key] = (value[key] or "").strip()
        value["options"] = [item.strip() for item in value["options"] or []]
        return value


class Create(BaseModel):
    kind: Literal["NOTE", "QUESTION"]
    content: Content


class Revision(BaseModel):
    revision: int = Field(gt=0)


class Edit(Revision):
    content: Content


def web_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname and parsed.username is None:
            if not any(char.isspace() or ord(char) < 32 for char in value):
                return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except ValueError:
        pass
    return None


def _name_uuid(value: str) -> str:
    return str(UUID(bytes=md5(value.encode(), usedforsecurity=False).digest(), version=3))


def validate(kind: str, item: dict) -> None:
    if not web_url(item["sourceUrl"]) or not all(item[key] for key in ("role", "title", "explanation", "sourceName")):
        raise BizError("请补齐内容和原文来源", code=400)
    if kind == "NOTE":
        if item["targetId"] is not None or len(item["title"]) > 160 or not item["company"] or not item["publishedOn"]:
            raise BizError("公开面经需要公司、原文发布日期和不超过 160 字的标题", code=400)
    elif item["role"] not in {"backend", "algorithm", "llm"} or not item["topic"] or len(item["options"]) != 4 \
            or not all(item["options"]) or len({option.lower() for option in item["options"]}) != 4 \
            or item["correctAnswer"] not in {"A", "B", "C", "D"}:
        raise BizError("单选题需要主题、四个不同的选项以及一个正确答案", code=400)


def curators() -> set[str]:
    return {str(UUID(value.strip())) for value in settings.career_content_curators.split(",") if value.strip()}


def authorize(user: str) -> None:
    if user not in curators():
        raise BizError("只有题库维护者可以审核公开内容", code=403, status_code=403)


def _view(row) -> dict:
    return dict(row, content=json.loads(row["content"]), updatedAt=row["updatedAt"].replace(tzinfo=timezone.utc))


async def read(db: Records, draft_id: str, *, lock=False) -> dict:
    sql = SELECT + " WHERE id = :id" + (" FOR UPDATE" if lock else "")
    row = (await db.db.execute(text(sql), {"id": draft_id})).mappings().one_or_none()
    if row is None:
        raise BizError("内容草稿不存在", code=404, status_code=404)
    return _view(row)


def require_revision(draft: dict, revision: int) -> None:
    if draft["status"] != "DRAFT" or draft["revision"] != revision:
        raise conflict("此草稿已变化，请重新读取")


@router.get("/access")
async def access(db: Records):
    return success(db.user in curators())


@router.get("")
async def drafts(db: Records, status: str = "DRAFT", page: int = 1):
    authorize(db.user)
    if status not in {"DRAFT", "PUBLISHED", "DISMISSED"} or not 1 <= page <= 2147483647:
        raise BizError("审核筛选无效", code=400)
    rows = await db.db.execute(text(SELECT + """
        WHERE status = :status ORDER BY updated_at DESC, id DESC LIMIT 21 OFFSET :offset
    """), {"status": status, "offset": (page - 1) * 20})
    items = [_view(row) for row in rows.mappings()]
    return success({"items": items[:20], "hasMore": len(items) > 20})


@router.post("")
async def create(body: Create, db: Records):
    authorize(db.user)
    item = body.content.clean()
    validate(body.kind, item)
    base = None
    if body.kind == "QUESTION" and item["targetId"] is not None:
        base = (await db.db.execute(text("""
            SELECT MAX(version) FROM career_question_version WHERE id = :question
        """), {"question": item["targetId"]})).scalar_one()
        if base is None:
            raise BizError("找不到要修订的公开题目", code=400)
    draft_id = str(uuid4())
    await db.db.execute(text("""
        INSERT INTO career_content_draft (id, kind, payload, base_version) VALUES (:id, :kind, :item, :base)
    """), {"id": draft_id, "kind": body.kind, "item": json.dumps(item, ensure_ascii=False), "base": base})
    return success(await read(db, draft_id))


@router.put("/{draft_id}")
async def edit(draft_id: UUID, body: Edit, db: Records):
    authorize(db.user)
    draft = await read(db, str(draft_id), lock=True)
    require_revision(draft, body.revision)
    item = body.content.clean()
    if item["targetId"] != draft["content"]["targetId"]:
        raise BizError("请重新创建草稿以选择另一道题", code=400)
    validate(draft["kind"], item)
    await db.db.execute(text("""
        UPDATE career_content_draft SET payload = :item, revision = revision + 1 WHERE id = :id
    """), {"id": str(draft_id), "item": json.dumps(item, ensure_ascii=False)})
    return success(await read(db, str(draft_id)))


async def change_status(db: Records, draft_id: str, status: str) -> dict:
    await db.db.execute(text("""
        UPDATE career_content_draft SET status = :status, reviewed_by = :user, revision = revision + 1,
            published_at = IF(:status = 'PUBLISHED', CURRENT_TIMESTAMP(6), NULL) WHERE id = :id
    """), {"status": status, "user": db.user, "id": draft_id})
    return await read(db, draft_id)


@router.post("/{draft_id}/publish")
async def publish(draft_id: UUID, body: Revision, db: Records):
    authorize(db.user)
    draft = await read(db, str(draft_id), lock=True)
    if draft["status"] == "PUBLISHED" and draft["revision"] == body.revision + 1:
        return success(draft)
    require_revision(draft, body.revision)
    item = draft["content"]
    validate(draft["kind"], item)
    today = datetime.now(SHANGHAI).date()
    if draft["kind"] == "NOTE":
        url = web_url(item["sourceUrl"])
        existing = (await db.db.execute(text("""
            SELECT id FROM career_interview_note WHERE SUBSTRING_INDEX(source_url, '#', 1) = :url LIMIT 1
        """), {"url": url})).scalar_one_or_none()
        await db.db.execute(text("""
            INSERT INTO career_interview_note
                (id, role, company, title, summary, source_name, source_url, published_on, sourced_on)
            VALUES (:id, :role, :company, :title, :explanation, :sourceName, :sourceUrl, :publishedOn, :today) AS incoming
            ON DUPLICATE KEY UPDATE role = incoming.role, company = incoming.company, title = incoming.title,
                summary = incoming.summary, source_name = incoming.source_name, source_url = incoming.source_url,
                published_on = incoming.published_on, sourced_on = incoming.sourced_on
        """), {**item, "id": existing or f"managed-{_name_uuid(url)}", "today": today})
    else:
        base = draft["baseVersion"] or 0
        question = item["targetId"] if item["targetId"] is not None else f"managed-{draft_id}"
        if item["targetId"] is not None:
            # Serialize publication of multiple drafts derived from the same live version.
            await db.db.execute(text("SELECT id FROM career_task_scheduler WHERE id = 1 FOR UPDATE"))
            live = (await db.db.execute(text("""
                SELECT version FROM career_question_version WHERE id = :id ORDER BY version DESC LIMIT 1 FOR UPDATE
            """), {"id": question})).scalar_one_or_none()
            if live != base:
                raise conflict("公开题目已更新，请基于新版本重新建稿")
        await db.db.execute(text("""
            INSERT INTO career_question_version (id, version, grading_version, role, topic, prompt,
                option_a, option_b, option_c, option_d, correct_answer, explanation, source_name, source_url, sourced_on)
            VALUES (:id, :version, :version, :role, :topic, :title,
                :a, :b, :c, :d, :correctAnswer, :explanation, :sourceName, :sourceUrl, :today)
        """), {**item, "id": question, "version": base + 1, "today": today, **dict(zip("abcd", item["options"]))})
    return success(await change_status(db, str(draft_id), "PUBLISHED"))


@router.post("/{draft_id}/dismiss")
async def dismiss(draft_id: UUID, body: Revision, db: Records):
    authorize(db.user)
    draft = await read(db, str(draft_id), lock=True)
    require_revision(draft, body.revision)
    return success(await change_status(db, str(draft_id), "DISMISSED"))


def feed_urls() -> list[str]:
    urls = []
    for value in settings.career_public_note_feeds.split(","):
        if value.strip():
            url = web_url(value.strip())
            if url is None:
                raise RuntimeError("Invalid configured career feed URL")
            urls.append(url)
    return list(dict.fromkeys(urls))


@router.get("/feeds")
async def feed_count(db: Records):
    authorize(db.user)
    return success(len(feed_urls()))


@router.post("/feeds/refresh")
async def refresh(db: Records):
    authorize(db.user)
    return success(await refresh_feeds())


def publication(value: str) -> str | None:
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        try:
            return parsedate_to_datetime(value).date().isoformat()
        except (TypeError, ValueError):
            return None


async def fetch_entries(client: httpx.AsyncClient, source: str) -> list[tuple[str, dict]]:
    async with client.stream("GET", source) as reply:
        reply.raise_for_status()
        body = bytearray()
        async for part in reply.aiter_bytes():
            body.extend(part)
            if len(body) > MAX_FEED_SIZE:
                raise ValueError("Feed too large")
    # Reject DTDs and entities even in BOM/UTF-16 documents before parsing.
    if b"<!DOCTYPE" in body.replace(b"\0", b"").upper() or b"<!ENTITY" in body.replace(b"\0", b"").upper():
        raise ValueError("Unexpected feed DTD")
    root = ET.fromstring(body)
    entries = root.findall(".//{*}item")
    atom = not entries
    result = []
    for entry in (root.findall(".//{*}entry") if atom else entries)[:20]:
        link = entry.findtext("{*}link", "").strip()
        if atom:
            link = next((item.get("href", "") for item in entry.findall("{*}link")
                         if item.get("rel", "alternate") == "alternate"), "")
        title = entry.findtext("{*}title", "").strip()
        canonical = web_url(urljoin(source, link)) if link else None
        if not canonical or len(canonical) > 2048 or not title:
            continue
        date_value = publication(entry.findtext("{*}published" if atom else "{*}pubDate", "").strip())
        key = _name_uuid(f"{canonical}\n{title}\n{date_value or 'null'}")
        result.append((key, dict(Content(
            role="", topic="", title=title[:160], explanation="", company="", options=[],
            sourceName=(urlsplit(source).hostname or "")[:160], sourceUrl=canonical, publishedOn=date_value,
        ).model_dump(mode="json"))))
    return result


async def refresh_feeds() -> dict:
    succeeded, failed = 0, 0
    async with career_transaction() as connection:
        lock = (await connection.execute(text("SELECT GET_LOCK(CONCAT(DATABASE(), ':career_feeds'), 0)"))).scalar_one()
        if lock != 1:
            return {"succeeded": 0, "failed": 0, "busy": True}
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(6, connect=4)) as client:
                for url in feed_urls():
                    try:
                        async with asyncio.timeout(12):
                            items = await fetch_entries(client, url)
                        async with career_transaction() as data:
                            for key, item in items:
                                await data.execute(text("""
                                    INSERT INTO career_content_draft (id, source_key, kind, payload)
                                    VALUES (:id, :key, 'NOTE', :content) ON DUPLICATE KEY UPDATE id = id
                                """), {"id": str(uuid4()), "key": key, "content": json.dumps(item, ensure_ascii=False)})
                        succeeded += 1
                    except Exception as error:
                        logger.warning("Career feed %s failed: %s", urlsplit(url).hostname, type(error).__name__)
                        failed += 1
        finally:
            await connection.execute(text("SELECT RELEASE_LOCK(CONCAT(DATABASE(), ':career_feeds'))"))
    return {"succeeded": succeeded, "failed": failed, "busy": False}


def feed_schedule():
    configured = settings.career_public_note_refresh_cron.strip()
    if configured == "-" or not feed_urls():
        return None
    second, minute, hour, day, month, weekday = configured.lower().replace("?", "*").split()
    return crontab(minute=minute, hour=hour, day_of_month=day, month_of_year=month,
                   day_of_week=weekday.replace("7", "0")), crontab(minute=second).minute


async def poll_feeds() -> None:
    schedule = feed_schedule()
    if schedule is None:
        return
    cron, seconds = schedule
    last = None
    while True:
        now = datetime.now(SHANGHAI).replace(microsecond=0)
        if now != last and now.second in seconds and now.minute in cron.minute and now.hour in cron.hour \
                and now.day in cron.day_of_month and now.month in cron.month_of_year \
                and now.isoweekday() % 7 in cron.day_of_week:
            last = now
            try:
                await refresh_feeds()
            except Exception:
                logger.exception("Career feed refresh failed")
        await asyncio.sleep(0.5)
