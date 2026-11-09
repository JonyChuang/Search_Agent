# Comet → Search Agent 求职项目修改清单

> 架构更新（2026-11-05）：用户已确定 Java 业务后端 + Python Agent。产品范围与导航继续有效；下文将求职业务全部放入 Python 的路径及原批次顺序，由 [Java + Agent 架构决定](java-agent-architecture-2026-11-05.md) 中的服务归属与阶段 0–4 取代。Java 工程尚待创建。

日期：2026-11-05
状态：开发清单与界面设计；业务改造尚未实施。
工作目录：`D:\Agent\Search_Agent`
开发仓库：https://github.com/JonyChuang/Search_Agent
上游来源：https://github.com/lm041520/Comet
基线：`656fe21`（Comet 源码基线与交接文档），以实施时 Git 状态为准。

本文替代旧交接文档中的“科研文献助手”产品规划。保留 Comet 的技术基础，在现有项目中逐步改造。当前只完成本文、开发约定及设计稿整理；下列业务项均为待开发，文件清单中“新增”路径不表示文件已创建。

## 1. 产品目标与范围

面向研究生，串起：真实经历档案 → 岗位与公司分析 → 简历准备 → 面经学习与刷题 → 模拟面试 → 网申 → 投递跟踪与复盘。

重点是让 Agent 根据目标岗位和实际准备情况推进任务。页面与 Agent 共用业务服务；任务进度、材料版本、答题结果均持久化。先覆盖后端、算法和大模型应用方向，其他岗位通过分类、知识点与题库配置扩展。

## 2. 确定的导航

| 分组 | 菜单 | 目标路由（规划） | 页面处理 |
| --- | --- | --- | --- |
| 工作台 | 求职总览 | / | 改造 HomePage |
| 工作台 | 求职助手 | /chat | 改造 ChatPage |
| 求职准备 | 简历与经历 | /career/resume | 新增 ResumeWorkbenchPage |
| 求职准备 | 岗位与公司 | /career/jobs | 新增 JobCompanyPage |
| 求职准备 | 我的资料 | /knowledge | 改造现有知识库与文档详情 |
| 面试训练 | 面经与题库 | /career/questions | 新增 ExperienceBankPage |
| 面试训练 | 刷题练习 | /career/practice | 新增 PracticePage |
| 面试训练 | 模拟面试 | /career/interviews | 新增 MockInterviewPage |
| 求职进展 | 网申助手 | /career/apply | 新增 ApplicationAssistantPage |
| 求职进展 | 投递看板 | /career/applications | 新增 ApplicationBoardPage |
| 求职进展 | 计划与提醒 | /career/plan | 新增 CareerPlanPage |
| 设置 | 模型配置 | /settings/models | 沿用现有页面 |
| 设置 | 角色配置 | /settings/agent | 改造默认角色与设置文案 |
| 设置 | 技能中心 | /settings/skills | 扩展现有 SkillPage |
| 设置 | 工具配置 | /settings/tools | 扩展现有工具与 MCP 配置 |
| 设置 | 消息推送 | /settings/notify | 沿用渠道配置，增加求职事件 |

侧栏底部依次为“求职进展”“个人工作区”“设置”。设置默认展开，允许收起。原 Comet 工作台从头像菜单进入。侧栏较矮时允许滚动，菜单可用键盘操作。导航折叠状态独立于业务任务。

音乐、情绪、图片库、生活记忆、图谱和群聊不再占据主导航。第一阶段隐藏入口，保留已有数据和迁移；不把“隐藏菜单”当作移除后台任务。与求职无关的周期任务须另行调整。

执行轨迹进入任务详情；收藏按岗位、题目和资料归类。深度研究作为公司与岗位调查能力接入助手。

设计稿见：
- [可点击界面草图](design/career-navigation-preview.html)
- [首页与导航](design/career-navigation-v2.png)
- [技能中心](design/career-skills-preview.png)
- [网申助手](design/career-application-preview.png)

