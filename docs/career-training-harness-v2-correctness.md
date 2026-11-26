# TRAINING Harness V2 正确性与策略验收

本轮以 GitHub `main` 的 `723340d34502abc1651a39b5ab40bec5bf08789e` 为基线。验收使用 Windows、Python 3.12.13、MySQL 8.4.13、锁定依赖和本地模型替身。

## 复现与修复

| 问题与源码位置 | 修复前复现或检查结果 | 修复后行为 |
| --- | --- | --- |
| 自然语言误识别，`career_training_contract.py` | 「不要安排五道题」「最多安排五道题」「如果有时间就安排五道题」都落为精确 5。`_REQUIRED.search` 将「不要复习 Redis」转成必备技能 | 有限规则按完整子句判定 `CONFIRMED`、`NEGATED`、`AMBIGUOUS`、`CONFLICTING`、`UNSUPPORTED`。否定、条件和近似题量保留原文。上下限和区间要求确认精确量。明确更正可替换本轮较早值。API 显式字段优先，之后是可确证本轮指令、确认的会话值和岗位推导规则。契约记录识别状态及获选来源 |
| Pinned 截止日漂移，`career_context_versions.py`、`career_chat_context.py`、`career_training_contract.py` | 11 月 26 日保存的「明天」在两次提交中分别得到 11 月 27 日和 28 日。版本只存原文本，任务创建时重新解析 | 确认时把原始值、规范化日期、IANA 时区、解析时点和来源消息固化到现有 `field_meta`。跨日提交和回滚使用同一绝对值。缺少依据的历史相对日期需要确认。固定日期过期会被拒绝，滚动窗口需要改写成固定日期 |
| Retry 与 Repair 混扣，`career_training_runtime.py`、`career_task_service.py`、`career_worker.py`、`career_queue.py` | 只预约首个修复模型请求，持久状态已经是 1 次请求和 1 轮修复。两次外部异常可以耗尽修复轮次 | 预约请求先记模型次数，结果进入验证并提交时才累计修复。临时重试由原队列及事务计数。无结果和接管时未知结果分开标记，已预约模型请求保留。模型调用上限、修复上限和累计时限分别执行 |
| 技能状态未决定配额，`career_learning_state.py`、`career_training_harness.py`、`career_question_catalog.py`、`career_training.py` | 原 V2 状态记录包含掌握度和置信度，候选匹配和集合覆盖主要消费技能是否命中。同一套多技能题库中，原 V1 与原 V2 的名额结果一致 | 可选效用策略使用掌握度、证据置信度、近期性、岗位技能和显式软偏好。先满足指定题、版本、题量、截止日期、技能、复习顺序和完成题排除，再分配剩余名额。多技能题只贡献一个最大软效用，连续选同技能的边际效用递减。模型获得冻结的推荐题与理由，结果记录实际题目采纳 |
| 预检只证明技能覆盖，`feasible_questions`、`verify_plan` | `Redis+Python` 与 `MySQL` 可达到技能覆盖，却无法按 `Redis → MySQL → Python` 首次出现的顺序完成 | 搜索选题时同时证明排程可行。截断到 30 道后再找见证并保存精确题号、版本与顺序。搜索取不到证据且到达工作量上限时返回 `TASK_CONTRACT_FEASIBILITY_UNDETERMINED`。搜索完整后无解返回 `TASK_CONTRACT_UNSATISFIABLE` |
| 阶段语义不足，`prioritySkills`、`PRIORITY_ORDER_MISMATCH` | 默认检查首次位置，`Redis → MySQL → Redis` 合法，无法表达阶段不交错 | 默认仍为 `FIRST_OCCURRENCE_ORDER`。用户明确选择或表达先完成一阶段再开始下一阶段时采用 `STRICT_PHASE_ORDER`。多技能题归入最早覆盖的优先阶段，每个严格阶段至少有一题。顺序按排程及题目引用次序检查，同一日仍有顺序 |
| 工作流效果证据，`eval/harness_v2_eval.py` | 原 19 例使用模型替身，缺少扩展用例、分母拆分和多次运行输出 | 保留原入口，增加组选择、重复运行、逐案例结果和六项扩展情境。报告分开统计可满足任务、错误接收、错误拒绝及预期澄清。真实模型路径继续需要明确授权，当前轮次选择本地替身 |
| 学习策略评测，`eval/career_training_harness_eval.py`、`eval/career_attempt_replay.py` | 原 D/E 主结果一致，观察性回放的相邻计划可能重复计量后续作答 | 新增四组独立、同硬约束的名额评测。历史回放在任务创建时间切分训练证据，后续观察窗口以下一计划为上界，并按作答 ID 去重。独立题后续作答单列为观察性统计 |
| 无效手动重试，`CareerQueue.retry`、`TaskHistory.tsx` | `FAILED` 可以直接回队，预算已耗尽也会再次失败 | 按结构化错误码和剩余预算判定，原任务的重试与暂停恢复共用服务端检查。可恢复任务保留原预算、契约和目录。耗尽后页面引导创建新计划，新的 `requestId` 关联用户同岗位的 `restartTaskId`。重复原请求仍返回原任务 |

