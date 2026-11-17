"""Measure context retention against labeled job-history fixtures without model calls."""

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from uuid import UUID

from app.core.rag.chunker import count_tokens
from app.services.career_chat_context import HISTORY_TOKENS, RECENT_MESSAGES, clip, summarize, turn_content

FIXTURE = Path(__file__).with_name("fixtures") / "career_history_gold.json"
PROFILES = {"short": 28, "medium": 46, "long": 72}
PROMPTS = (
    "这个部分能用一个例子解释吗？",
    "刚才提到的几个阶段大概怎么衔接？",
    "先记一下这条资料，后面再一起整理。",
    "这些说明有点散，可以先概括一下吗？",
    "我想再看一眼前面列的检查点。",
    "现在手头只有学校的课程项目，之后补充其他材料。",
    "项目文档还有一版草稿，等我核对后再看。",
    "请把记录日期和资料来源也记下来。",
    "这个建议先放到备选清单，等有空再展开。",
    "我们把讨论接回刚才的问题吧。",
)
NOTES = (
    "可以先从输入、执行步骤和预期结果三部分复述，再找一个小型实例走完流程。",
    "如果要说明一次任务失败，先交代当时的状态、告警信息以及如何判断任务是否完成。",
    "对照岗位描述时，可以逐句标出职责与关键词，并回到自己实际做过的工作查找证据。",
    "为了便于复查，把项目截图、接口记录、实验日志和说明文档关联到各自的来源。",
    "讨论索引问题时，先明确查询条件、数据分布与排序要求，再解释为什么选择这种索引。",
    "开放题可以先交代结论，再补上方案取舍、异常处理以及验证过程。",
    "遇到多个备考主题时，可根据离面试的时间、基础熟悉程度和资料是否齐全来排序。",
    "讨论并发时可以分别检查请求进入、任务领取、业务写入、状态查询几个环节。",
    "表单里可能混有招聘方的说明和候选人填写的资料，应结合字段名称核对含义。",
    "有些面经只记录用户回忆，整理时可标注发布日期、公司和能核对的题目。",
    "把回答拆成背景、行动、产出能帮助定位证据，但产出还需要给出对应测量口径。",
    "针对面试复盘，可以分别记录已掌握的内容、还不完整的例子和下一步练习题。",
    "为了方便下一次继续，先保存当前中间结果，再把尚未验证的要点放进待办清单。",
    "案例之间的业务背景可能不同，比较结果时需要考虑输入规模和运行环境。",
)


def conversation(case, profile, case_index):
    size = PROFILES[profile]
    recent_position = size - 2 - 2 * (case_index % 4)
    positions = {
        "short": (4 + 2 * (case_index % 3), recent_position),
        "medium": (6 + 2 * (case_index % 5), 22 + 2 * (case_index % 8)),
        "long": (4 + 2 * (case_index % 7), recent_position if case_index % 2 else 38),
    }[profile]
    rows = []
    for position in range(size):
        offset = case_index + position // 2
        if position % 2 == 0:
            text = PROMPTS[offset % len(PROMPTS)]
        else:
            length = (2, 5, 9)[offset % 3]
            text = "\n".join(NOTES[(offset + step) % len(NOTES)] for step in range(length))
        rows.append(SimpleNamespace(id=str(UUID(int=position + 1)),
                                    role="user" if position % 2 == 0 else "assistant", content=text))
    if case.get("superseded"):
        rows[2].content = case["superseded"]
    for position, fact in zip(positions, case["facts"], strict=True):
        rows[position].content = fact["message"]
    gold = {rows[position].id: fact["value"] for position, fact in zip(positions, case["facts"], strict=True)}
    return rows, gold


def fixed_window(rows):
    return {row.id: row.content for row in rows[-40:]}


def budgeted_history(rows):
    budget = HISTORY_TOKENS // RECENT_MESSAGES - 12
    recent = {
        row.id: turn_content(row.content, [], budget) if row.role == "user" else clip(row.content, budget)
        for row in rows[-RECENT_MESSAGES:]
    }
    compact = summarize(rows[:-RECENT_MESSAGES])
    earlier = {entry["message_id"]: entry["excerpt"] for entry in json.loads(compact)} if compact else {}
    return earlier | recent, count_tokens("\n".join([compact, *recent.values()]))


def recent_only(rows, budget):
    chosen = []
    for row in reversed(rows):
        rendered = "\n".join(text for _, text in reversed(chosen))
        complete = "\n".join(part for part in (row.content, rendered) if part)
        if count_tokens(complete) <= budget:
            chosen.append((row.id, row.content))
            continue
        excerpt = clip(row.content, budget - count_tokens(rendered) - 1)
        if excerpt and count_tokens(f"{excerpt}\n{rendered}") <= budget:
            chosen.append((row.id, excerpt))
        break
    return dict(reversed(chosen))


def score(context, gold, tokens=None):
    recovered = [key for key, value in gold.items() if value in context.get(key, "")]
    return {"hits": len(recovered), "total": len(gold),
            "tokens": count_tokens("\n".join(context.values())) if tokens is None else tokens,
            "missing": [value for key, value in gold.items() if key not in recovered]}


def summarize_scores(results):
    return {"hits": sum(item["hits"] for item in results),
            "total": sum(item["total"] for item in results),
            "all_facts_cases": sum(item["hits"] == item["total"] for item in results),
            "mean_tokens": round(mean(item["tokens"] for item in results), 2)}


def evaluate(cases):
    runs = []
    by_method = defaultdict(list)
    for index, case in enumerate(cases):
        for profile in PROFILES:
            rows, gold = conversation(case, profile, index)
            context, tokens = budgeted_history(rows)
            comparison = {"fixed_40": score(fixed_window(rows), gold),
                          "recent_same_budget": score(recent_only(rows, tokens), gold),
                          "budgeted_history": score(context, gold, tokens)}
            runs.append({"case": case["id"], "profile": profile, "messages": len(rows), **comparison})
            for name, result in comparison.items():
                by_method[name].append(result)
    return {"scenarios": len(cases), "conversations": len(runs),
            "summary": {name: summarize_scores(rows) for name, rows in by_method.items()}, "runs": runs}


if __name__ == "__main__":
    print(json.dumps(evaluate(json.loads(FIXTURE.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2))
