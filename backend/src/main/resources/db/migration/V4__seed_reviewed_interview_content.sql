INSERT INTO career_interview_note
    (id, role, company, title, summary, source_name, source_url, published_on, sourced_on)
VALUES
    ('cloudflare-software-intern-2022', '软件开发实习', 'Cloudflare', '软件开发实习面试回顾',
     'Ulysses Kee 回顾了自己的实习求职过程。面试中，团队多次询问他希望参与哪类工作，以及这些兴趣与实习内容的关系。',
     'Cloudflare Blog · Ulysses Kee', 'https://blog.cloudflare.com/internship-experience-software-development-intern/#interview-experience',
     '2022-05-18', '2026-11-06'),
    ('cloudflare-solutions-2019', '解决方案工程', 'Cloudflare', '从产品理解到网络架构说明',
     'Andrew A. Schafer 回忆，面试前收到的准备建议包括了解 Cloudflare 的工作方式。在与联合创始人的交流中，他请对方画出简化的网络结构图，随后决定完成解决方案工程团队布置的作业。',
     'Cloudflare Blog · Andrew A. Schafer', 'https://blog.cloudflare.com/china-silicon-valley-china/',
     '2019-04-10', '2026-11-06');

-- Original practice prompts and distractors, checked against the linked references.
INSERT INTO career_question_version
    (id, version, grading_version, role, topic, prompt, option_a, option_b, option_c, option_d,
     correct_answer, explanation, source_name, source_url, sourced_on)
VALUES
    ('backend-java-hashcode', 1, 1, 'backend', 'Java 集合',
     '两个 Java 对象按 equals 判定相等。以下哪条是 hashCode 必须满足的约定？',
     '两个对象的 hashCode 必须不同', '两个对象的 hashCode 必须相同',
     '两个对象的引用地址必须相同', 'hashCode 必须在每次启动 JVM 时都相同',
     'B', 'equals 相等的对象必须产生相同的哈希值。equals 不相等的对象仍允许出现哈希碰撞。',
     'Java SE 21 · Object.hashCode', 'https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/Object.html#hashCode()', '2026-11-06'),
    ('backend-mysql-snapshot', 1, 1, 'backend', '数据库事务',
     'InnoDB 事务使用 REPEATABLE READ，且本事务未修改所查数据。第一次普通 SELECT 建立快照后，另一事务更新数据并提交。原事务再次执行普通 SELECT 时读取哪个版本？',
     '另一事务刚提交的版本', '由第二次 SELECT 随机选择的版本',
     '所有事务开始前数据库中的最早版本', '第一次一致性读建立的快照中的版本',
     'D', '同一 REPEATABLE READ 事务中的一致性读复用第一次一致性读的快照，因此此处看不到另一事务之后提交的更新。',
     'MySQL 8.4 · Consistent Nonlocking Reads', 'https://dev.mysql.com/doc/refman/8.4/en/innodb-consistent-read.html', '2026-11-06'),
    ('algorithm-binary-search', 1, 1, 'algorithm', '二分查找',
     '对有序列表 [1, 2, 2, 4] 调用 bisect_left(values, 2)，返回的零基索引是多少？',
     '1', '2', '3', '4',
     'A', 'bisect_left 返回相同元素之前的插入位置。列表中第一个 2 的索引为 1。',
     'Python 3.12 · bisect_left', 'https://docs.python.org/3.12/library/bisect.html#bisect.bisect_left', '2026-11-06'),
    ('algorithm-deque', 1, 1, 'algorithm', '队列与广度优先搜索',
     '使用 Python 容器维护广度优先搜索的先进先出队列。哪组操作既能保持顺序，也能高效地从头部出队？',
     'list.append 与 list.pop(0)', 'deque.append 与 deque.pop',
     'deque.append 与 deque.popleft', 'list.append 与 list.pop',
     'C', 'append 从右侧入队，popleft 从左侧出队。deque 两端的这些操作通常为 O(1)，列表头部删除需要移动元素。',
     'Python 3.12 · collections.deque', 'https://docs.python.org/3.12/library/collections.html#collections.deque', '2026-11-06'),
    ('llm-semantic-retrieval', 1, 1, 'llm', 'RAG 语义检索',
     '问题和相关文档使用了不同措辞。哪种能力最有助于召回几乎没有共同关键词的相关段落？',
     '按文档上传时间倒序', '按向量表示的语义相似度检索',
     '只查找完全匹配的词组', '只保留文件名最长的文档',
     'B', '向量表示可将语义接近的文本放在相近位置，即使文本没有明显的词面重合。',
     'OpenAI API · Semantic search', 'https://developers.openai.com/api/docs/guides/retrieval#semantic-search', '2026-11-06'),
    ('llm-elastic-mapping', 1, 1, 'llm', 'RAG 文本索引',
     '用 Elasticsearch 建立知识库索引，希望段落可按分词后的术语搜索，同时用来源标签做精确过滤。通常应如何映射这两个字段？',
     '段落用 keyword，来源标签用 text', '两个字段都用 integer',
     '段落用 date，来源标签用 text', '段落用 text，来源标签用 keyword',
     'D', 'text 字段经过分析后可用于全文搜索。keyword 适合需要按完整值匹配的结构化标签。',
     'Elasticsearch · Text field type', 'https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/text', '2026-11-06');
