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
_FIELD_ALIASES = {
    "求职目标": r"求职目标|实习方向",
    "复习顺序": r"复习顺序",
    "截止时间": r"截止时间|截止日期|最后期限",
    "意向城市": r"意向城市|求职城市|目标城市",
    "实习时长": r"实习时长|实习周期",
    "异地偏好": r"异地偏好|是否接受异地",
    "简历素材偏好": r"简历素材偏好|简历素材范围",
}
_FIELD = "|".join(f"(?:{aliases})" for aliases in _FIELD_ALIASES.values())
_UPDATE = re.compile(
    rf"^(?:(?:请|把|我的|我想将|将)\s*)*(?P<field>{_FIELD})\s*(?:调整为|改成|改为|设为|定为|是|到|为)\s*(?P<value>.+)$"
)
_CLEAR = re.compile(rf"^(?:请)?(?:取消|清除|删除)(?:我的)?(?P<field>{_FIELD})(?:的?约束|限制)?$")
_GOAL = re.compile(r"^现在(?:我)?决定(?:重点)?投递(?P<value>.+)$")
_INTENT = re.compile(r"^(?:请|帮我|给我|能否|能不能|如何|怎么|重新安排|重新制定|生成|创建|总结|解释|查询|执行|按照|根据)")
_AMBIGUOUS = re.compile(
    r"[,，]|(?:请|帮我|给我|然后|接着|并且|同时)(?=.{2,})"
    r"|(?:怎么|如何|重新安排|重新制定|重新生成|创建|执行|总结|解释|查一下)|生成(?=.{0,8}(?:计划|简历|报告))"
)
_SENTENCES = re.compile(r"(?<=[。！？；!?;])")
_CONDITIONAL = re.compile(r"如果|除非|倘若|要是|假如")
_DEADLINE_EDIT = re.compile(r"(?:改成|改为|调整为|重设|重新设为)")
_CLAUSES = re.compile(r"([，,]\s*|\s*(?:并|同时|然后|接着)(?=请|帮我|给我|重新安排|重新制定|创建|生成|查询))")
_HISTORICAL_PINNED = re.compile(rf"{_FIELD}|现在(?:我)?决定(?:重点)?投递|(?:不)?接受异地|简历(?:仅|只)用")
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
    return [part.strip() for line in text[:6000].splitlines() for part in _SENTENCES.split(line) if part.strip()]


def _constraint_change(clause: str) -> tuple[str, str | None] | None:
    if clause.rstrip().endswith(("?", "？")):
        return None
    clause = clause.strip(" \t-•").rstrip("。！!；;").strip()
    clause = re.sub(r"^确认\s*[:：]\s*", "", clause)
    match = _CLEAR.fullmatch(clause) or _UPDATE.fullmatch(clause) or _GOAL.fullmatch(clause)
    if match is None:
        if clause in {"接受异地", "不接受异地", "我接受异地", "我不接受异地"}:
            return "异地偏好", clause.removeprefix("我")
        if re.fullmatch(r"简历(?:只能使用|仅使用|只用)(?:我的)?(?:真实确认经历|已确认经历|真实经历)", clause):
            return "简历素材偏好", "仅使用已确认经历"
        return None
    parts = match.groupdict()
    alias = parts.get("field")
    field = next(key for key, aliases in _FIELD_ALIASES.items() if re.fullmatch(aliases, alias)) if alias else "求职目标"
    value = parts.get("value")
    if value is None:
        return field, None
    value = value.strip()
    if not value or len(value) > 180 or _AMBIGUOUS.search(value) or value.startswith(("什么", "多久", "哪", "多少")):
        return None
    return field, value


def _parse_sentence(sentence: str) -> tuple[dict[str, str | None], str]:
    if _CONDITIONAL.search(sentence):
        return {}, sentence
    direct = _constraint_change(sentence)
    if direct is not None:
        return dict([direct]), ""
    parts = _CLAUSES.split(sentence)
    if len(parts) == 1:
        return {}, sentence
    updates = {}
    remaining = []
    for offset in range(0, len(parts), 2):
        clause = parts[offset]
        following = parts[offset + 2].lstrip() if offset + 2 < len(parts) else ""
        change = _constraint_change(clause)
        if change is not None and (not following or _INTENT.match(following) or _constraint_change(following)):
            if (change[0] == "截止时间" and change[0] in updates and updates[change[0]] != change[1]
                    and change[1] is not None and not _DEADLINE_EDIT.search(clause)):
                return {}, sentence
            updates[change[0]] = change[1]
        else:
            if remaining:
                remaining.append(parts[offset - 1])
            remaining.append(clause)
    return (updates, "".join(remaining).strip()) if updates else ({}, sentence)


