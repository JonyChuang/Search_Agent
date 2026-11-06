# 经历档案与岗位记录

对应[逐日交付计划](career-agent-delivery-plan-2026-11-12.md)的第二个里程碑。在[第一天本地启动流程](career-agent-day-1-2026-11-06.md)的基础上，启动 Java 前在其终端设置与 `api/.env` 一致的 `JWT_SECRET` 和 `JWT_ALGORITHM`。默认算法 HS256 要求密钥至少 32 字节。HS384 和 HS512 分别要求至少 48 和 64 字节。若此前使用短密钥，更新两处配置并重启服务，随后重新登录。Java 使用 Spring Security 验证 Comet 签发的访问令牌。[Spring Security JWT 文档](https://docs.spring.io/spring-security/reference/6.5/servlet/oauth2/resource-server/jwt.html)

Flyway V2 扩展 V1 的 `career_profile` 并新增 `career_experience` 与 `career_job`。岗位记录含用户填写的公司名称，便于下一阶段按岗位准备。用户的经历和岗位通过令牌中的 Comet 用户 UUID 查询，浏览器填写的用户标识不会改变记录归属。

## 使用

1. 使用 Comet 账号登录，从「求职准备」打开「简历与经历」。填写求职目标、毕业月份和偏好，然后新增一条教育、科研、项目或实习经历。核对事实后勾选确认。
2. 打开「岗位与公司」，新增公司、岗位、JD、招聘来源和记录日期。已知来源链接时可同时保存。
3. 刷新页面检查已保存的内容。换另一个账号登录，确认只显示该账号自己的资料。两个页面支持编辑和删除记录。

| 接口 | 用途 |
| --- | --- |
| `GET /api/career/profile`、`PUT /api/career/profile` | 读取或保存个人求职档案。未填写时返回 `data: null` |
| `GET /api/career/experiences`、`POST /api/career/experiences` | 列出和新增经历 |
| `GET /api/career/jobs`、`POST /api/career/jobs` | 列出和新增岗位 |
| `GET`、`PUT`、`DELETE` `/api/career/{experiences或jobs}/{id}` | 读取、更新或删除当前用户的一条记录。其他账号访问同一 ID 返回 404 |

业务接口沿用 `code/message/data`，无效访问令牌返回 HTTP 401。页面走本地 Vite 的 `/api/career` 代理。若默认端口 8080 已占用，在 Java 和 Vite 启动终端为 `CAREER_BACKEND_PORT` 设置相同的可用端口。

## 验收

- MySQL 8.4.13 上的 Maven `verify` 通过。4 项集成测试覆盖令牌签名、过期时间和类型、已有档案更新、经历确认、招聘来源、跨账号读写隔离。Flyway 提示该版本尚未列入其已验证的 MySQL 版本，V1 和 V2 均执行成功。
- Chrome 中验证了设置默认展开、两页空状态、创建档案和经历、录入带来源的岗位，以及刷新后的数据回读。使用 Comet 签发函数生成令牌，账号资料接口使用测试替身，求职请求经 Vite 到 Java 和真实 MySQL。
- 前端 `npx tsc --noEmit` 和 `npm run build` 通过。构建有既有的包体积和混合导入提示。
- Python `uv run --locked ruff check .` 通过。

复跑数据库测试时，将 `CAREER_TEST_MYSQL_URL`、`CAREER_TEST_MYSQL_USER` 和 `CAREER_TEST_MYSQL_PASSWORD` 指向独立测试库，再从 `backend` 运行 `.\mvnw.cmd verify`。未设置测试库地址时，Maven 跳过这组集成测试。

## 登录正常但求职页面提示无法验签

求职接口返回 401 时，前端会向 Comet 确认会话。Comet 确认会话有效时，页面保留登录并显示重试入口。

从 `api` 目录启动 Comet 时，配置通常来自 `api/.env`。使用仓库根目录的 Compose 启动时，默认使用根目录的 `.env`。启动终端的环境变量也可能覆盖文件配置。核对当前运行的 Comet 实际使用的 `JWT_SECRET` 和 `JWT_ALGORITHM`，让 Java 使用同一组值。若 Comet 仍使用模板里的短密钥，先生成符合算法长度要求的新密钥并配置到两端，再重启 Comet 和 Java，重新登录。
