# Java 业务后端 + Python Agent 架构决定

日期：2026-11-05
状态：技术路线已选定，第一天工程基线见 [本地启动与验收](career-agent-day-1-2026-11-06.md)。

## 1. 已确认方向

面向研究生的求职与面试训练 Agent，以 Comet 为源码基础，开发仓库为 JonyChuang/Search_Agent。用户已明确选择 Java 后端 + Agent。

产品范围和导航沿用 career-agent-change-list-2026-11-05.md。本文更新其中的服务归属、文件位置和实施顺序：求职业务不能继续全部新增到 Python services 中。

- Java：账户与业务权限、求职档案、岗位与公司、简历版本、题库、作答与练习、面试业务、学习计划、网申和投递状态。
- Python：模型适配、Agent Harness、RAG、文档处理、Skill 读取与执行、推理过程、工具编排。
- React：保留 Comet 前端，按已有导航设计调整页面，通过业务 API 展示真实数据。
- 独立执行器：编程/SQL 判题、网申浏览器操作；与主 API 分开运行。

## 2. 技术选择

| 层 | 选择与边界 |
| --- | --- |
| Java 服务 | Spring Boot、Spring Security、Bean Validation、MyBatis-Plus、Maven |
| Java 业务库 | MySQL；通过 Flyway 管理 Java 自己的业务表 |
| Python Agent | 保留 FastAPI、LangChain 和 Comet 工具注册机制，逐步提取通用 Harness |
| Python 后台执行 | 复用 Redis/Celery，Java 通过内部 HTTP 接口提交任务，不直接构造 Celery 私有消息协议 |
| 检索 | 先复用 Elasticsearch 混合检索，按公共资料和用户私有材料过滤 |
| 文件 | 保留存储接口；Java 管理材料归属和版本，Python 仅读取获准处理的材料 |
| 前端 | 保留 React、TypeScript、Ant Design 和 Vite |
| 进度 | 优先沿用 SSE 与可查询的持久化任务事件；断线后从事件序号继续读取 |
| 原有存储 | PostgreSQL 和 Neo4j 暂按上游兼容需求保留，不清库或自动替换；是否退役按模块迁移和实际需求决定 |

具体依赖版本在创建工程时核实兼容性并锁定。Spring Boot 与 MyBatis-Plus 的 Starter 须匹配，不直接拼接不同大版本依赖。

官方选型入口：
- https://docs.spring.io/spring-boot/system-requirements.html
- https://baomidou.com/en/getting-started/
- https://docs.celeryq.dev/en/stable/userguide/tasks.html

首阶段按两套应用服务部署，不按每个业务模块拆微服务。Redis 优先用于现有队列、事件及有依据的限流/缓存需求；Kafka、多级缓存等按实际瓶颈再引入。

## 3. 调用关系和状态归属

~~~mermaid
flowchart TB
    Web[React 前端] --> Java[Java 业务 API]
    Java --> SQL[(MySQL 业务与任务记录)]
    Java --> Agent[Python Agent 内部接口]
    Agent --> Worker[Celery 执行与 Harness]
    Worker --> Model[模型 / RAG / Skill]
    Worker --> Tools[求职工具适配层]
    Tools --> Java
    Worker --> Executors[独立判题 / 浏览器执行器]
    Worker --> Events[步骤事件与检查点]
    Events --> Java
    Java --> Web
~~~

Java 是求职业务事实及任务对外状态的权威写入方。Python 保存推理轨迹和检查点，通过内部事件回报执行情况；不能直接改写 Java 业务表。

服务契约携带 run_id、step_id、事件序号和业务版本。用户身份来自 Java 验证后的任务上下文和受控服务调用，不能采用模型自由填写的 user_id。Python 内部接口不得以客户端传入一个用户 ID 作为充分授权。

业务与存储划分：

| 对象 | 权威归属 | Python 如何使用 |
| --- | --- | --- |
| 经历、简历版本、岗位、题目、作答、申请阶段 | Java | 通过业务工具读取或请求修改 |
| 任务目标、用户归属、取消、对外状态 | Java | 接收任务和取消信号，返回执行事件 |
| 模型消息、工具轨迹、上下文摘要、运行检查点 | Python | 运行时持久化，关联 Java run_id |
| 文档解析文本与搜索索引 | Python 检索服务 | 必须保留 Java 材料 ID、版本和授权范围 |
| Skill 安装来源、版本及用户启停 | Java | 按指定版本加载，报告工具依赖和运行结果 |

Python 的当前 Alembic 历史继续管理上游表；Java Flyway 只管理新业务库。两种迁移工具不共同管理同一张表。

## 4. 首条业务链路

输入：用户确认的求职经历、一份真实岗位描述、经过审核的题目。

