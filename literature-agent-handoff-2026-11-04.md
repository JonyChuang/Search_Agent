> 历史交接文档：2026-11-05 产品方向已调整为“研究生求职与面试训练 Agent”。当前功能、导航、Skill、网申及文件级改造清单见 [最新修改清单](docs/career-agent-change-list-2026-11-05.md)。本文保留历史背景，不再作为当前产品范围。

# 文献 Agent 项目交接文档

日期：2026-11-04
目标开发目录：`D:\Agent\Search_Agent`。
开发基础：[lm041520/Comet](https://github.com/lm041520/Comet/tree/main)，直接在其源码上改造为 Search_Agent。用户于 2026-11-04 明确取消 CoreCoder 复用方案。

## 一、背景与项目目标

用户希望把新项目打造为以 Agent 为中心的科研文献助手，直接以 Comet 源码为基础进行改造，沿用其产品基础和助手体验；使用对象先聚焦计算机及人工智能方向的研究生。原有企业服务台和工单不再是新项目的业务定位。

核心场景：研究者设置研究方向后，可以搜索、收藏、阅读和管理论文，记录个人笔记，并订阅相关新论文；Agent 根据任务使用检索、阅读、笔记和推荐工具，提供可追溯结果。用户希望项目自带 Skill，也支持用户安装自己的 Skill；复杂任务可考虑多 Agent。

完整用户路径：设置方向 → 搜索论文 → 收藏到文献库 → 阅读和提问 → 写笔记 → 订阅新文献 → 查看推荐和反馈 → 持续调整偏好。

## 二、产品原则

- 首页以助手和任务为中心，支持自然语言提出请求、查看任务进度和结果；文献库、笔记、推荐等页面配合助手使用。
- 真正打通数据和操作流程，不把空页面或模拟内容当作已完成功能。
- 文献记录来自可核对的数据源，提供标题、作者、日期、标识及来源链接；不让模型凭记忆编造引用。
- 将摘要、用户提供的全文和其他可合法获取的全文区分开；总结明确标示依据范围，涉及原文定位时保留可追溯的页码或片段。
- 用户笔记与 AI 草稿区分保存，AI 不覆盖用户原文；涉及订阅或修改数据的动作提供清晰的用户控制。
- 默认关注单人可用的闭环，再推进权限、团队协作及规模化；企业级能力以实际验证为准，不提前宣称生产就绪。

## 三、功能范围

### 第一阶段：文献日常使用闭环

1. 账号和研究方向：保存主题、关键词及用户选定的种子论文。
2. 论文发现：接入一个可靠学术数据源，搜索并展示元数据与来源；处理分页、限流、异常和去重。
3. 个人文献库：收藏、分类或标签、待读/阅读中/已读状态；识别同一论文的不同来源和版本。
4. 论文阅读与问答：上传用户有权使用的 PDF，解析、索引和检索；回答标注依据及可访问范围，未获得全文时不得声称读过全文。
5. 阅读笔记：用户编辑与保存、关联论文、区分 AI 草稿；逐步完善原文定位与引用。
6. 每日跟踪：用户创建、暂停或删除订阅；定时获取候选论文、过滤和去重，展示推荐理由及链接；无符合条件的新论文时不重复推送。先提供站内推荐和历史，其他推送渠道后续扩展。
7. Agent 主界面：对话、工具调用状态、来源和任务结果可见；提供明确的失败与重试状态。

### 后续完善

- 深度文献调查：多篇论文搜索、筛选、比较，生成可核对来源的报告；将可获取的摘要和全文区别呈现。
- Skill：项目自带文献搜索、精读、对比、笔记整理和追踪等技能；用户可安装、配置、启停、更新与卸载自己的技能。优先支持流程/参考资料型技能；脚本型技能需具备隔离运行能力后才支持执行。
- 多 Agent：仅在复杂任务按需分配检索、阅读和核查职责；与单 Agent 在同一任务集比较效果、延迟和成本。
- 研究记忆与图谱：用户可查看、修正和删除的任务事实；建立可追溯的论文、方法、任务等关系，不将推测或共现直接视为事实。
- 产品完善：流式进度、任务恢复、运行记录、模型和工具配置、用户隔离、部署维护、评测与成本统计。

## 四、Comet 开发基线与改造入口

用户已明确：以 GitHub 上的 Comet 项目为基础，在本目录直接改造；不使用 CoreCoder 作为复用参考。原先围绕 CoreCoder 的迁移表、R01/R02/R03 编号和旧项目规划不再作为本项目的开发依据。

- 开发仓库（origin）：https://github.com/JonyChuang/Search_Agent.git
- 上游来源（upstream）：https://github.com/lm041520/Comet.git；仅用于获取更新，本地已禁用向上游推送。
- 上游分支：main；本地开发分支：main，推送到 origin/main。
- 初始提交：2ae1c07425de51d6891644ff75c9ecfa5b0e6e6e。
- 已补全 Comet 的 Git 历史，保留原始提交与来源记录。
- 后续改造提交到 JonyChuang/Search_Agent，不推送到 Comet。
- 原始 README.md 保留上游项目说明；本交接文档和 AGENTS.md 记录 Search_Agent 的目标与开发约定。

以下为本次源码检查确认的入口，仅表示已有代码，尚未验证运行效果：

| 模块 | 当前代码位置 | 文献场景改造方向 |
| --- | --- | --- |
| Agent 与工具 | api/app/core/agent/orchestrator.py、tools/registry.py、tools/builtin/ | 加入论文检索、收藏、阅读、笔记工具，按任务选择工具 |
| 文档解析与检索 | api/app/core/rag/parser.py、chunker.py、search.py、es_store.py | 论文 PDF、页码与片段定位、论文及笔记检索 |
| 深度研究 | api/app/core/agent/research/、api/app/services/research_service.py | 学术来源、论文筛选、摘要与全文范围、带来源的对比报告 |
| Skill | api/app/services/skill_service.py、skill_builtins.py、web/src/pages/SkillPage.tsx | 文献工作流模板、自定义技能与工具配置；外部技能包安装能力另行检查和扩展 |
| 定时任务与通知 | api/app/services/agent_task_service.py、notify_service.py、api/app/tasks/ | 论文订阅、增量候选、去重、推荐历史、暂停与恢复 |
| 账户与配置 | api/app/services/auth_service.py、model_config_service.py、api/app/models/ | 沿用账户与模型配置，新增用户研究方向与偏好 |
| 前端 | web/src/pages/ChatPage.tsx、KnowledgeBasePage.tsx、ResearchPage.tsx、AgentTaskPage.tsx | 助手入口、个人文献库、阅读笔记及推荐体验 |

技术基础以当前 Comet 为准：FastAPI、SQLAlchemy/Alembic、PostgreSQL、Elasticsearch、Neo4j、Redis/Celery；React/TypeScript/Ant Design/Vite。遵循现有 controller → service → repository → model/db 分层及用户隔离方式。

代码检查时未发现项目自身的 LICENSE/COPYING 文件或明确许可声明，不能据此标注为 MIT、Apache 等许可证。

## 五、建议的任务拆分与验收

1. **检查目标项目**：确认 Comet 导入版本、配置、Git 状态和开发环境；围绕其已有结构增量改造。
2. **建立基础闭环**：选定并核实论文来源及其使用条件；实现真实搜索、收藏、论文导入、问答和笔记。验收：用户检索一篇真实论文，收藏、阅读、提问并保存笔记，刷新后仍可访问。
3. **实现持续跟踪**：保存订阅，后台定时获取并去重；记录运行状态、失败原因和推荐历史。验收：订阅正常运行，可暂停恢复，重复任务不产生重复推荐；没有合适新论文时安静处理。
4. **检索与 Agent 优化**：在人工标注的论文问题和笔记样例上，评估召回、来源支持、工具选择、任务完成、耗时和成本；同样例对比现有规则与候选重排序模型。
5. **扩展能力**：按优先级建设内置与用户 Skill、深度调查、图谱和按需多 Agent；保留证据、权限和用户控制。
6. **交付验证**：检查用户隔离、错误恢复、模型或数据源不可用时的处理、迁移和部署；完整记录实际测试结果，不能编造用户量和效果指标。

围绕 Comet 现有架构增量实现文献业务，保留现有内容和来源记录；数据源结合实际需求确定。API 配额、论文元数据和全文访问条件应在实施时查阅各数据源官方说明。

## 六、参考资料

- Comet 项目及产品功能：<https://github.com/lm041520/Comet>。
- Elicit Research Agent：<https://support.elicit.com/en/articles/14757543-getting-started-with-elicit-which-workflow-should-i-use>。
- Semantic Scholar Research Feed：<https://webflow.semanticscholar.org/faq/create-research-feeds>。
- Zotero 笔记与 PDF 标注：<https://www.zotero.org/support/note_templates>。
- 本项目开发约定：`D:\Agent\Search_Agent\AGENTS.md`。
- Comet 原始运行说明：`D:\Agent\Search_Agent\README.md`。

## 七、当前交接状态

2026-11-04 已根据用户最新决定，将 Comet main 的源码导入 D:\Agent\Search_Agent，建立开发分支并保留本交接文档；随后按用户指定将 JonyChuang/Search_Agent 设为开发仓库，使用 main 分支。已初步检查代码结构和依赖声明。

当前完成的是开发基线导入与约定更新。尚未修改业务代码、安装依赖、配置模型、启动存储服务、执行数据库迁移或运行应用测试；科研文献闭环尚未实现。

后续开发在本目录的 Comet 源码上直接进行，优先实现真实论文搜索与个人文献库，再衔接已有 PDF 检索、Agent 问答、笔记和订阅能力。运行验证应区分上游现有功能与本项目新增功能。
