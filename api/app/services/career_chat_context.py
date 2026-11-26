"""Rebuild job-scoped chat context from the current, user-owned messages."""
import json
import re
from contextlib import aclosing

from app.core.rag.chunker import count_tokens
from app.services.career_question_catalog import skills_in

HISTORY_TOKENS = 4200
SUMMARY_TOKENS = 1100
CURRENT_TOKENS = 6000
RECENT_MESSAGES = 8
_CHANGING_FIELDS = {
    "复习顺序": re.compile(r"^(?:把)?复习顺序(?:改为|是|调整为|设为)"),
    "截止时间": re.compile(r"^(?:把)?(?:截止(?:时间|日期)|最后期限)(?:改为|调整为|定为|是|到|为)"),
    "求职目标": re.compile(
        r"^(?:我(?:的)?(?:实习方向|求职目标)(?:是|改为|为)|现在(?:我)?决定(?:重点)?投递)"
    ),
}
_SENTENCES = re.compile(r"(?<=[。！？；])|\n")
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


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCES.split(text[:6000]) if part.strip()]


def constraint_field(text: str) -> str | None:
    for field, pattern in _CHANGING_FIELDS.items():
        if pattern.search(text.strip(" \t-•")):
            return field
    return None


def update_constraints(current: dict, message) -> None:
    if message.role != "user":
        return
    meta = getattr(message, "meta_data", None) or {}
    statements = meta.get("career_constraints")
    if not isinstance(statements, dict):
        statements = extract_constraints(message.content)
    for field, value in statements.items():
        if field in _CHANGING_FIELDS and isinstance(value, str):
            current[field] = (str(message.id), value)


def extract_constraints(text: str) -> dict[str, str]:
    result = {}
    for sentence in sentences(text):
        field = constraint_field(sentence)
        if field:
            result[field] = sentence
    return result


def known_constraint_fields() -> set[str]:
    return set(_CHANGING_FIELDS)


async def latest_constraints(messages) -> dict:
    current: dict = {}
    async with aclosing(messages) as history:
        async for message in history:
            found: dict = {}
            update_constraints(found, message)
            for field, value in found.items():
                current.setdefault(field, value)
            if len(current) == len(_CHANGING_FIELDS):
                break
    return current


def render_constraints(current: dict) -> str:
    return json.dumps([
        {"field": field, "message_id": source, "statement": clip(statement, 100)}
        for field, (source, statement) in sorted(current.items())
    ], ensure_ascii=False) if current else ""


def effective_content(message, current: dict) -> str:
    if message.role != "user":
        return message.content
    removed = False
    kept = []
    for sentence in sentences(message.content):
        field = constraint_field(sentence)
        if field and current.get(field) != (str(message.id), sentence):
            removed = True
        else:
            kept.append(sentence)
    return "\n".join(kept) if removed else message.content


def turn_content(text: str, attachments: list[dict], budget: int) -> str:
    question = clip(text, budget - 16)
    remaining = budget - count_tokens(question) - 16
    visible = attachments[:8]
    if not visible or remaining < 48:
        return question
    size = max(1, remaining // len(visible) - 4)
    sources = "\n\n".join(
        clip(f"资料 {item.get('file_name', '')}\n{item.get('text', '')}", size) for item in visible
    )
    return f"{clip(sources, remaining)}\n\n用户提问\n{question}"


def fit_turn(window: int, output_reserve: int, system: str, tools: list, text: str, attachments: list, history: list):
    budget = window - output_reserve - count_tokens(system) - tool_schema_tokens(tools) - 512
    if budget < 64:
        return "", []
    question = turn_content(text, attachments, min(CURRENT_TOKENS, budget))
    remaining = min(HISTORY_TOKENS, budget - count_tokens(question))
    kept = []
    # Only take complete user/assistant turns from the newest end of the history.
    end = len(history)
    while end > 1:
        start = end - 1
        while start >= 0 and history[start].type != "human":
            start -= 1
        if start < 0:
            break
        group = history[start:end]
        cost = sum(count_tokens(message.content) + 8 for message in group)
        if cost > remaining:
            break
        kept[:0] = group
        remaining -= cost
        end = start
    return question, kept


def tool_schema_tokens(tools: list) -> int:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    return sum(count_tokens(json.dumps(convert_to_openai_tool(tool), ensure_ascii=False)) for tool in tools)


def message_cost(message) -> int:
    content = message.content if isinstance(message.content, str) else json.dumps(message.content, ensure_ascii=False)
    calls = getattr(message, "tool_calls", [])
    return count_tokens(content) + (count_tokens(json.dumps(calls, ensure_ascii=False)) if calls else 0) + 16


def fit_agent_round(window: int, output_reserve: int, schemas: int, messages: list, turn_index: int) -> list | None:
    """Fit a tool loop round without breaking current tool-call/result pairs."""
    budget = window - output_reserve - schemas - 512
    system_end = 1 if messages[0].type == "system" else 0
    history = messages[system_end:turn_index]
    prefix = [*messages[:system_end], messages[turn_index]]
    turn = messages[turn_index + 1:]
    base = sum(map(message_cost, prefix))
    results = [index for index, message in enumerate(turn) if message.type in {"tool", "human"}]
    if results:
        fixed = base + sum(message_cost(message) for index, message in enumerate(turn) if index not in results)
        # Reserve tool evidence before older chat turns and cap any individual result.
        share = (budget - fixed - 16 * len(results)) // len(results)
        if share < 24:
            return None
        for index in results:
            message = turn[index]
            turn[index] = message.model_copy(update={"content": clip(str(message.content), min(1600, share))})
    remaining = budget - base - sum(map(message_cost, turn))
    if remaining < 0:
        return None
    # History can arrive read-truncated. Keep complete turns from the newest end.
    start = len(history)
    while start:
        head = start - 1
        while head >= 0 and history[head].type != "human":
            head -= 1
        if head < 0 or head == start - 1:
            break
        remaining -= sum(map(message_cost, history[head:start]))
        if remaining < 0:
            break
        start = head
    return [*prefix[:-1], *history[start:], prefix[-1], *turn]


def summarize(messages, current: dict | None = None, *, question: str = "") -> str:
    if current is None:
        current = {}
        for message in messages:
            update_constraints(current, message)
    candidates = []
    requested_skills = skills_in(question)
    for index, message in enumerate(messages):
        parts = sentences(effective_content(message, current))
        relevant = [part for part in parts if IMPORTANT.search(part) or CONSTRAINT.search(part)]
        for position, part in enumerate(relevant or parts[:1]):
            rank = (bool(requested_skills & skills_in(part)), message.role == "user", bool(CONSTRAINT.search(part)),
                    bool(IMPORTANT.search(part)), index, -position)
            candidates.append((rank, index, message, part))
    ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
    chosen: dict[int, dict] = {}
    seen = set()
    for _, index, message, excerpt in ranked:
        clipped = clip(excerpt, 100)
        key = (message.role, clipped)
        if key in seen:
            continue
        previous = chosen.get(index)
        value = f"{previous['excerpt']}\n{clipped}" if previous else clipped
        entry = {"message_id": str(message.id), "speaker": message.role, "excerpt": value}
        candidate = {**chosen, index: entry}
        encoded = json.dumps(list(candidate.values()), ensure_ascii=False)
        if count_tokens(encoded) <= SUMMARY_TOKENS:
            chosen = candidate
            seen.add(key)
    return json.dumps([chosen[index] for index in sorted(chosen)], ensure_ascii=False) if chosen else ""