## 实现与兼容性

- 契约版本 2 写入显式顺序模式与新预算。新任务最多 5 次模型预约、2 次自动临时重试、2 轮进入验证的修复和 300 秒累计时限，原有单次 Worker 85 秒限额继续生效。既有契约版本 1 沿用签发时的模型上限和选题顺序语义，存量计数保留，后续完成的修复按新计账处理。留存的已验证草稿可以在接管后直接提交。
- 现有 MySQL `context_json`、`training_runtime_json`、`details_json` 与 PostgreSQL `field_meta` 承载新增字段。Pydantic 为旧行补读缺省值。MySQL 写入仍校验执行代次与租约，返回验证结果还校验当前预约操作 ID 和状态。状态写入不依赖模型文本。没有新增 SQL 迁移，V1–V20 仍为本轮兼容基线。继承的截止日继续以原确认时区作为日历基准，新提出的相对日期使用本轮时区。
- 排程预检使用技能覆盖和优先阶段归属搜索，优先尝试最稀缺的未覆盖约束，保留精确版本并禁止选同 ID 多次。日期窗口由契约验证，合法日期都可在起止窗口内按步骤顺序安排。缺题、指定版本或排程冲突在入队前发现。模型生成的文本质量和未经确认的经历引用仍由最终验证和原有语义评估入口检查。
- 配置 `CAREER_TRAINING_LEARNING=objective-practice-v2-utility` 启用效用策略，默认仍为 `objective-practice-v1`。原 `objective-practice-v2` 可单独选择。`CAREER_TRAINING_UTILITY_WEIGHTS` 接受 `TrainingUtilityWeights` 定义的 JSON 字段，例如 `{"weak":2.1,"dueReview":0.9}`。权重与推荐理由随任务冻结。岗位技能使用等权默认值和相同岗位加成，未使用自报难度或岗位重要度评分。

## 评测结果

### 可比较的 19 个工作流案例

V1 使用 `723340d` 的原生成、校验、重试和目录检查点。原 V2 使用该提交的 D 组，新 V2 使用本轮 D 组。输入、题库、故障响应和输出验收相同。原 V2 合约的默认模型预约上限为 3，新版为 5。这批案例没有因该差异改变结果；下面的故障对照将两版上限都固定为 5。

| 指标 | V1 | 原 V2 | 修复后 V2 |
| --- | ---: | ---: | ---: |
| 全部场景成功 | 11/19 | 17/19 | 17/19 |
| 可满足场景成功 | 11/17 | 17/17 | 17/17 |
| 已保存计划硬约束通过 | 11/18 | 17/17 | 17/17 |
| 错误接收 | 7/18 | 0/17 | 0/17 |
| 可满足任务未保存 | 0/17 | 0/17 | 0/17 |
| 首次候选通过 | 4/18 | 7/17 | 7/17 |
| 修复成功 | 7/14 | 10/10 | 10/10 |
| 模型调用总数 | 26 | 24 | 24 |
| 检查点恢复 | 2/2 | 2/2 | 2/2 |

