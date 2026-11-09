# Search Agent v1 启动与验收

后续训练检查点和实测见[训练步骤恢复与模型基线](career-agent-training-checkpoints.md)。

按[本地启动说明](career-agent-day-1-2026-11-06.md#本地启动)启动存储和三个应用。从 `api/.env.example` 创建本地配置，按模板说明生成 `FERNET_KEY`。使用已有 PostgreSQL 时，沿用原有加密密钥。Java 与 Comet 使用相同的 JWT 签名密钥、算法和内部服务令牌。打开 [本地网页](http://localhost:5173)，确认 [求职服务](http://localhost:5173/api/career/health) 和 [Comet 存储](http://localhost:5173/api/health) 都已就绪。

## 从岗位走到投递

1. 登录 Comet。在「岗位与公司」录入一份目标 JD，保留招聘来源与记录日期。在「简历与经历」确认至少一条与岗位相关的真实经历。演示时可使用独立测试账号和示例 JD，如「Java 后端实习，要求熟悉 Java 集合、MySQL 和 HTTP」。演示经历仅用于该测试账号。
2. 在「设置 → 模型配置」添加对话模型，启用 `function_call`，设为默认并测试连接。DeepSeek 官方接口可用模型名 `deepseek-flash`，Base URL 为 `https://api.deepseek.com`。求职任务请求使用非思考模式，以便指定工具。 [DeepSeek Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)
3. 在「岗位训练计划」选择该岗位及后端开发方向。等任务成功后，打开计划中的一道题，提交答案，查看解析。回到计划页生成复习建议。刷新页面可回查计划、作答和建议。
4. 在「模拟面试」选择同一岗位和题目，提交开放回答，查看一轮复盘。在「岗位简历版本」选择已确认的经历，生成草稿，查看事实依据并打印为 PDF。
5. 在「网申助手」为同一岗位关联简历，填写表单答案草稿。用户自行在招聘网站完成投递后，可在「投递看板」更新阶段。演示时用测试记录验证阶段历史。

公开面经和练习题由 Flyway 导入，页面显示来源和版本。浏览与刷题、生成简历草稿以及维护网申与投递记录可以独立于模型配置使用。完整操作入口见[题库和错题](career-agent-day-3-practice.md)及[岗位训练和申请材料](career-agent-day-4-5-workflow.md)。

## 复跑检查

| 模块 | 命令与前置条件 |
| --- | --- |
| Java | 在 `backend` 运行 `./mvnw.cmd verify`。先设置 `CAREER_TEST_MYSQL_URL`、`CAREER_TEST_MYSQL_USER` 和 `CAREER_TEST_MYSQL_PASSWORD`，指向独立的 MySQL 测试库 |
| Python | 在 `api` 运行 `uv run --locked ruff check .` 和 `uv run --locked python -m unittest discover -s tests -p 'test_career_*.py'` |
| 前端 | 在 `web` 运行 `npx tsc --noEmit` 和 `npm run build` |
| 真实模型 | 在 `api` 运行 `uv run --locked python -m scripts.check_model_tool_call <用户名>`，再完成上述第 3、4 步中的计划、复习与面试 |

## 交付验收

| 检查 | 实测 |
| --- | --- |
| Java 与数据库 | MySQL 8.4.13 从空库迁移 V1 至 V6，10 项 Maven 集成测试通过，覆盖身份校验、跨账号隔离、题目版本、重试去重、简历快照与投递历史 |
| 浏览器流程 | 使用新的本地应用配置、空 PostgreSQL 和空 MySQL 启动，通过 Comet 注册登录，保存加密的模型配置。Chrome 验证训练失败重试、计划内作答、复习、模拟面试、打印 PDF、网申草稿、投递历史回读及跨账号隔离。模型响应使用本地替身 |
| 任务中断恢复 | 训练任务进入第 1 次执行且已向模型发起请求后，终止并重启 Java。两分钟租约到期后，服务自动重新领取同一任务，第 2 次执行成功，历史中只有一份计划 |
| 模型保存 | 复现网页入口返回 500。按当前配置重启本机 Comet 后，同一入口成功保存临时 DeepSeek 配置，验证后已清理。新增回归测试检查无效 `FERNET_KEY` 的错误提示 |
| 静态检查与构建 | Python Ruff 和 5 项求职测试通过。前端 TypeScript 和生产构建通过 |
| 真实模型 | 2026-11-09 使用 `deepseek-flash` 完成训练、复习和面试，详见[真实模型基线](career-agent-training-checkpoints.md#真实模型基线) |

Flyway 提示当前版本的已验证 MySQL 范围。Vite 构建仍有包体积和混合导入提示。

## 可凭证说明的项目工作

- 在 Comet 上接入 Spring Boot 求职服务，通过统一登录身份隔离经历、岗位、作答和申请材料，使用 MySQL 与 Flyway 管理求职业务表。
- 用持久化任务、执行租约和按用户的请求幂等键衔接 Python Agent 与 Java。训练计划写入时校验任务归属、题目版本和执行代次。
- 保留练习题与评分版本、简历事实快照及投递阶段历史，支持刷新后回查。实测范围见上表。
