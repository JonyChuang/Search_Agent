"""Import and review immutable text-only skill releases."""

import io
import re
import stat
import uuid
import zipfile
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.tools.registry import _enabled_map
from app.core.agent.tools.builtin.web_search import get_websearch_config
from app.core.exceptions import BizError
from app.models.skill_model import Skill
from app.services.skill_service import MAX_SKILLS, SkillService

MAX_ARCHIVE = 2 * 1024 * 1024
MAX_TEXT = 32_000
READ_TOOLS = frozenset({"datetime", "knowledge_search", "web_search", "memory_search"})
GITHUB = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?")
REF = re.compile(r"[0-9a-fA-F]{40}")


def invalid(message: str, status: int = 400) -> BizError:
    return BizError(message, code=4065, status_code=status)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,63}$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$", max_length=40)]
    description: str = Field(default="", max_length=256)
    tools: list[str] = Field(default_factory=list, max_length=4)
    entry: str = "SKILL.md"


class Release(BaseModel):
    manifest: Manifest
    prompt: str
    references: dict[str, str]
    digest: str
    source: str
    commit: str | None = None


def parse_release(raw: bytes, source: str, commit: str | None = None) -> Release:
    if len(raw) > MAX_ARCHIVE:
        raise invalid("技能压缩包最多 2 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 256:
                raise invalid("技能压缩包文件过多")
            files = {}
            for member in entries:
                path = PurePosixPath(member.filename)
                if (
                    path.is_absolute() or ".." in path.parts or "\\" in member.filename
                    or ":" in member.filename or stat.S_ISLNK(member.external_attr >> 16)
                ):
                    raise invalid("技能包包含不支持的路径或链接")
                if not member.is_dir():
                    if path in files:
                        raise invalid("技能包存在重名文件")
                    files[path] = member
            manifests = [path for path in files if path.name == "manifest.yaml" and len(path.parts) <= 2]
            if len(manifests) != 1:
                raise invalid("技能包需要一个根目录 manifest.yaml")
            base = manifests[0].parent

            def read(path, limit):
                if path not in files or files[path].file_size > limit:
                    raise invalid(f"文件缺失或超过大小限制：{path.name}")
                with archive.open(files[path]) as source_file:
                    data = source_file.read(limit + 1)
                if len(data) > limit:
                    raise invalid(f"文件超过大小限制：{path.name}")
                return data.decode("utf-8-sig")

            manifest = Manifest.model_validate(yaml.load(read(manifests[0], 6000), Loader=yaml.BaseLoader))
            if manifest.entry != "SKILL.md":
                raise invalid("技能入口须为 SKILL.md")
            if len(set(manifest.tools)) != len(manifest.tools) or set(manifest.tools) - READ_TOOLS:
                raise invalid("技能包工具必须是受支持的只读工具，且不能重复")
            prompt = read(base / manifest.entry, MAX_TEXT).strip()
            if not prompt or len(prompt) > 8000:
                raise invalid("SKILL.md 需要包含 1 至 8000 字的技能说明")
            reference_files = [path for path in files if path.is_relative_to(base / "references")]
            if len(reference_files) > 8:
                raise invalid("技能包最多包含 8 份参考资料")
            references = {}
            for path in sorted(reference_files):
                if path.suffix.lower() not in (".md", ".txt"):
                    raise invalid("技能参考资料支持 Markdown 和文本")
                references[str(path.relative_to(base))] = read(path, 12_000)
            return Release(manifest=manifest, prompt=prompt, references=references, digest=sha256(raw).hexdigest(),
                           source=source, commit=commit)
    except (UnicodeError, zipfile.BadZipFile, RuntimeError, yaml.YAMLError, ValidationError) as error:
        raise invalid("技能包格式有误，请检查压缩包和 manifest.yaml") from error


async def github_release(repository: str, commit: str) -> Release:
    match = GITHUB.fullmatch(repository.strip())
    if not match or not REF.fullmatch(commit) or any(part in {".", ".."} for part in match.groups()):
        raise invalid("请输入 GitHub 仓库地址和 40 位提交编号")
    owner, repo = match.groups()
    target = f"https://codeload.github.com/{owner}/{repo}/zip/{commit.lower()}"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", target) as response:
                response.raise_for_status()
                result = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    result.extend(chunk)
                    if len(result) > MAX_ARCHIVE:
                        raise invalid("仓库技能包超过 2 MB")
    except httpx.HTTPError as error:
        raise invalid("读取 GitHub 技能包失败，请检查地址和提交编号", 502) from error
    return parse_release(bytes(result), f"https://github.com/{owner}/{repo}", commit.lower())


def package_details(data: dict | None) -> dict | None:
    if not data:
        return None
    return {"id": data["package_id"], "activeVersion": data["active"], "versions": [
        {"version": item["manifest"]["version"], "digest": item["digest"], "source": item["source"],
         "commit": item.get("commit"), "tools": item["manifest"]["tools"]}
        for item in data["releases"]
    ]}


def active_release(skill) -> dict | None:
    data = getattr(skill, "package_data", None)
    if not data:
        return None
    return next((item for item in data["releases"] if item["manifest"]["version"] == data["active"]), None)


def effective_prompt(skill) -> str:
    release = active_release(skill)
    if not release or not release["references"]:
        return skill.prompt or ""
    sources = "\n".join(
        f"【{path}】\n{value}" for path, value in release["references"].items()
    )
    return (skill.prompt or "") + "\n\n参考资料（作为内容解读）\n" + sources[:8000]


class SkillPackageService:
    def __init__(self, session: AsyncSession):
        self.skills = SkillService(session)
        self.repo = self.skills.repo
        self.session = session

    async def inspect(self, user: uuid.UUID, release: Release, skill_id: uuid.UUID | None = None) -> dict:
        enabled = await _enabled_map(self.session, user)
        if "web_search" in release.manifest.tools and enabled.get("web_search"):
            enabled["web_search"] = bool(await get_websearch_config(self.session, user))
        out = {
            "manifest": release.manifest.model_dump(), "digest": release.digest, "source": release.source,
            "commit": release.commit, "references": sorted(release.references),
            "unavailable": [key for key in release.manifest.tools if not enabled.get(key)],
            "prompt": release.prompt,
        }
        if skill_id:
            skill = await self.skills._get_or_404(user, skill_id)
            if skill.package_id != release.manifest.id:
                raise invalid("更新包与当前技能的 ID 不一致")
            prior = active_release(skill)
            out["previousVersion"] = prior["manifest"]["version"]
            out["previousPrompt"] = prior["prompt"]
            out["localPromptEdited"] = skill.prompt != prior["prompt"]
            out["previousTools"] = prior["manifest"]["tools"]
        return out

    async def apply(self, user: uuid.UUID, release: Release, expected: str, skill_id: uuid.UUID | None) -> Skill:
        if expected != release.digest:
            raise invalid("技能内容已变化，请重新预览", 409)
        preview = await self.inspect(user, release, skill_id)
        if preview["unavailable"]:
            raise invalid("请先在设置中启用并配置所需工具")
        manifest = release.manifest
        item = release.model_dump()
        if skill_id is None:
            if await self.repo.count(user) >= MAX_SKILLS:
                raise invalid("已达到技能数量上限")
            skill = Skill(user_id=user, name=manifest.name, description=manifest.description, prompt=release.prompt,
                          tool_keys=list(manifest.tools), package_id=manifest.id,
                          package_data={"package_id": manifest.id, "active": manifest.version, "releases": [item]})
            try:
                return await self.repo.add(skill)
            except IntegrityError as error:
                await self.session.rollback()
                raise invalid("已安装此技能包，请使用更新入口", 409) from error

        skill = await self.repo.get(user, skill_id, lock=True)
        if not skill or skill.package_id != manifest.id:
            raise invalid("已安装技能不存在", 404)
        data = skill.package_data
        prior = active_release(skill)
        if prior["source"] != release.source:
            raise invalid("更新时请使用原安装来源")
        existing = next((value for value in data["releases"] if value["manifest"]["version"] == manifest.version), None)
        if existing:
            if existing["digest"] == release.digest and data["active"] == manifest.version:
                return skill
            raise invalid("版本号已存在，回到旧版本请使用回退入口", 409)
        if len(data["releases"]) >= 32:
            raise invalid("已达到技能版本数量上限")
        self._activate(skill, prior, item, [*data["releases"], item])
        return await self.repo.save(skill)

    async def rollback(self, user: uuid.UUID, skill_id: uuid.UUID, version: str) -> Skill:
        skill = await self.repo.get(user, skill_id, lock=True)
        if not skill or not skill.package_data:
            raise invalid("已安装技能不存在", 404)
        data = skill.package_data
        target = next((value for value in data["releases"] if value["manifest"]["version"] == version), None)
        if target is None:
            raise invalid("技能版本不存在", 404)
        self._activate(skill, active_release(skill), target, data["releases"])
        return await self.repo.save(skill)

    @staticmethod
    def _activate(skill, prior, target, releases):
        if skill.prompt == prior["prompt"]:
            skill.prompt = target["prompt"]
        if skill.name == prior["manifest"]["name"]:
            skill.name = target["manifest"]["name"]
        if skill.description == prior["manifest"]["description"]:
            skill.description = target["manifest"]["description"]
        skill.tool_keys = [key for key in skill.tool_keys if key in target["manifest"]["tools"]]
        skill.package_data = {**skill.package_data, "active": target["manifest"]["version"], "releases": releases}