新版扩展到 25 个场景。整份重生成和定向修复在相同上限下都完成 **22/22** 个可满足任务。两组均正确处理其余 3 例，分别是题库不足、模型输入预算不足和题量范围需要确认。可满足任务的错误拒绝为 0/22，已保存计划的错误接收为 0/22。两组各有 11/22 首次通过和 11/11 修复成功。调用分别为 33 次和 30 次，平均 1.32 与 1.20 次每场景。一次本地 P95 分别为 10.0 和 9.5 毫秒，受本机调度影响。真实模型的 Token 和供应商延迟缺失。

### 5 个故障用例的同预算对照

在独立的 `723340d` 源码和当前源码中运行同一故障脚本。限额保持 5 次模型预约、2 次修复和 2 次临时重试。模型替身只有返回结构化内容才计入有效修复。

| 故障用例 | 修复前 | 修复后 | 模型预约前 → 后 | 有效修复前 → 后 | 暂时性重试 |
| --- | --- | --- | ---: | ---: | ---: |
| 初稿超时 | 成功 | 成功 | 2 → 2 | 0 → 0 | 1 |
| 修复超时后恢复 | 成功 | 成功 | 3 → 3 | 1 → 1 | 1 |
| 修复时依次超时、限流 | 提前耗尽修复预算 | 成功 | 3 → 4 | 0 → 1 | 2 |
| 两个修复候选都不合法 | 达到修复上限 | 达到修复上限 | 3 → 3 | 2 → 2 | 0 |
| 预约修复后中断 | 成功 | 成功 | 3 → 3 | 1 → 1 | 0 |
| 合计 | 3/5 | 4/5 | 14 → 15 | 4 → 5 | 4 |

持久化修复计数从 8 降到 5，提前终止从 1 例降到 0 例。多出的 1 次模型调用完成了原先错误终止的计划。即时故障的模型退避及租约接管另外由 MySQL 集成测试验证。

### 独立学习策略评测

10 个固定证据集，42 个题目名额。四组使用同一岗位、题库、作答历史、题量、指定题和硬约束求解器。薄弱、新题探索以及需要巩固的技能依据夹具设计标注，分数不参与结果评分。新题以精确版本判定。

| 指标 | A 岗位匹配 | B 原 Learning V1 | C 原 Learning V2 | D 效用排序 |
| --- | ---: | ---: | ---: | ---: |
| 岗位技能覆盖 | 30/30 | 30/30 | 30/30 | 30/30 |
| 薄弱技能的新题覆盖 | 6/6 | 6/6 | 6/6 | 6/6 |
| 探索技能的新题覆盖 | 14/14 | 14/14 | 14/14 | 14/14 |
| 定期巩固命中 | 1/1 | 1/1 | 1/1 | 1/1 |
| 相关新题数 | 28/42 | 28/42 | 28/42 | 41/42 |
| 已练过的题目 | 14/42 | 14/42 | 14/42 | 1/42 |
| 补弱额外新题名额 | 0/42 | 0/42 | 0/42 | 6/42 |
| 指定题保留 | 10/10 | 10/10 | 10/10 | 10/10 |

多薄弱技能时，D 组在满足覆盖后把空余名额分给 Redis 与 MySQL。近期 Redis 表现改善时，额外名额转向仍薄弱的 MySQL 和待探索的 Python。固定模型回归测试还确认，模型可以读取最终冻结的推荐，Redis 改善前后的最终计划包含不同的题目。采纳计数按保存计划与候选推荐交集计算。真实采纳率和后续独立题的作答效果仍缺观测。

## 修改文件和验证范围

