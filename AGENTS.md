# Search_Agent 开发约定

## 项目基础

- 工作目录：D:\Agent\Search_Agent。
- 用户明确要求直接基于 https://github.com/lm041520/Comet 的源码改造。
- 不使用 CoreCoder 作为代码、架构或文档的复用参考。
- origin 指向 https://github.com/JonyChuang/Search_Agent.git，main 为开发分支，后续代码推送到 origin。
- upstream 指向 Comet，作为更新来源；本地已禁用向其推送。初始版本见交接文档。
- 阅读 literature-agent-handoff-2026-11-04.md 获取产品范围；README.md 当前仍为上游运行说明。

## 产品目标

面向计算机与人工智能方向研究生的科研文献助手，以 Agent 为入口。优先打通研究方向、真实论文搜索、收藏、PDF 阅读问答、个人笔记及每日订阅推荐。

- 论文元数据来自可核对的数据源；回答保留来源，区分摘要依据与全文依据。
- 用户笔记与 AI 草稿分别保存；订阅支持用户创建、暂停和删除。
- 在 Comet 现有模块上增量实现，并如实记录已验证与尚未实现的能力。

## 结构与验证

- 后端位于 api/，前端位于 web/；保留 controller → service → repository → model/db 分层。
- 后端依赖使用 uv；数据库变更通过 Alembic 迁移。
- 新业务数据沿用 user_id 隔离，敏感配置沿用现有加密机制。
- 后端代码变更按上游约定运行 uv run ruff check .（api/）。
- 前端代码变更按上游约定运行 npx tsc --noEmit（web/），交付构建时运行 npm run build。
- 针对涉及的数据持久化、检索来源、用户隔离或订阅去重执行相应验证；环境缺失时明确记录未运行项。
- 保留上游来源和现有文件；当前仓库未发现项目自身的明确许可证声明，不自行添加许可证结论。
