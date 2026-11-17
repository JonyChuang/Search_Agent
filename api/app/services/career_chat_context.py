"""Rebuild job-scoped chat context from the current, user-owned messages."""
import json
import re

from app.core.rag.chunker import count_tokens

HISTORY_TOKENS = 4200
SUMMARY_TOKENS = 1100
CURRENT_TOKENS = 6000
RECENT_MESSAGES = 8
IMPORTANT = re.compile(r"确认|要求|目标|截止|限制|只用|保留|偏好|注意|负责|证据|真实|阶段")
CONSTRAINT = re.compile(r"确认|只用|请勿|不要|务必|截止时间|限制|目标是|必须|改为")


def clip(text: str, tokens: int) -> str:
    if count_tokens(text) <= tokens:
        return text
    low, high = 0, len(text)
    while low + 1 < high:
        middle = (low + high) // 2
        if count_tokens(text[:middle] + "…") <= tokens:
            low = middle
        else:
            high = middle
    return text[:low] + "…" if low else ""


def turn_content(text: str, attachments: list[dict], budget: int) -> str:
    question = clip(text, budget - 16)
    remaining = budget - count_tokens(question) - 16
    visible = attachments[:8]
    if not visible or remaining < 48:
        return question
    size = max(1, remaining // len(visible) - 4)
    sources = "\n\n".join(clip(f"资料 {item['file_name']}\n{item.get('text', '')}", size) for item in visible)
    return f"{clip(sources, remaining)}\n\n用户提问\n{question}"


def summarize(messages) -> str:
    if not messages:
        return ""
    ranked = sorted(enumerate(messages), key=lambda row: (
        row[1].role == "user", bool(CONSTRAINT.search(row[1].content[:4000])),
        bool(IMPORTANT.search(row[1].content[:4000])), row[0],
    ), reverse=True)
    chosen = []
    seen = set()
    for index, message in ranked:
        sentences = [part.strip() for part in re.split(r"(?<=[。！？])|\n", message.content[:6000]) if part.strip()]
        if not sentences:
            continue
        excerpt = next((part for part in sentences if CONSTRAINT.search(part)),
                       next((part for part in sentences if IMPORTANT.search(part)), sentences[0]))
        clipped = clip(excerpt, 100)
        key = (message.role, clipped)
        if key in seen:
            continue
        entry = {"message_id": str(message.id), "speaker": message.role, "excerpt": clipped}
        encoded = json.dumps([item for _, item in [*chosen, (index, entry)]], ensure_ascii=False)
        if count_tokens(encoded) <= SUMMARY_TOKENS:
            chosen.append((index, entry))
            seen.add(key)
    return json.dumps([item for _, item in sorted(chosen)], ensure_ascii=False) if chosen else ""
