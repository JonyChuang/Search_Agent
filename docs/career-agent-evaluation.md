# Search Agent 标注测试集评估

## 岗位对话约束保留

测试集包含 24 个手工编写的合成场景，覆盖简历、备考、模拟面试和网申，每个场景标注两条应保留的约束及其来源。每个场景分别放入 28、46、72 条消息的对话，形成 72 条测试对话和 144 次约束检查。各长度复用相同标注。对话中包含普通澄清问题、较长回复和中途修改的旧信息。

在同一批对话中比较固定最近 40 条消息、与现有方案等 Token 预算的最近消息、现有岗位上下文装配。现有方案复用实际服务的 `summarize`、`clip` 与 `turn_content`。计算约束召回时，正确值必须出现在对应来源消息保留的文本中。Token 数使用 `cl100k_base` 计算送入模型前的历史文本，含结构化摘录，范围为历史片段。执行采用本地离线评测。

| 方案 | 约束召回 | 两条约束均保留的对话 | 平均历史 Token |
| --- | ---: | ---: | ---: |
| 固定最近 40 条 | 120/144（83.33%） | 48/72 | 3,757.36 |
| 等预算最近消息 | 50/144（34.72%） | 0/72 | 1,844.26 |
| 岗位上下文装配 | 142/144（98.61%） | 70/72 | 1,845.36 |

与固定最近 40 条方案相比，约束召回提高 15.28 个百分点，平均历史 Token 减少 50.89%。两处遗漏来自同一个简历场景，其约束位于旧消息的第二句，摘录保留了第一句。

在 `api/` 复跑。输出包含每条对话、每个方案的命中数、遗漏值和 Token 数。

```powershell
uv run python -m eval.career_history_eval
```

[标注场景](../api/eval/fixtures/career_history_gold.json) · [评测脚本](../api/eval/career_history_eval.py)

## Java 任务调度与租约接管

在隔离的 MySQL 8.4.13 空库上应用 Flyway V1–V19，通过 Spring Boot 实际调用 `CareerTaskStore`。并发工作负载交叉组合 2、3、4 个用户，每用户 2、3 个岗位，以及 4、8 个并发工作线程。每种组合重复 3 次，每岗位入队两个任务，每个请求 ID 额外重放一次。逐轮核对认领顺序、并发边界、唯一任务 ID 和最终完成状态。

租约测试给已认领任务注入到期时间，分别覆盖写入检查点之前、题目目录落库后、计划草稿落库后，每阶段 8 次。核对重新认领的任务 ID、递增的执行代次、检查点以及旧执行者的写回结果。

| 检查项 | 实测 |
| --- | ---: |
| 并发工作负载 | 36/36 保持同岗位任务顺序及并发上限 |
| 任务认领 | 540 个任务全部完成，0 次重复认领 |
| 重复请求 | 540/540 返回原任务 |
| 租约到期接管 | 24/24 重新认领原任务 |
| 旧执行者回写 | 24/24 被拒绝 |

提供独立测试库并设置 `CAREER_TEST_MYSQL_URL`、`CAREER_TEST_MYSQL_USER` 和 `CAREER_TEST_MYSQL_PASSWORD`，在 `backend/` 复跑。

```powershell
$env:CAREER_TASK_EVAL = 'true'
.\mvnw.cmd '-Dtest=CareerTaskEvaluationTest' test
```

[工作负载与断言](../backend/src/test/java/com/searchagent/career/task/CareerTaskEvaluationTest.java)

## 资料库 RAG 检索对照

2026-11-17 在本机 Elasticsearch 8.17.0 上运行。测试集由 48 篇手工编写的中文后端和求职技术短文档、40 条查询及文档级标注组成。查询包括 12 条术语检索、14 条语义改写和 14 条需要两份资料的查询。每条文档在本次数据上生成一个子块，因此候选块和来源文档一一对应。

评测使用实际 IK 分词、父子分块、Elasticsearch kNN 和 BM25，以及项目的 `hybrid_search`。评测索引独立创建，完成后清理。两路各取 20 个候选，混合组沿用项目的 Min-Max 归一化及 0.6 向量、0.4 BM25 的权重。向量组和混合组共享同一批 512 维向量，使用 CPU 本地运行的 BGE-small-zh-v1.5 ONNX 模型。对照关闭 Rerank。 [BGE 模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5) · [ONNX 文件来源](https://modelscope.cn/models/lyf219/bge-small-zh-v1.5-onnx)

Recall@5 是各查询前五条结果中相关文档召回比例的平均值，Hit@5 统计至少命中一份相关资料的查询比例，MRR@5 统计前五条结果内首个相关文档的倒数排名均值。

| 方案 | Recall@5 | Hit@5 | MRR@5 | 所有标注文档均命中 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 85.00% | 87.50% | 0.8458 | 33/40 |
| 向量 kNN | 88.75% | 92.50% | 0.7267 | 34/40 |
| 混合检索 | 90.00% | 92.50% | 0.8562 | 35/40 |

混合方案的 Recall@5 较 BM25 提高 5.00 个百分点，较向量 kNN 提高 1.25 个百分点。混合组取得 12/12 的术语查询命中，多文档查询的 Recall@5 为 92.86%。在语义改写子集上，混合组命中 11/14，向量组命中 12/14。混合组漏掉了 `semantic-13` 的岗位资料摘录文档，向量组可召回该文档。

在 `api/` 复跑时，将 `tokenizer.json` 和 `bge-small-zh-v1.5.onnx` 下载至同一目录，指向加载了 IK 插件的 Elasticsearch 实例。额外 Python 依赖可装入独立评测目录。

```powershell
uv pip install --target ../tmp/career-rag-eval/deps onnxruntime==1.22.1 tokenizers==0.21.4
$env:PYTHONPATH = (Resolve-Path ../tmp/career-rag-eval/deps).Path
uv run python -m eval.career_rag_eval --model-dir ../tmp/career-rag-eval/modelscope-bge-small-zh
```

[标注资料与查询](../api/eval/fixtures/career_rag_gold.json) · [评测脚本](../api/eval/career_rag_eval.py)
