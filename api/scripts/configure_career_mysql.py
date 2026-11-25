"""Save the running development MySQL container's password to the shared .env."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[2]
PASSWORD_KEY = "CAREER_MYSQL_PASSWORD"


def docker_command() -> str:
    command = shutil.which("docker")
    if command:
        return command
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidate = Path(local_appdata) / "Programs/DockerDesktop/resources/bin/docker.exe"
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("找不到 Docker CLI。请从可以运行 docker 的终端重试。")


def docker_output(command: str, *args: str) -> str:
    try:
        result = subprocess.run(
            [command, *args], check=True, capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        raise SystemExit("无法读取本地项目的 MySQL 容器。请在 Docker Desktop 运行时，从 Windows 终端重试。") from None
    return result.stdout


def main() -> None:
    env_path = ROOT / ".env"
    if dotenv_values(env_path, encoding="utf-8-sig", interpolate=False).get(PASSWORD_KEY):
        print("项目根目录的 .env 已有 CAREER_MYSQL_PASSWORD。")
        return

    docker = docker_command()
    containers = docker_output(
        docker, "ps", "-q", "--filter", "label=com.docker.compose.project=search-agent-career",
        "--filter", "label=com.docker.compose.service=mysql", "--filter", "health=healthy",
    ).split()
    if len(containers) != 1:
        raise SystemExit("未找到健康的 search-agent-career MySQL 容器，请在根目录 .env 填入原密码。")
    entries = json.loads(docker_output(docker, "inspect", "--format", "{{json .Config.Env}}", containers[0]))
    password = next((entry.partition("=")[2] for entry in entries if entry.startswith("MYSQL_PASSWORD=")), "")
    if not password or any(char in password for char in "\\\r\n"):
        raise SystemExit("无法安全地将当前密码写入共享 .env，请通过 CAREER_MYSQL_PASSWORD 环境变量提供原密码。")

    set_key(env_path, PASSWORD_KEY, password, quote_mode="always", encoding="utf-8")
    print("已将项目 MySQL 的密码保存到根目录 .env。")


if __name__ == "__main__":
    main()
