# 第三天 · 面经、题库与练习

对应[逐日交付计划](career-agent-delivery-plan-2026-11-12.md)的第三个里程碑。按[本地启动说明](career-agent-day-1-2026-11-06.md)运行 Java、Comet 和 React，使用 Comet 账号登录。Flyway V3 创建公共面经、题目版本和个人作答表，V4 导入首批资料。客观题由 Java 判分，使用此流程无需配置模型。

从第二天的环境升级时，用当前代码重新启动 Java 服务，让 Flyway 把现有求职库迁移到 V4。Java 启动日志显示已迁移或数据库已是 V4 后，再刷新题库页面。

## 使用

1. 从「面试训练」打开「面经与题库」，在「公开面经」查看原文链接、发布日期和整理日期。
2. 在「题库」或「刷题练习」选择后端开发、算法或大模型应用方向，点「开始作答」。
3. 选择一个选项并提交，查看判分、正确选项、解析和题目及评分版本。提交响应丢失时，同一浏览器标签页刷新后可重试原提交。
4. 答错后打开「错题本」，刷新仍可查看。点击「重新作答」会打开当前题目版本，答对后标为「已复习」，再次答错会回到「待复习」。「练习记录」可回查每次作答和当时的反馈。

首批公共内容含 2 篇候选人本人公开回顾的中文摘要和 6 道依据技术文档编写的原创单选题。公开回顾反映作者当时的个人经历。练习题在题库中标明技术参考来源。个人经历、岗位和练习记录按账号隔离。[软件开发实习回顾](https://blog.cloudflare.com/internship-experience-software-development-intern/#interview-experience) · [解决方案工程回顾](https://blog.cloudflare.com/china-silicon-valley-china/)

## 接口与数据

| 接口 | 用途 |
| --- | --- |
| `GET /api/career/interview-notes` | 读取已整理的公共面经 |
| `GET /api/career/questions?role=backend` | 按岗位方向列出当前题目版本。可选方向为 `backend`、`algorithm`、`llm` |
| `GET /api/career/questions/{id}` | 读取当前题干和选项 |
| `POST /api/career/practice/attempts` | 携带 `requestId`、`questionId`、`questionVersion`、`answer` 提交并取得反馈 |
| `GET /api/career/practice/attempts?page=1` | 分页读取当前账号的历史作答 |
| `GET /api/career/practice/wrong-questions` | 读取当前账号的错题次数和复习状态 |

同一用户用同一提交编号重试相同作答会取得原反馈。若提交编号已用于另一份作答，接口返回 HTTP 409。错题状态从作答记录计算，重试原提交不会累加错题次数。新增题目或修订题干、选项、答案和评分说明时使用新的 Flyway 迁移，修订在同一题目 ID 下插入新版本，保留历史版本供旧作答回查。

复跑 Java 集成测试时，使用[经历与岗位验收](career-agent-profile-jobs.md#验收)中的环境变量，将 Maven 指向独立 MySQL 测试库。

## 验收

- MySQL 8.4.13 从空库执行 V1 至 V4 成功。Maven `verify` 在独立构建目录通过，7 项集成测试覆盖原有档案与岗位、题库筛选、答案隐藏、服务端判分、并发重试、账号隔离和历史版本。Flyway 仍提示 MySQL 8.4 尚未列入当前版本已验证的范围。
- Chrome 通过 Vite、Java 和真实 MySQL 验证了面经来源、岗位筛选、提交响应丢失后的刷新重试、错题复做及历史回读。两个测试账号使用签名令牌，Comet 的账号资料接口使用测试替身。
- 前端 TypeScript 检查和生产构建通过，仍有既有的包体积与混合导入提示。Python Ruff 通过。