def parse_constraint_request(text: str) -> tuple[dict[str, str | None], str]:
    """Extract explicit changes, keeping the original request when splitting is uncertain."""
    updates = {}
    remainder = []
    fence = None
    for line in text.splitlines(keepends=True):
        marker = line.lstrip()[:3]
        if marker in {"```", "~~~"}:
            if fence in (None, marker):
                fence = marker if fence is None else None
            remainder.append(line)
            continue
        if fence:
            remainder.append(line)
            continue
        for sentence in _SENTENCES.split(line):
            changes, request = _parse_sentence(sentence)
            if ("截止时间" in updates and changes.get("截止时间") is not None
                    and changes["截止时间"] != updates["截止时间"] and not _DEADLINE_EDIT.search(sentence)):
                return {}, text.strip()
            updates.update(changes)
            remainder.append(request)
    return updates, "".join(remainder).strip()


def normalize_constraint_value(field: str, value: str) -> str | None:
    changes, _ = parse_constraint_request(value)
    if field in changes:
        return changes[field]
    return None if _UPDATE.match(value.strip()) or _GOAL.match(value.strip()) else value


def update_constraints(current: dict, message) -> None:
    if message.role != "user":
        return
    meta = getattr(message, "meta_data", None) or {}
    statements = meta.get("career_constraints")
    if not isinstance(statements, dict):
        statements = extract_constraints(message.content)
    for field, value in statements.items():
        if field in _FIELD_ALIASES and (value is None or isinstance(value, str)):
            current[field] = (str(message.id), normalize_constraint_value(field, value) if value is not None else None)


def extract_constraints(text: str) -> dict[str, str | None]:
    return parse_constraint_request(text)[0]


def known_constraint_fields() -> set[str]:
    return set(_FIELD_ALIASES)


def constraint_types() -> list[str]:
    return list(_FIELD_ALIASES)


async def latest_constraints(messages) -> dict:
    current: dict = {}
    async with aclosing(messages) as history:
        async for message in history:
            found: dict = {}
            update_constraints(found, message)
            for field, value in found.items():
                current.setdefault(field, value)
            if len(current) == len(_FIELD_ALIASES):
                break
    return {key: value for key, value in current.items() if value[1] is not None}


def constraint_details(current: dict, version: int, metadata: dict | None = None) -> list[dict]:
    return [
        {"field": field, "source_message_id": source, "value": value, "version": version, "confirmed": version > 0,
         **(metadata or {}).get(field, {}),
         **({"confirmed": False, "status": "AMBIGUOUS"}
            if field == "截止时间" and not (metadata or {}).get(field, {}).get("normalizedValue")
            and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else {})}
        for field, (source, value) in current.items() if value is not None
    ]


def effective_content(message, current: dict, *, keep_current: bool = True) -> str:
    removed = False
    kept = []
    for sentence in [part for line in message.content.splitlines() for part in _SENTENCES.split(line) if part.strip()]:
        updates, request = _parse_sentence(sentence)
        is_current = keep_current and message.role == "user" and updates and all(
            tuple(current.get(field, ())) == (str(message.id), value) for field, value in updates.items()
        )
        if is_current or (not updates and not _HISTORICAL_PINNED.search(sentence)):
            kept.append(sentence.strip())
            continue
        removed = True
        if request != sentence and request:
            kept.append(request)
    return "\n".join(kept) if removed else message.content


def without_constraint_updates(text: str) -> str:
    """Only the stored revision supplies active values, even when regenerating old turns."""
    return parse_constraint_request(text)[1]


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
    standalone = current is None
    if standalone:
        current = {}
        for message in messages:
            update_constraints(current, message)
    candidates = []
    requested_skills = skills_in(question)
    for index, message in enumerate(messages):
        parts = sentences(effective_content(message, current, keep_current=standalone))
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