设计稿中的数量、公司、申请内容均为示例，未连接真实数据。

## 3. 现有文件修改清单

下列路径相对于仓库根目录。

| 编号 | 现有文件或目录 | 修改内容 | 批次 |
| --- | --- | --- | --- |
| C01 | web/src/layouts/MainLayout.tsx | 按第 2 节重建分组；设置默认展开；移除播放器和群聊顶栏在新主流程中的挂载；保留自适应侧栏 | A |
| C02 | web/src/App.tsx | 注册求职页面与详情路由；保留登录守卫；旧页面先按兼容策略处理 | A |
| C03 | web/index.html、web/src/pages/LoginPage.tsx、api/app/config.py、api/app/main.py | 更新项目名称、标题、登录及 API 说明；保留上游署名；检查默认应用名 | A |
| C04 | web/src/pages/HomePage.tsx、web/src/api/dashboard.ts、api/app/controllers/dashboard_controller.py、api/app/services/dashboard_service.py | 首页展示今日任务、真实练习与申请统计；未开始时显示空状态；按当前用户查询 | A/B |
| C05 | web/src/pages/ChatPage.tsx、web/src/api/chat.ts、api/app/services/chat_service.py、api/app/schemas/chat_schema.py | 对话关联目标岗位、简历版本、练习或申请；显示可打开的任务结果、错误与重试 | B |
| C06 | api/app/core/agent/orchestrator.py、context_hint.py、tools/registry.py、tools/builtin/__init__.py | 接入求职工具和任务上下文；对工具调用绑定用户身份与执行记录 | B/C |
| C07 | web/src/pages/KnowledgeBasePage.tsx、KnowledgeDetailPage.tsx、web/src/api/documents.ts、api/app/services/document_service.py | 改为“我的资料”；关联经历、简历、面经与申请附件；保留上传、解析与检索 | A/B |
| C08 | api/app/core/rag/parser.py、chunker.py、es_index.py、es_store.py、search.py、api/app/tasks/parse.py | 保留来源与页码/段落定位；区分公共学习资料和个人材料；调整索引及重建策略 | B |
| C09 | api/app/services/skill_builtins.py、skill_service.py、api/app/models/skill_model.py、api/app/schemas/skill_schema.py、api/app/controllers/skill_controller.py、api/app/repositories/skill_repository.py | 求职技能模板；新增来源、版本、安装与更新信息；保留编辑、启停、归属校验 | B/C |
| C10 | web/src/pages/SkillPage.tsx、web/src/pages/skill/SkillEditModal.tsx、web/src/api/skills.ts、web/src/stores/skillStore.ts | 内置技能/我的技能/安装入口；配置、启停、更新差异与卸载 | B/C |
| C11 | api/app/core/agent/research/、api/app/services/research_service.py | 公司及岗位调查输出包含来源与日期；区分公开事实、用户输入和待确认判断 | C |
| C12 | api/app/core/agent/loop/、tracing/、web/src/components/trace/ | 复用核查与追踪；核查异常记录为未知/失败，不转成通过；材料事实核查与练习评分分开 | B/C |
| C13 | api/app/celery_app.py、api/app/tasks/beat.py、agent_task.py、api/app/services/agent_task_service.py、notify_service.py | 新增练习复习、面试、申请截止提醒；提醒与研究任务执行分开；重复派发不重复产生副作用 | B/C |
| C14 | api/app/models/__init__.py、api/migrations/env.py、api/app/controllers/router.py | 注册新模型和路由；通过新增 Alembic 迁移扩展表，保留现有迁移历史 | A/B/C |
| C15 | api/app/config.py、api/pyproject.toml、api/uv.lock、web/package.json、web/package-lock.json、.env.example、api/.env.example、docker-compose.yml、docker-compose.prod.yml | 按实际选型增加简历导出、网申执行器、判题服务和独立队列配置；锁文件随依赖更新 | B/C |
| C16 | AGENTS.md、README.md、docs/README.md、literature-agent-handoff-2026-11-04.md | 更新产品方向、记录实施进度、保留旧交接历史与上游来源 | 已整理，持续维护 |

