# Search Agent 完整规划交付

## 使用入口

| 功能 | 使用方式 |
| --- | --- |
| 组题练习 | 备考中心 → 开始练习。按岗位、主题或题型开始一组，退出或刷新后继续。已交答案和未交题目都能从同一进度恢复。可根据复盘生成新版计划并回查上一版。 |
| 编程与 SQL | 备考中心 → 开始练习 → 编程与 SQL。提交后查看用例结果和判题记录。 |
| 计划与提醒 | 求职进展 → 计划与提醒。可关联岗位，安排复习、面试和投递截止提醒。启用站外提醒时，使用账号已开启的通知渠道。 |
| 岗位操作 | 求职助手 → 岗位操作。为当前岗位创建文字模拟面试、简历草稿或网申草稿，从结果卡打开记录。简历草稿引用已确认的经历。 |
| 任务中心 | 备考任务可查看运行状态、暂停、继续或取消。运行统计显示近 30 天任务与已记录步骤的 Token。 |
| Skill | 设置 → 技能中心。可复制六个求职模板，也可从 ZIP 或 GitHub 固定提交预览、安装、更新、回退和卸载。 |

Java 的 Flyway 迁移到 `V19`。Python 的 Alembic 迁移到 `f48c07e29bd1`。启动已有项目时，在 `api/` 执行 `uv run alembic upgrade head`，再重启两个后端。Java 随启动应用 Flyway 迁移。

## 判题执行器

Java 使用 Judge0 的配置、提交和状态接口。可以连接独立部署的 Judge0 CE，或运行仓库的本地 Docker 执行器。判题服务需要同时关闭 `ENABLE_NETWORK` 与 `ALLOW_ENABLE_NETWORK`。外部沙箱应部署在独立的受控地址，配合 `CAREER_JUDGE0_TOKEN`。Judge0 CE 1.13.1 的 Linux 和 cgroup 要求见官方发布说明。 [Judge0 CE 发布说明](https://github.com/judge0/judge0/releases/tag/v1.13.1) · [Judge0 API](https://ce.judge0.com/)

本地模式使用已有 Docker Engine 和 Python，以下以 PowerShell 为例。

```powershell
docker pull python@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff
$env:CAREER_JUDGE0_TOKEN = [Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$env:CAREER_JUDGE0_URL = 'http://127.0.0.1:2358'
python tools/career-judge/runner.py
```

Java 启动时使用相同地址与 token，Python 语言编号为 `71`。如果 Docker 命令不在 PATH，可以为执行器设置 `CAREER_JUDGE_DOCKER` 为对应的 Docker CLI 绝对路径。执行器只监听 `127.0.0.1`，每个用例使用一个独立、禁网、只读根目录、无宿主文件挂载的容器，并限制进程数、CPU、内存、执行时间和输出量。SQL 使用初始化后的临时 SQLite 数据库，按查询结果判题。判题服务仅对 Java 返回状态和通过用例数。 [Docker 资源限制](https://docs.docker.com/engine/containers/resource_constraints/)

## Greenhouse 网申

1. 在 Chrome 或 Edge 扩展程序页打开开发者模式，选择「加载已解压的扩展程序」，加载 `tools/greenhouse-extension/`。
2. 在岗位与公司填入 `https://job-boards.greenhouse.io/<公司>/jobs/<岗位编号>` 形式的招聘地址。在网申助手选好简历，保存邮箱和其他材料，填写官网使用的姓名并下载填表凭证。
3. 从简历预览保存本次投递的 PDF。打开招聘页，在扩展导入凭证和 PDF，根据提示授权连接 Search Agent 后点击「填写官网表单」。
4. 扩展填写未填写的姓名、邮箱、电话和简历。核对官网字段、附件以及验证问题。确认本次投递后点击「我已核对，提交这份申请」。
5. 出现可识别的官网确认后，在扩展选择「读取官网回执」。扩展关闭后可重新导入原凭证。也可根据官网或邮件在网申助手手动记录回执。提交结果待核对期间，系统保留材料版本，并拒绝再次使用提交凭证。

凭证包含本次使用的联系方式，限指定岗位和草稿版本，24 小时有效。确认状态以页面显示为依据。其他域名、招聘网站自定义必填项及验证码由用户在浏览器处理。 [Chrome activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab) · [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)

## Skill 包格式

ZIP 根目录放 `manifest.yaml` 和 `SKILL.md`，可附加 `references/` 中的 Markdown 或文本。GitHub 导入使用公开仓库地址与完整的 40 位提交号。每个版本有内容摘要，预览与安装必须对应同一个包。

```yaml
id: career-notes
name: 求职面经整理
version: 1.0.0
description: 整理资料里的面试题和出处
entry: SKILL.md
tools: [knowledge_search, datetime]
```

可声明的只读工具为 `datetime`、`knowledge_search`、`memory_search`、`web_search`。新增工具可在技能编辑中选择，并适用账号的工具权限与配置。技能内容由文本和参考资料组成。

## 上下文和评测

求职对话按账号、对话和岗位筛选历史。保留最近八条消息，旧内容优先提取用户确认的约束，每段摘录关联原消息 ID。长附件单独分配预算，给用户问题留出空间。任务恢复沿用已有的资料版本与步骤检查点。客观题学习反馈从当前岗位和题目版本的作答记录读取，供复习使用。

在 `api/` 执行 `uv run python -m eval.career_context_benchmark` 可复跑三个固定合成用例。使用 `cl100k_base` 估算历史片段大小，固定最近 40 条基线为 73,606–95,206 Token，按预算装配后为 3,752–3,765 Token。三个用例均找回最早的指定约束及其原消息，并保留最近一轮的完整结果。测量覆盖本地装配和约束回查，未调用模型。多 Agent 与离线强化学习按原规划作为有模型对照数据后的选项。

配置 `api/eval/.env.eval` 的 `EVAL_CHAT_*` 后，可加 `--with-model` 复跑两组共六次合成请求。选用支持至少 100,000 输入 Token 的模型。输出记录实际输入、输出、耗时和约束回查是否命中。

## 验收记录

- MySQL 8.4 从空库迁移至 V19，通过 Java 测试。PostgreSQL 16 从空库应用 Alembic 迁移，验证 Skill 安装、更新、回退、卸载及跨账号隔离。临时 Redis 验证同会话互斥、同用户限额与旧执行者释放保护。
- 浏览器回归使用打包后的页面和隔离后端，覆盖私有资料出题、公开面经审核、题目版本、练习刷新续做、任务指标和申请回执。判题使用实际 Docker 容器验证通过、错误、超时、SQL 只读和网络限制。
- 站外提醒使用本地接收端核对，Greenhouse 使用合成表单验证。真实站点确认页面及新版模型质量对照尚待实测。前端打包通过，仍有上游包体积和混合导入提示。
