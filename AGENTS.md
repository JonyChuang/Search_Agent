# Search_Agent 开发约定

## 项目基础

- 工作目录：D:\Agent\Search_Agent。
- 用户明确要求直接基于 https://github.com/lm041520/Comet 的源码改造。
- 不使用 CoreCoder 作为代码、架构或文档的复用参考。
- origin 指向 https://github.com/JonyChuang/Search_Agent.git，main 为开发分支，后续代码推送到 origin。
- upstream 指向 Comet，作为更新来源；本地已禁用向其推送。初始版本见交接文档。
- 当前运行架构与部署说明见 docs/python-runtime-operations.md。

## 产品目标

当前产品方向为面向研究生的求职与面试训练 Agent。2026-11-05 的求职方案替代旧的科研文献助手规划。

- 早期求职计划见 docs/career-agent-change-list-2026-11-05.md，科研文献助手交接仅用于历史参考。
- 打通真实经历、岗位与公司、简历定制、面经与题库、刷题、模拟面试、网申与投递跟踪。
- 侧栏底部依次为“求职进展”“个人工作区”“设置”。设置默认展开，包含模型配置、角色配置、技能中心、工具配置和消息推送。Comet 工作台位于头像菜单。
- 支持求职内置 Skill 和用户安装 Skill；复用现有模板/编辑/启停，新增包导入、版本、依赖检查与更新卸载。
- 以持久化任务状态和可恢复执行支撑 Agent；页面与 Agent 共用业务服务。Skill 描述流程，工具执行操作，Harness 管理状态。
- 简历依据用户确认的真实经历；练习成绩与上游项目文档不能自动转化为用户成果。
- 面经、岗位和公司信息保留来源与时间；公共资料和个人材料分开管理，题目与评分规则保留版本。
- 网申草稿与实际提交状态区分；按用户明确指令提交，结果不明先核实，保留人工接管和恢复。
- 已建立第一天的工程和联通基线；docs/design/ 仅为示例界面，不能把示例数据或按钮宣称为已实现功能。
- 在 Comet 现有模块上增量实现，保留原有文件、数据与迁移历史；不复用 CoreCoder。

## 结构与验证

- api/ 为 FastAPI 与 Python Worker，web/ 为 React。backend/ 保留既有 MySQL 迁移和 Java 历史参考。
- Python 负责求职业务、Agent 与任务调度。部署时使用独立 Career Worker，开发模式可由 FastAPI 启动。
- MySQL 保留既有 Flyway SQL 和校验和，由 Python 迁移器执行。账户和对话等 PostgreSQL 数据使用 Alembic 迁移。
- Python 依赖使用 uv，测试在 api/ 使用 python -m unittest discover -s tests。
- 新业务数据沿用 user_id 隔离，敏感配置沿用现有加密机制。
- Python 变更使用 uv run --locked ruff check app，求职队列验证使用 python -m eval.career_worker_load。
- 工具和页面复用 Python 业务权限。写操作需要独立幂等和明确确认，身份来自认证凭证。
- 前端代码变更按上游约定运行 npx tsc --noEmit（web/），交付构建时运行 npm run build。
- 针对数据持久化、用户隔离、材料与来源、判题、技能安装及网申副作用执行相应验证；环境缺失时明确记录未运行项。
- 保留上游来源和现有文件；当前仓库未发现项目自身的明确许可证声明，不自行添加许可证结论。

## Agent 工程设计与成果记录

- 用户要求在上下文压缩、长短期记忆、治理及并发等设计中参考 Claude Code 或其他成熟 Agent 的公开文档/开源实现，并适配求职业务；详见 docs/agent-engineering-highlights-2026-11-05.md。
- 仓库中保留来源和复用边界；公开行为说明不等于掌握闭源内部实现。实现与测量完成后才能把机制与结果写成已完成的简历成果。
- 上下文采用预算装配、原文引用及可回查压缩；会话状态与长期事实分别管理；Python 负责业务授权、事实版本、推理与工作记忆。
- 同会话有序、跨会话有界并行；写操作独立幂等并校验执行代次；用户安装的 Skill 不扩大权限。