| 文件 | 变更及验证 |
| --- | --- |
| `api/app/services/career_training_contract.py`、`career_training_verifier.py` | 解析状态、两种顺序和同一可行性规则。单测覆盖否定、范围、明确更正、旧契约、跨阶段题、截断与复杂度保护 |
| `api/app/services/career_context_versions.py`、`career_chat_context.py`、`chat_service.py`，`api/app/controllers/chat_controller.py` | 保存时锚定日期，读取和回滚保留元数据。测试覆盖跨时区、午夜、旧值待确认、回滚和会话混合输入 |
| `api/app/services/career_training_runtime.py`、`career_task_service.py`、`career_queue.py`、`career_worker.py` | 持久化预约、重试和修复计数及错误分类。MySQL 验证取消、两次瞬态失败后成功、接管、并发手动重试、幂等回读与过期执行者写保护 |
| `api/app/services/career_learning_state.py`、`career_training_harness.py`、`career_question_catalog.py`、`career_training.py` | 计算并应用软效用、占用名额与采纳。通过四组确定性评测及模型替身生成回归 |
| `api/app/controllers/career_task_controller.py`、`api/app/config.py`、两个 `.env.example`、`docker-compose.prod.yml` | 新计划来源校验和策略配置。现有默认策略维持 V1，数据继续按认证用户和岗位查询 |
| `api/eval/harness_v2_eval.py`、`harness_retry_eval.py`、`career_training_harness_eval.py`、`career_attempt_replay.py` | 工作流、故障与独立策略对照、只读时序回放。既有 `harness_v2_replay.py` 复用版本化验证器继续运作 |
| `api/tests/test_career_training_v2.py`、`test_career_training_v2_mysql.py`、`test_career_chat_tools.py`、`test_agent_runtime_integration.py` | 新增回归并更新反映旧行为的断言 |
| `web/src/api/chat.ts`、`careerWorkflow.ts`、`web/src/pages/TrainingPlanPage.tsx`、`career/TaskHistory.tsx`、`career/TrainingPlanCard.tsx`、`chat/CareerContextButton.tsx` | 日期确认及显示、阶段顺序、采纳数、后续操作提示。TypeScript 和前端生产构建 |

隔离 MySQL 的任务恢复测试验证了旧执行代次无法写入运行状态和草稿，已预约本地修复在退出前没有计为有效修复，接管后以同一契约修复并可脱敏回放。两次外部故障后成功的任务保存 `modelCalls=4`、`transientRetries=2`、`repairRounds=1`。队列负载测试继续通过 16 次提交去重、12 个认领请求、并发上限 4，以及退避和旧草稿恢复。

完整 Python 回归发现 87 项，79 项通过，8 项 PostgreSQL/Redis 集成测试因环境门控跳过。通过现有 V20 迁移和校验和检查、Ruff、TypeScript 类型检查及 Vite 生产构建。Vite 仍报告既有的分块大小及混用导入提示。

## 复跑命令和边界

以下命令从 `api/` 运行。MySQL 集成测试需要将 `CAREER_MYSQL_*` 指向已迁移的本机一次性数据库，并将 `CAREER_HARNESS_MYSQL_TEST_DB` 设为同名的 `harness_v2_*` 数据库。

```powershell
uv run --locked python -m unittest discover -s tests
uv run --locked ruff check app
uv run --locked python -m scripts.migrate_career_mysql
uv run --locked python -m eval.career_worker_load
uv run --locked python -m eval.harness_v2_eval --groups AD --details
uv run --locked python -m eval.harness_v2_eval --groups CD --extended --details
uv run --locked python -m eval.harness_retry_eval
uv run --locked python -m eval.career_training_harness_eval --policies
uv run --locked python -m eval.career_attempt_replay --user <authorized-owner> --job <job>
```

原版对照可在 `723340d` 独立检出后运行原 `eval.harness_v2_eval`，以及将同一份 `eval/harness_retry_eval.py` 放入其 `api/eval/` 复跑。需要真实模型时，准备授权的测试账号，固定模型版本、温度和同一模型配置，再运行 `python -m eval.harness_v2_eval --live-user <authorized-user> --groups ACD --repeat 5 --details`。在原版本上对同一 19 个案例重复运行原 `--live-user` 命令。`--extended` 可补测新版的额外场景。真实评测可以另启 `--semantic`，语义调用与生成指标分开解释。

本轮按用户选择执行本地模拟评测。真实模型、真实账号历史、供应商 Token 和生产延迟没有实测数据。PostgreSQL/Redis 的完整联调仍需隔离服务，日期持久化接口、修改和回滚已在仓储替身上覆盖。搜索上限可能使大规模目录出现可行性待定，诊断与确定无解分别报告。
