"""Budgeted career prompts and references to the owner's original documents."""
import asyncio
import json
import re
from uuid import UUID

from app.core.exceptions import BizError
from app.core.rag.chunker import count_tokens
from app.db.postgres import SessionLocal
from app.services.document_service import DocumentService

CONTEXT_TOKENS = 9000
CATALOG_TOKENS = 4000


class CareerSourceUnavailable(Exception):
    """A selected source is absent, unreadable, or no longer matches the checkpoint."""


class CareerContextTooLarge(Exception):
    """Required fields exceed the prompt budget."""


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def excerpt(text: str, limit: int) -> str:
    if count_tokens(text) <= limit:
        return text
    left, right = 0, len(text)
    while right - left > 1:
        midpoint = (left + right) // 2
        if count_tokens(text[:midpoint]) <= limit - 8:
            left = midpoint
        else:
            right = midpoint
    return text[:left] + " […]"


async def read_source(user_id: UUID, document_id: str) -> dict:
    try:
        async with SessionLocal() as session:
            source = await DocumentService(session).preview(user_id, UUID(document_id), include_revision=True)
    except (BizError, ValueError) as error:
        raise CareerSourceUnavailable() from error
    if not source["content"]:
        raise CareerSourceUnavailable()
    return source


def source_excerpt(text: str, job: dict) -> str:
    blocks = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(blocks) < 2:
        blocks = [part.strip() for part in text.splitlines() if part.strip()]
    query = " ".join(job.get(key, "") for key in ("title", "skills", "jd"))
    terms = set(re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}", excerpt(query, 1200).lower()))
    if not blocks:
        return excerpt(text, 500)
    terms.update(word[index:index + 2] for word in list(terms) if not word.isascii()
                 for index in range(len(word) - 1))
    def relevance(item):
        block = item[1].lower()
        return -sum(term in block for term in terms)

    ranked = sorted(enumerate(blocks), key=relevance)
    return excerpt("\n\n".join(excerpt(block, 120) for _, block in ranked[:4]), 500)


def prepare_context(raw: dict, saved: dict | None, skill: dict, sources: list[dict], source_tokens: int) -> dict:
    if saved is not None:
        revisions = {source["id"]: source["revision"] for source in sources}
        if len(revisions) != len(saved["references"]) or any(
            revisions.get(ref["id"]) != ref["revision"] for ref in saved["references"]
        ):
            raise CareerSourceUnavailable()
        return saved

    job = raw["job"]
    payload = {**raw, "job": {**job, "jd": excerpt(job.get("jd", ""), 1800)}}
    payload.pop("documentIds", None)
    payload.pop("skillId", None)
    if skill.get("selected"):
        payload["skillGuidance"] = skill["selected"]["guidance"]
    feedback = payload.pop("feedback", [])
    facts = payload.pop("experiences", [])
    plan = payload.get("plan")
    if plan:
        payload["plan"] = {"analysis": excerpt(plan.get("analysis", ""), 550), "steps": plan.get("steps", [])[:4]}
    if payload.get("preferences"):
        notes = payload["preferences"]
        payload["preferences"] = {**notes, "notes": excerpt(notes["notes"], 500)}

    references = [
        {"id": source["id"], "title": source["file_name"], "revision": source["revision"]}
        for source in sources
    ]
    for field, values, limit in (("experiences", facts, 500), ("feedback", feedback, 650)):
        if values:
            payload[field] = []
        for value in values:
            clipped = {key: excerpt(item, limit) if isinstance(item, str) else item for key, item in value.items()}
            if count_tokens(encode(payload)) + count_tokens(encode(clipped)) + source_tokens + 48 > CONTEXT_TOKENS:
                break
            payload[field].append(clipped)
    if count_tokens(encode(payload)) + source_tokens + 24 > CONTEXT_TOKENS:
        raise CareerContextTooLarge()
    return {"payload": payload, "references": references, "skill": skill}


def document_excerpts(sources: list[dict], job: dict) -> list[dict]:
    return [
        {"reference": index + 1, "title": source["file_name"], "excerpt": source_excerpt(source["content"], job)}
        for index, source in enumerate(sources)
    ]


async def assemble_context(user_id: UUID, raw: dict, saved: dict | None, skill: dict) -> tuple[dict, dict]:
    sources = await asyncio.gather(*(read_source(user_id, item) for item in raw.get("documentIds", [])))
    documents = document_excerpts(sources, raw["job"])
    prepared = prepare_context(raw, saved, skill, sources, count_tokens(encode(documents)))
    payload = {**prepared["payload"], "documents": documents}
    if count_tokens(encode(payload)) > CONTEXT_TOKENS:
        raise CareerContextTooLarge()
    return prepared, payload


def compact_catalog(catalog: list[dict]) -> list[dict]:
    compact = []
    for question in catalog:
        item = {key: question[key] for key in ("id", "version", "topic", "prompt", "kind") if key in question}
        if "prompt" in item:
            item["prompt"] = excerpt(item["prompt"], 180)
        if count_tokens(encode([*compact, item])) > CATALOG_TOKENS:
            break
        compact.append(item)
    return compact