实际修改 C03/C15 前先定位项目名称引用，避免批量替换破坏上游来源、配置键或服务连接。C08 的解析接口变动须同步适配调用方，不能只在展示层添加页码。

## 4. 新增业务模块与文件

保留当前分层。每个业务模块按需要新增：
`api/app/models/<模块>_model.py`、
`schemas/<模块>_schema.py`、
`repositories/<模块>_repository.py`、
`services/<模块>_service.py`、
`controllers/<模块>_controller.py`。
后台流程只调用这些业务服务；页面和 Agent 共享相同持久化结果。

| 编号 | 模块名 | 新增内容与数据关系 | 前端新增文件（web/src/ 下） | 批次 |
| --- | --- | --- | --- | --- |
| N01 | career_profile | 求职目标、毕业时间与偏好；结构化教育、科研、项目和实习经历；原始材料及用户确认状态 | pages/ResumeWorkbenchPage.tsx、api/careerProfile.ts | A |
| N02 | resume | 简历、不可变内容版本、目标岗位关联、修改依据、PDF 导出产物 | api/resumes.ts、components/resume/ | B |
| N03 | job | 公司、岗位、来源 URL、采集日期、招聘要求和收藏；用户自行导入 JD 也可使用 | pages/JobCompanyPage.tsx、api/jobs.ts | A/B |
| N04 | interview_experience | 面经来源、岗位、公司、轮次、发布时间、材料关联；抽取草稿与审核状态 | pages/ExperienceBankPage.tsx、api/interviewExperiences.ts | B |
| N05 | question | 岗位/知识点分类、题目、来源类型、难度、答案、评分规则、版本与测试用例 | api/questions.ts、components/question/ | B |
| N06 | practice | 练习会话、实际作答、提交记录、判题反馈、错题与复习状态；答案与题目版本绑定 | pages/PracticePage.tsx、api/practice.ts | B |
| N07 | interview | 模拟面试、已问问题、连续追问、逐项反馈及最终复盘；关联简历、岗位和对话 | pages/MockInterviewPage.tsx、api/interviews.ts | C |
| N08 | application | 申请记录、目标岗位、材料版本、开放题答案、网申草稿、执行任务和状态事件；投递记录支持人工录入 | pages/ApplicationAssistantPage.tsx、ApplicationBoardPage.tsx、api/applications.ts | B/C |
| N09 | career_plan | 阶段计划、任务、完成记录、复习时间和提醒；调整时保存依据与变更历史 | pages/CareerPlanPage.tsx、api/careerPlan.ts | B |
| N10 | career_run | 持久化 Agent 运行状态、步骤、事件、检查点、取消/接管及产物引用 | api/careerRuns.ts、components/career/TaskRunPanel.tsx | B |
| N11 | skill_package | 技能包元信息、来源与版本、所需工具、安装记录、用户自定义配置和更新历史 | pages/skill/SkillInstallModal.tsx、api/skills.ts（扩展） | C |

数据原则：
- 个人经历、简历、作答、面试、安装记录、申请、任务与附件均检查当前用户归属。
- 公共题库与用户私有题目有明确范围；关联的参考资料也按范围过滤。
- 简历版本是经历事实的呈现；练习表现不会自动转化为简历项目成果。
- 题目/评分规则、简历、Skill 及网申步骤的版本必须能随历史记录追溯。
- 网申运行状态和投递阶段分开：一次填表失败不能把申请误记为已提交。
- 共享公司资料与用户的私人岗位记录分开管理，不把私人批注放进公共记录。

## 5. Agent Harness 与工具

新增 `api/app/core/agent/harness/`：
- `runner.py`：执行循环；从已保存的目标、当前步骤和上下文继续。
- `state.py`：状态结构、步骤结果、产物引用与恢复所需字段。
- `context.py`：选择岗位、真实经历、技能、资料和练习结果，限制每次读取范围。

