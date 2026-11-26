# 正确性、安全性与恢复验收记录

本页保留上一轮验收记录。混合请求、字段级约束和 MCP 限时预授权见 [岗位约束与运行配置](python-runtime-operations.md#岗位约束与运行配置)。

代码基线为 GitHub 上 Search_Agent 的 main 提交 `632aa84`。运行架构由 FastAPI、Python Career Worker、Celery Worker 和 Beat 构成。两个新增 Alembic 版本只增加 PostgreSQL 索引和监控采样表。MySQL 迁移历史、任务检查点、Redis Stream 键和游标格式沿用当前版本。

| 项目 | 根因 | 修改文件与核心变更 | 验证结果 | 兼容性与剩余风险 |
| --- | --- | --- | --- | --- |
| P0 约束历史覆盖 | 历史摘要会保留助手复述。旧轮次重生成会再次将旧请求中的约束声明发给模型。空状态缺少权威表达，消息和版本分两次提交。 | `career_chat_context.py`、`career_context_versions.py`、`chat_service.py`。历史和重生成输入去除已识别的旧约束，提示词显式使用已保存快照，包括空列表。用户消息和修订在同一事务下写入。 | 本地回归覆盖旧摘要和复述。真实 PostgreSQL 验证并发编辑只接受一方、删除后重新读取、显式回滚。 | 既有版本、按钮和接口沿用。规则只自动识别项目已有的目标、顺序和截止时间表达。复杂自然语言可通过约束面板确认。生成中的一轮使用该轮组装时的快照。 |
| P0 MCP 无确认调用 | 旧的本地 `read` 授权在执行入口直接放行，配置标签不能证明远端工具的副作用。 | `mcp/execution.py`、`mcp/loader.py`、`McpServers.tsx`。账户授权和已同步 Schema 哈希先过服务端校验。所有外部 MCP 调用均生成审批。服务端在同一远端会话检查最新 Schema，发出操作前复查本地授权和修订号。 | 定向测试覆盖旧 `read`、Schema 变化及临执行前的撤销。 | `read` 请求格式和数据库值仍被接受，客户端统一显示「每次确认」。旧待确认记录没有哈希，升级后需重新发起。Schema 一致时远端仍可能改变内部实现，超时后应先核实副作用结果。 |
| P1 普通单聊预算 | 输入裁剪和工具轮次检查曾由岗位分支条件启用。 | `chat_service.py`、`config.py`、`api/.env.example`。普通单聊在纯文本、原生工具调用、ReAct 和多模态路径共用预算逻辑，限制附件及召回文本，逐轮保留完整协议消息，预留回答和图片预算。 | 普通单聊带长附件、长历史的实际服务入口测试通过。工具调用配对回归通过。 | 接口和 SSE 事件沿用。默认窗口 32768，回答预留 2048，可配置 `CHAT_CONTEXT_WINDOW` 和 `CHAT_RESERVED_OUTPUT`。模型与图片 Token 采用估算，额度需匹配部署模型的窗口。 |
| P1 全局搜索语义 | 传入向量门槛时跳过 Elasticsearch BM25。三路检索原先各自在同一数据库会话解析并调用 Embedding。 | `rag/search.py`、`search_service.py`、`career_rag_eval.py`。文档和图片的短语命中先按 BM25，再追加超过余弦阈值的向量邻居。全局 Embedding 复用一次，失败时保留短语通路。 | 定向回归覆盖短语命中、向量门控、租户过滤和无向量回退。40 条标注查询在真实 ES 8.17 与本地 BGE 上完成。 | 返回结构沿用。短语匹配按索引分词定义，BM25 分数归一到 0–1，追加的向量结果保留原始余弦分数。两类分值用于各自排序。Neo4j 记忆搜索仍采用现有语义门槛。 |
| P1 长工具结果 | 只有单条上限，过期清理依赖新写入，回读次数无界。 | `tool_results.py`、`agent_runtime_model.py`、`84c297ea9e13`、`celery_app.py`、`tasks/beat.py`。同账户并发写受事务锁和条数、密文字节配额约束。Redis 限制回读，Beat 定期删除过期行。 | 真实 PostgreSQL 与 Redis 验证并行写、分页、岗位隔离、跨客户端限频和过期清理。 | 七天到期、旧引用 ID、加密格式和分页格式沿用。额度满时保留可读摘录。Redis 不可用时暂停引用回读，清理速度取决于 Beat 调度。 |
| P1 Worker 故障 | 既有续租和恢复逻辑缺少对取消、退避和最终草稿接管的组合验证。 | `career_worker.py`、`career_worker_load.py`、`test_agent_reliability.py`。保持已有认领和状态机，补充失租取消、关闭释放、退避及接管回归。 | 本地真实 MySQL 中 16 次提交去重为 8 个任务，12 路认领约束下首轮为 4 个。确认旧执行拒绝写回、退避期不可认领、检查点和已保存草稿可接管。 | 原任务结构、业务幂等和状态沿用。尚需目标环境持续负载和真实进程异常退出后的恢复时间数据。 |
| P1 真实模型评测 | 固定脚本替代模型，对失败原因和供应商实际 Token 用量报告不足。 | `career_workflow_eval.py`。沿用固定案例，报告失败原因、供应商已返回的用量和检查点类型，保留 `--live-user` 模式。 | 脚本约束及任务结果均为 4/4，恢复 2/2，有效提交 4/6。两次无效提交为故意注入。真实模型指标待验收。 | 评测无需改业务数据库。实时模式使用合成输入和回调替身，适合测模型选题及修复。真实数据库恢复由 MySQL 集成单独验证。当前配置的模型服务不在本机运行环境的出站允许范围内。 |
| P1 审批竞态 | 上一版已有 Redis 原子消费，需要验证跨请求并发、账户隔离和过期。 | `test_agent_reliability.py`、`test_agent_runtime_integration.py`。测试通过 FastAPI 和 JWT 进入审批入口，连接真实 DB 与 Redis，远端适配器由测试替身记录执行次数。 | 无认证 401，其他账户和过期各 404，同一审批的两个并发请求只执行一次。撤销和 Schema 变化在定向测试中拒绝。 | Redis 审批键和 TTL 沿用。从最后一次本地授权校验到远端执行存在网络窗口，已送达远端的调用无法通过 Redis 撤销。 |
| P1 SSE 跨实例 | 已统一 Streams，待验证现有快照、游标和生产入口。 | `test_agent_runtime_integration.py`。对两套 API 和独立 Redis 客户端做自动化测试，再使用两个本地 Uvicorn 进程通过 HTTP 做恢复冒烟。 | 真实 Redis 重放无重复。末尾游标和过期游标返回空闲，跨账户无法读取。两个进程的 PostgreSQL、Redis、ES 和 Neo4j 均健康。 | 现有游标和消息格式沿用。负载均衡器的 SSE 缓冲、空闲超时，以及 Redis 故障切换仍须在目标环境验证。 |
| P2 自适应训练 | 既有回放缺少同题数的非自适应对照和明确的后续观察窗口。 | `career_attempt_replay.py`。在同一归档候选目录内比较选题覆盖，从草稿生成时间观察后续作答。 | 本地回放 2 个岗位范围、7 份计划，无符合条件的薄弱历史或后续样本。 | 仅读历史数据，输出聚合结果。归档候选目录受当时策略影响，且计划窗口可重叠，收益仍需对照样本。 |
| P2 监控 | 队列健康靠即时日志，无法查历史趋势和恢复状态。 | `career_worker.py`、`agent_runtime_model.py`、`e43bb0cd41a2`、`tasks/beat.py`。PostgreSQL 分钟快照跨实例去重，记录告警出现与消除，保留 30 天。 | 真实 PostgreSQL 临时表验证同一分钟去重、告警触发和恢复。Trace 与已有页面回归通过。 | 通过数据库和日志查看队列状态，暂无外部告警投递或值班处理系统的验收结果。 |
| P2 历史代码与启动 | 旧目录同时保留历史源码和 MySQL 迁移。冷启动首次加载分词词表依赖出站网络。 | `docs/README.md`、`python-runtime-operations.md`、`api/Dockerfile`。标明 Python 运行入口与历史迁移目录，构建镜像时预热词表。 | 本地重现未缓存词表时的启动失败，并在本地缓存可用时通过双进程启动。前端生产构建通过。 | `backend/src/main/resources/db/migration` 仍作为 MySQL 迁移输入。Docker 构建节点需能取得已锁定的词表。生产镜像构建和发布待验收。 |

## 检索与部署复验

普通 RAG 在 40 条标注查询上的 Recall@5 为 90%，全局搜索模式为 88.75%。本机检索阶段 P95 分别是 38.44 ms 和 38.74 ms。受控向量的真实 ES 回归另外确认了低余弦的短语命中得到保留、仅向量命中且相关性不足的条目被剔除、无 Embedding 时短语仍可用、跨账户文档不会返回。

在配置了本地 PostgreSQL、MySQL 和 Redis 的工作区，从 `api` 目录执行。

```powershell
uv run --locked alembic upgrade head
uv run --locked ruff check app tests eval
$env:RUN_AGENT_RUNTIME_INTEGRATION = "1"
uv run --locked python -m unittest discover -s tests
uv run --locked python -m eval.career_worker_load
uv run --locked python -m eval.career_workflow_eval
```

有授权的测试模型时，追加 `python -m eval.career_workflow_eval --live-user <测试用户UUID>`。本地记录回放使用 `python -m eval.career_attempt_replay --user <用户UUID> --job <岗位UUID>`。生产验收使用独立测试账户和现有 Compose 服务。

1. 备份 PostgreSQL 和 MySQL，统一 API、Worker 的 `FERNET_KEY`。先执行 PostgreSQL 新迁移，再更新 API 副本。归档表索引创建期间可能阻塞同表写入，大表在维护窗口执行。
2. 完成所有 API 副本升级后再开放外部 MCP 工具调用，重新生成升级前的待确认请求。确认查询权限、审批一次性和远端工具版本变化的响应。
3. 用实际反向代理验证两个 API 副本之间的 `Last-Event-ID` 续传。记录真实模型 Token、任务质量以及 Worker 重启后恢复到终态的耗时。
4. 用 `career_queue_samples` 的 `sampled_at`、`queued`、`expired_leases`、`oldest_wait_seconds` 和 `alert` 对照 Worker 日志。告警条件为存在过期租约或最长队列等待超过 300 秒。结合已有 Trace 页面读取模型调用 P95、Token 和任务失败。目标环境告警渠道应验证收到触发与恢复两类消息。
