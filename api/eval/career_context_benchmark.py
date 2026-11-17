"""Deterministic context comparison for three synthetic career conversations."""
import argparse
import json
from statistics import mean
from time import perf_counter
from types import SimpleNamespace
from uuid import UUID

import httpx
from json_repair import loads

from app.core.rag.chunker import count_tokens
from app.services.career_chat_context import HISTORY_TOKENS, RECENT_MESSAGES, clip, summarize

SCENARIOS = (
    ("resume", "确认只用已核对的项目经历", "已核对的项目经历", "简历经历、岗位关键词和原始项目说明。"),
    ("interview", "确认目标是后端实习，保留数据库追问", "保留数据库追问", "面试题目、数据库索引和各轮回答。"),
    ("application", "申请截止时间是 2026-12-17", "2026-12-17", "招聘要求、附件清单、来源和个人表单答案。"),
)


def measure(model=None):
    output = []
    for task, constraint, required, filler in SCENARIOS:
        messages = [SimpleNamespace(id=UUID(int=index + 1),
                                   role="user" if index % 2 == 0 else "assistant",
                                   content=(filler * (index % 4 + 1) * 45) + f"记录 {index}。")
                    for index in range(60)]
        messages[2].content = constraint + "。"
        messages[-1].content = "最近一轮的完整结果。"
        baseline = "\n".join(row.content for row in messages[-40:])
        start = perf_counter()
        recent = "\n".join(clip(row.content, HISTORY_TOKENS // RECENT_MESSAGES - 12)
                           for row in messages[-RECENT_MESSAGES:])
        compact = summarize(messages[:-RECENT_MESSAGES])
        elapsed = round((perf_counter() - start) * 1000, 2)
        evidence = next((item for item in json.loads(compact) if required in item["excerpt"]), {})
        prepared = compact + "\n" + recent
        output.append({"task": task, "baseline_tokens": count_tokens(baseline),
                       "prepared_tokens": count_tokens(prepared), "assembly_ms": elapsed,
                       "baseline_preserves_constraint": required in baseline, "constraint_source_matches":
                           evidence.get("message_id") == str(messages[2].id), "recent_result_preserved": messages[-1].content in recent})
        if model:
            output[-1]["model_comparison"] = compare_model(model, baseline, prepared, required)
    return {"model_calls": len(output) * 2 if model else 0, "tokenizer": "cl100k_base", "runs": output,
            "mean_assembly_ms": round(mean(row["assembly_ms"] for row in output), 2)}


def compare_model(model, baseline, prepared, required):
    results = {}
    question = "找出这个任务中明确确认的求职约束或申请截止时间。仅返回 JSON 对象，constraint 为原文，无法找到时写 null。"
    with httpx.Client(timeout=120, follow_redirects=False) as client:
        for variant, text in (("fixed_window", baseline), ("budgeted", prepared)):
            started = perf_counter()
            response = client.post(f"{model.base_url}/chat/completions",
                                   headers={"Authorization": f"Bearer {model.api_key}"}, json={
                                       "model": model.model_name, "temperature": 0, "max_tokens": 220,
                                       "messages": [{"role": "system", "content": question}, {"role": "user", "content": text}],
                                   })
            response.raise_for_status()
            data = response.json()
            decoded = loads(data["choices"][0]["message"]["content"] or "{}")
            answer = decoded.get("constraint") if isinstance(decoded, dict) else None
            usage = data.get("usage") or {}
            results[variant] = {"model": model.model_name, "matches": isinstance(answer, str) and required in answer,
                                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                                "elapsed_ms": round((perf_counter() - started) * 1000, 2)}
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-model", action="store_true", help="向评测配置中的服务发送六个合成请求")
    args = parser.parse_args()
    model = None
    if args.with_model:
        from eval.eval_config import chat_client

        model = chat_client()
    print(json.dumps(measure(model), ensure_ascii=False, indent=2))