持久化由 N10 的 repository/service 负责，避免多个模块各自维护运行真相。复用已有 Redis 实时事件、SSE、Celery 与 tracing；关闭前端连接后任务结果仍可查询。Celery 负责投递执行任务，业务状态保存在数据库。

新增 `api/app/core/agent/tools/builtin/career.py`，先注册：
- 查询/更新已确认的求职档案（写入有明确用户意图）。
- 分析岗位、生成简历草稿、查询简历版本。
- 检索面经与题目、创建练习、读取作答反馈、安排复习。
- 创建模拟面试、读取复盘、更新准备计划。
- 创建网申草稿、准备材料、检查申请状态。

工具能力只在对应业务已实现时启用；不要注册返回模拟成功的工具。所有工具通过业务服务执行，不能依赖模型自行传入正确的 user_id。按需装载 Skill 和调用工具，不在第一版强制引入多 Agent。

运行状态至少覆盖：待执行、运行中、等待用户、成功、失败、取消。步骤完成后保存检查点；重试须校验副作用。网申与判题执行队列独立于提醒心跳，避免长任务阻塞通知。

## 6. Skill 的具体改造

现状已存在：内置模板复制、用户创建与编辑、删除、启停、绑定知识库与工具白名单。尚不存在已验证的外部技能包安装、版本化更新与执行隔离。

新增六个求职模板：简历诊断、岗位分析、科研项目追问、算法陪练、网申材料整理、面试复盘。

新增 `api/app/core/skills/`：
- `package.py`：约定并解析技能包格式，校验必要字段与工具依赖。
- `loader.py`：按指定安装版本读取提示词和参考资料。
- `installer.py`：本地包与仓库地址导入，保存来源、检查更新及卸载关联。

第一版包格式在实施时写入单独协议：`SKILL.md`（任务说明）、`manifest.yaml`（ID、名称、版本、工具依赖、入口）、`references/`（可选资料）。借鉴 SKILL.md 形式不等于兼容所有平台的包。先支持流程与参考资料，不执行包内任意脚本。

安装流程：选择来源 → 预览说明/依赖/访问范围 → 检查兼容性 → 安装到当前用户 → 配置与启停。更新固定到明确版本并展示差异，保留用户本地修改，提供回退；更新源不可用不影响已安装版本读取。

Skill 声明不能扩大用户工具权限。运行时检查当前用户授权范围、当前任务允许的工具、Skill 所需工具与实际可用工具；缺失依赖清楚提示。包内路径与引用文件只在其允许范围内读取。卸载不删除用户简历、资料或历史任务。

## 7. 网申模块的具体改造

新增 `api/app/core/application/`：
- `browser.py`：浏览器执行器接口、页面状态和人工接管；凭证与会话按用户隔离。
- `mapping.py`：将当前用户确认的经历与指定简历版本映射到表单。
- `adapters/`：每种受支持招聘流程的读取、填写和状态确认；实施前确定首个真实站点。
- `checks.py`：附件、必填项、开放题事实、岗位条件与提交回执检查。

新增 `api/app/tasks/application.py`，长时间浏览器步骤独立后台运行。

交付分两层：
1. 所有岗位先可用：保存岗位、选择材料、编辑答案、检查草稿、人工更新投递状态。
2. 适配站点后可用：读取真实表单、填写并上传、本人接管、提交及回执核实；明确当前支持的网站和步骤。

用户看到将提交的材料与表单内容，最终提交依用户明确指令执行。遇到登录、验证码或需要本人确认的问题保留进度并接管，不声称已提交。超时或结果不明先核实站点状态再重试，避免重复申请；状态记录含来源和时间。

原始简历、浏览器会话与申请附件按用户隔离。日志保留必要的字段名、状态与错误，不原样写入账号凭据及完整敏感表单。

## 8. 面经、刷题与模拟面试的具体改造

