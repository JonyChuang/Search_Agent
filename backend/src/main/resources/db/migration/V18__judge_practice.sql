CREATE TABLE career_judge_problem (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version INT NOT NULL,
    kind VARCHAR(8) NOT NULL,
    topic VARCHAR(80) NOT NULL,
    prompt TEXT NOT NULL,
    starter TEXT,
    tests JSON NOT NULL,
    PRIMARY KEY (id, version)
);

CREATE TABLE career_judge_submission (
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    job_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
    problem_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version INT NOT NULL,
    submission MEDIUMTEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'QUEUED',
    passed INT NOT NULL DEFAULT 0,
    sandbox_token VARCHAR(128),
    lease CHAR(36),
    ready_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at TIMESTAMP(6),
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX ix_judge_ready (status, ready_at),
    INDEX ix_judge_owner (user_id, created_at),
    CONSTRAINT fk_judge_problem FOREIGN KEY (problem_id, version) REFERENCES career_judge_problem(id, version),
    CONSTRAINT fk_judge_job FOREIGN KEY (job_id) REFERENCES career_job(id) ON DELETE CASCADE
);

INSERT INTO career_judge_problem (id,version,kind,topic,prompt,starter,tests) VALUES
('prefix-sum',1,'PYTHON','前缀和',
 '第一行给出整数 n 和 q，第二行是 n 个整数。接下来 q 行每行给出闭区间 l r（从 1 开始）。每行输出对应区间的和。n、q 均不超过 10 万。',
 'import sys',
 JSON_ARRAY(
   JSON_OBJECT('stdin', CONVERT(CONCAT('3 3',CHAR(10),'1 -2 5',CHAR(10),'1 1',CHAR(10),'1 3',CHAR(10),'2 2',CHAR(10)) USING utf8mb4),
               'expected', CONVERT(CONCAT('1',CHAR(10),'4',CHAR(10),'-2',CHAR(10)) USING utf8mb4)),
   JSON_OBJECT('stdin', CONVERT(CONCAT('4 2',CHAR(10),'-10 4 0 9',CHAR(10),'1 4',CHAR(10),'3 4',CHAR(10)) USING utf8mb4),
               'expected', CONVERT(CONCAT('3',CHAR(10),'9',CHAR(10)) USING utf8mb4)),
   JSON_OBJECT('stdin', CONVERT(CONCAT('1 1',CHAR(10),'1000000000',CHAR(10),'1 1',CHAR(10)) USING utf8mb4),
               'expected', CONVERT(CONCAT('1000000000',CHAR(10)) USING utf8mb4)))),
('application-count',1,'SQL','SQL 聚合',
 '表 applications(company TEXT, stage TEXT)。查询每家公司的已投递记录数量（stage = ''SUBMITTED''）。返回两列 company 和 count，按照 company 升序排列，跳过没有已投递记录的公司。',
 'SELECT company, COUNT(*) AS count',
 JSON_ARRAY(
   JSON_OBJECT('stdin','CREATE TABLE applications(company TEXT, stage TEXT); INSERT INTO applications VALUES (''A'',''SUBMITTED''),(''A'',''DRAFT''),(''C'',''SUBMITTED''),(''A'',''SUBMITTED'');',
               'expected','[["A",2],["C",1]]'),
   JSON_OBJECT('stdin','CREATE TABLE applications(company TEXT, stage TEXT); INSERT INTO applications VALUES (''B'',''DRAFT''),(''A'',''DRAFT'');',
               'expected','[]'),
   JSON_OBJECT('stdin','CREATE TABLE applications(company TEXT, stage TEXT); INSERT INTO applications VALUES (''Z'',''SUBMITTED''),(''A'',''SUBMITTED'');',
               'expected','[["A",1],["Z",1]]')));

