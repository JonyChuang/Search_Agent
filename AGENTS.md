# Search_Agent 开发约定

## 项目基础

- 工作目录：D:\Agent\Search_Agent。
- 用户明确要求直接基于 https://github.com/lm041520/Comet 的源码改造。
- 不使用 CoreCoder 作为代码、架构或文档的复用参考。
- origin 指向 https://github.com/JonyChuang/Search_Agent.git，main 为开发分支，后续代码推送到 origin。
- upstream 指向 Comet，作为更新来源；本地已禁用向其推送。初始版本见交接文档。
- 产品范围见 docs/career-agent-change-list-2026-11-05.md；用户已选择 Java 业务后端 + Python Agent，服务归属和实施顺序以 docs/java-agent-architecture-2026-11-05.md 为准。README.md 同时保留上游运行说明。

## 产品目标

当前产品方向为面向研究生的求职与面试训练 Agent。2026-11-05 的求职方案替代旧的科研文献助手规划。

- 当前需求与文件级改造清单以 docs/career-agent-change-list-2026-11-05.md 为准；旧 literature-agent-handoff-2026-11-04.md 仅保留历史背景和上游来源。
- 打通真实经历、岗位与公司、简历定制、面经与题库、刷题、模拟面试、网申与投递跟踪。
- 导航设置紧接“求职进展”，默认展开，包含模型配置、角色配置、技能中心、工具配置和消息推送。
- 支持求职内置 Skill 和用户安装 Skill；复用现有模板/编辑/启停，新增包导入、版本、依赖检查与更新卸载。
- 以持久化任务状态和可恢复执行支撑 Agent；页面与 Agent 共用业务服务。Skill 描述流程，工具执行操作，Harness 管理状态。
- 简历依据用户确认的真实经历；练习成绩与上游项目文档不能自动转化为用户成果。
- 面经、岗位和公司信息保留来源与时间；公共资料和个人材料分开管理，题目与评分规则保留版本。
- 网申草稿与实际提交状态区分；按用户明确指令提交，结果不明先核实，保留人工接管和恢复。
- 已建立第一天的工程和联通基线；docs/design/ 仅为示例界面，不能把示例数据或按钮宣称为已实现功能。
- 在 Comet 现有模块上增量实现，保留原有文件、数据与迁移历史；不复用 CoreCoder。

## 结构与验证

- backend/ 为 Spring Boot 业务服务，api/ 为 Python Agent，web/ 为 React 前端。本地联通见 docs/career-agent-day-1-2026-11-06.md。
- Java 负责求职业务、身份权限与对外任务状态；Python 负责 Harness、模型、RAG、Skill 运行和检查点，通过内部接口调用 Java 业务。
- Java 业务库采用 MySQL/Flyway；保留现有 PostgreSQL 数据及 Python Alembic 历史，迁移按模块进行，不让两套服务同时任意修改同一业务表。
- Python 依赖使用 uv，原有表继续由 Alembic 管理；Java 使用 Maven 与独立 Flyway 迁移。具体版本在建立工程时确认并锁定。
- 新业务数据沿用 user_id 隔离，敏感配置沿用现有加密机制。
- Python 变更按上游约定运行 uv run ruff check .（api/）；Java 建立工程后使用 Maven 验证业务和跨服务契约。
- 工具和页面共用 Java 业务规则；任务派发、回调和工具副作用分别处理幂等。内部用户身份不能直接信任模型或浏览器传入的 user_id。
- 前端代码变更按上游约定运行 npx tsc --noEmit（web/），交付构建时运行 npm run build。
- 针对数据持久化、用户隔离、材料与来源、判题、技能安装及网申副作用执行相应验证；环境缺失时明确记录未运行项。
- 保留上游来源和现有文件；当前仓库未发现项目自身的明确许可证声明，不自行添加许可证结论。

## Agent 工程设计与成果记录

- 用户要求在上下文压缩、长短期记忆、治理及并发等设计中参考 Claude Code 或其他成熟 Agent 的公开文档/开源实现，并适配求职业务；详见 docs/agent-engineering-highlights-2026-11-05.md。
- 仓库中保留来源和复用边界；公开行为说明不等于掌握闭源内部实现。实现与测量完成后才能把机制与结果写成已完成的简历成果。
- 上下文采用预算装配、原文引用及可回查压缩；会话状态与长期事实分别管理；Java 负责业务授权和事实版本，Python 负责推理与工作记忆。
- 同会话有序、跨会话有界并行；写操作独立幂等并校验执行代次；用户安装的 Skill 不扩大权限。
