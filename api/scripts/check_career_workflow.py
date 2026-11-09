"""在专用演示账号中写入示例岗位、经历和作答，验证真实模型求职链路。"""
import argparse
import json
from getpass import getpass
from time import perf_counter, sleep
from uuid import uuid4

import httpx

JOB = {
    "company": "验收示例公司", "title": "Java 后端实习（示例）",
    "description": "维护 Spring Boot 接口，理解 Java 集合、哈希约定和 MySQL 索引。",
    "sourceName": "Search Agent 验收样例", "sourcedOn": "2026-11-09",
}
EXPERIENCE = {
    "type": "project", "title": "示例课程项目", "description": "用 Java 完成课程项目的查询接口。",
    "sourceNote": "仅用于验收的合成经历", "confirmed": True,
}


def request(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}，接口返回了非 JSON 响应") from error
    if not response.is_success or payload["code"] != 0:
        raise RuntimeError(f"{method} {path}: {response.status_code} {payload['message']}")
    return payload["data"]


def run_task(client: httpx.Client, kind: str, **data):
    started = perf_counter()
    task = request(client, "POST", f"career/tasks/{kind}", json={"requestId": str(uuid4()), **data})
    while task["status"] in ("QUEUED", "RUNNING") and perf_counter() - started < 150:
        sleep(1)
        task = request(client, "GET", f"career/tasks/{task['id']}")
    print(json.dumps({
        "kind": kind, "taskId": task["id"], "status": task["status"],
        "elapsedMs": round((perf_counter() - started) * 1000),
    }, ensure_ascii=False), flush=True)
    if task["status"] != "SUCCEEDED":
        raise RuntimeError(task["error"] or "任务在等待窗口内未完成")
    return task


def verify(client: httpx.Client, access_token: str) -> None:
    client.headers["Authorization"] = f"Bearer {access_token}"
    models = request(client, "GET", "models", params={"type": "chat"})
    model = next((item for item in models if item["is_default"]), models[0] if models else None)
    if model is None or "function_call" not in model["capability"]:
        raise RuntimeError("请为演示账号配置支持工具调用的对话模型")
    print(json.dumps({"provider": model["provider"], "model": model["model_name"]}), flush=True)

    facts = request(client, "GET", "career/experiences")
    attempts = request(client, "GET", "career/practice/attempts")
    if any(fact["confirmed"] for fact in facts) or attempts["items"]:
        raise RuntimeError("请使用没有已确认经历和作答历史的独立演示账号")
    job = request(client, "POST", "career/jobs", json=JOB)
    request(client, "POST", "career/experiences", json=EXPERIENCE)
    plan = run_task(client, "training", jobId=job["id"], role="backend")
    question = plan["result"]["questions"][0]
    request(client, "POST", "career/practice/attempts", json={
        "requestId": str(uuid4()), "questionId": question["id"], "questionVersion": question["version"], "answer": "B",
    })
    run_task(client, "review", planId=plan["id"])
    run_task(client, "interview", jobId=job["id"], questionId=question["id"], questionVersion=question["version"],
             answer="我会先解释 Java 对象相等与哈希值的约定，再用集合查找举例。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="独立演示账号的用户名")
    parser.add_argument("--origin", default="http://localhost:5173", help="能访问两端 API 的本地网页地址")
    args = parser.parse_args()
    with httpx.Client(base_url=f"{args.origin.rstrip('/')}/api/", timeout=15, trust_env=False) as client:
        session = request(client, "POST", "auth/login", json={
            "username": args.username, "password": getpass("演示账号密码："),
        })
        verify(client, session["access_token"])