1. Java 验证身份，保存经历与岗位；创建有幂等键的训练准备任务。
2. 任务记录与待派发记录在同一数据库事务中保存，后台派发到 Python；请求接收成功和 Agent 完成分别记录。
3. Python 按 run_id 去重接收并保存运行信息，交由后台 Worker 执行。Java 未收到回执可查询或重投同一 run_id。
4. Agent 分析岗位，通过工具请求 Java 获取适用题目并创建练习计划；页面和工具共用 Java 业务服务。
5. 用户通过 Java 提交答案，提交记录绑定题目与评分规则版本；客观题由确定规则判分，主观评价调用 Python。
6. Java 保存练习反馈和错题，Agent 基于实际结果建议后续复习；Java 校验并保存计划调整。
7. 前端可以在刷新或重新连接后继续查看任务与结果。

业务状态至少区分：待派发、待执行、运行中、等待用户、成功、失败、取消。任务取消与执行完成竞态通过版本和明确状态转换处理；不能由晚到事件覆盖新的终态。

## 5. 任务可靠性和 Harness

上下文、记忆、治理、并发与可验证简历成果的具体机制见 [Agent 工程设计](agent-engineering-highlights-2026-11-05.md)。

- 相同业务请求只创建一个任务；同一个工具写操作使用独立幂等键。任务去重不等于外部副作用已经去重。
- 同一会话内的有序操作串行；不同会话可以并行。无需按整个用户范围把所有任务串行化。
- 数据库提交和远端调用之间使用持久化待派发记录、重试与核对，不依赖一次跨服务 HTTP 请求永远成功。
- 检查点保存目标、上下文引用、已完成步骤及下一步；恢复后先检查已经产生的结果。
- 网申结果不明时先核实站点回执和申请状态，不能盲目重放提交。
- Hook/工具执行链统一进行参数校验、用户归属、Skill 工具范围、业务版本和事件留痕。
- Skill 不能绕过 Java 权限或直接写库。练习答案和程序判题结果由相应服务评定，模型不能自行提交可信分数。
- 记录任务受理、首个进度和完整完成时间，分开衡量；日志关联 run_id 和调用链，保留 token/成本统计。

## 6. 目标目录及迁移

以下为规划路径，不表示工程已建立：

~~~text
Search_Agent/
  backend/                         Java 业务服务
    pom.xml
    src/main/java/.../
      auth/
      profile/
      job/
      resume/
      question/
      practice/
      interview/
      application/
      plan/
      agenttask/
      integration/                 Python 内部接口与工具契约
    src/main/resources/db/migration/
    src/test/
  api/                             保留 Comet Python 服务，逐步聚焦 Agent
    app/core/agent/
    app/core/rag/
    app/core/skills/                按需新增
    app/tasks/
    app/integrations/career/        Java 业务工具客户端，按需新增
  web/                             React 前端
  contracts/                       内部任务、事件、工具接口约定，按需新增
  docs/
~~~

旧清单 N01–N09 的求职事实、N10 的业务任务记录、N11 的安装登记归 Java；Python 保留 Harness 状态、技能包解析与运行工具。旧清单中的 Python controller/model/service 路径是迁移前方案，按此边界调整，不能在两端重复建设整套求职业务。

账户、模型配置、材料、对话等既有模块逐项检查后迁移。兼容期明确路由与身份验证契约；同一个用户、材料和任务保留稳定标识。实施前核实旧数据及加密配置，不自动拷贝密码、密钥或废弃 PostgreSQL。

## 7. 实施顺序与验收

| 阶段 | 工作 | 验收 |
| --- | --- | --- |
| 0：工程与契约 | Java 工程、数据库迁移、身份验证契约、统一错误、Python 健康与任务内部接口 | 服务可启动；未授权访问被拒绝；接口契约和故障响应可验证 |
| 1：业务与任务 | 档案、JD、题目、练习、任务派发/事件与首批工具 | 跑通第 4 节；刷新后数据仍在；重复请求和中断恢复不重复创建结果 |
| 2：准备闭环 | 面经审核、主观评价、错题计划、简历版本与导出、模拟面试 | 有来源的题库到作答复习闭环；依据真实经历生成材料 |
| 3：求职执行 | Skill 包安装与版本、浏览器适配、独立判题、网申/投递 | 一个明确支持站点可恢复执行；真实判题；安装技能可配置、禁用和卸载 |
| 4：优化 | 固定任务集、任务质量和成本评测 | 根据证据再决定缓存扩展、模型训练或多 Agent |

Java 使用 Maven 验证业务规则和跨服务契约；Python 按仓库约定运行 Ruff 及与改动对应的测试；React 运行类型检查及交付构建。验证用户隔离、重复事件、任务恢复、题目/材料版本、评分和申请状态。仅有模拟接口通过不能宣称真实模型、浏览器或数据库集成已完成。

## 8. 当前实际状态

已建立 `backend/`、Flyway 首条求职库迁移、Java 到 Python 的健康检查和前端开发代理。后续按阶段接入业务数据与任务执行，实际验收以 [第一天记录](career-agent-day-1-2026-11-06.md) 为准。

后续实施以阶段 0 和首条业务链路为入口。以用户自己的实际实现和测量结果记录项目成果，不采用上游或他人简历中的性能数字。