面经导入依次为：材料入库 → 抽取草稿 → 按知识点/来源去重 → 审核 → 发布题目。公开面经、自编题、AI 生成题分开标注；来源叙述不自动当作已核实事实。

上游 `docs/` 自带 Agent/RAG 工程与面试学习文档，可列为候选资料。使用前检查来源与适用性，移除原项目/原作者经历绑定的表达；不自动当作当前用户的个人经历或已经授权公开的题库。

出题和检索读取题干与必要资料；测验中不向作答界面或作答模型提前泄露参考答案与隐藏测试。教学模式可主动提示，测验模式提交后展示参考答案。客户端不能自行提交可信分数。

判题：
- 客观题按确定答案。
- 技术问答按版本化评分要点，给出遗漏、错误与依据；模型评分标明其性质。
- 编程题由独立执行环境运行隐藏测试；SQL 题在隔离测试库比较结果。
- 新增 `api/app/core/practice/grader.py`、`judge_client.py`、`api/app/tasks/practice.py`；判题服务明确时间、内存、网络及数据边界，不在 API 主进程执行用户程序。
- 错题与复习更新按提交记录幂等处理；执行超时/系统错误与答错区分。

模拟面试保存独立业务会话，关联 Conversation 但不把所有状态塞进消息 metadata。问题、追问、评分和复盘分别可追溯；角色卡只影响表现方式，不取代业务逻辑或评分规则。

## 9. 批次、依赖与验收

| 批次 | 范围 | 关键验收 |
| --- | --- | --- |
| A：导航与基础档案 | C01–C04（基础）、N01、N03（手工录入 JD）、模型注册与迁移 | 导航与设置符合设计；真实经历和目标岗位保存后刷新仍在；无数据时不显示示例统计 |
| B：首次准备闭环 | N02、N04–N06、N08（草稿/人工看板）、N09–N10，资料溯源、内置 Skill、基础工具接入 | 导入面经并审核题目 → 作答 → 反馈/错题 → 安排复习；依据真实经历与 JD 导出简历；网申草稿与投递状态可持续保存 |
| C：执行与扩展 | N07、N11、浏览器适配、编程/SQL 判题、公司调查、技能安装与版本管理 | 完成可恢复模拟面试；真实测试用例判题；一个明确支持站点的网申流程可完成与接管；技能安装、更新、禁用和卸载符合声明 |
| D：评测与优化 | 固定任务集、轨迹、成本比较；按结果决定离线 RL | 对比同模型下原 Comet 流程与新 Harness；再决定是否训练搜索、表单操作或练习选择策略；不把模型打分或计划调整称为 RL |

A/B/C 是实施依赖顺序，不是工期承诺。题库初始资料准备、首个招聘站点、简历模板与判题服务选型在相应批次实施前确定。

必要验证：
- 新迁移在全新库与基线库上均可升级；旧数据读取正常。
- 用户 A 不能通过 ID、搜索、Agent 工具、附件或后台任务读取/修改用户 B 的资料。
- 公共题目不泄露私人材料；私有评分与隐藏测试不能经普通列表接口读到。
- 简历事实与版本、题目与评分版本、Skill 版本可追溯。
- 重复任务/提交不重复产生练习结果、提醒或申请；重试不回滚用户新修改。
- 核查失败不误记成功；后台中断、前端断线和任务恢复有真实验证。
- 后端按仓库要求运行 `uv run ruff check .`；前端运行 `npx tsc --noEmit` 与交付构建 `npm run build`，业务测试按各阶段选取必要用例。

## 10. 本次实际变更与后续入口

本次只整理需求和文件级清单，更新产品定位和文档入口，保存界面概念稿。未创建表、业务 API、页面组件、技能安装器、浏览器执行器或判题服务；未安装依赖、运行数据库迁移或应用测试。

开始业务改造时先执行批次 A。每完成一个模块，补充真实测试结果，并在本清单中标记完成内容和仍未支持的范围。
