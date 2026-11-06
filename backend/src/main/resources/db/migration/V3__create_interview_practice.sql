CREATE TABLE career_interview_note (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    role VARCHAR(24) NOT NULL,
    company VARCHAR(160) NOT NULL,
    title VARCHAR(160) NOT NULL,
    summary TEXT NOT NULL,
    source_name VARCHAR(160) NOT NULL,
    source_url VARCHAR(2048) NOT NULL,
    published_on DATE NOT NULL,
    sourced_on DATE NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE career_question_version (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version INT NOT NULL,
    grading_version INT NOT NULL,
    role VARCHAR(24) NOT NULL,
    topic VARCHAR(80) NOT NULL,
    prompt VARCHAR(1000) NOT NULL,
    option_a VARCHAR(500) NOT NULL,
    option_b VARCHAR(500) NOT NULL,
    option_c VARCHAR(500) NOT NULL,
    option_d VARCHAR(500) NOT NULL,
    correct_answer CHAR(1) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    explanation TEXT NOT NULL,
    source_name VARCHAR(160) NOT NULL,
    source_url VARCHAR(2048) NOT NULL,
    sourced_on DATE NOT NULL,
    PRIMARY KEY (id, version),
    CHECK (correct_answer IN ('A', 'B', 'C', 'D'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE career_practice_attempt (
    sequence_id BIGINT NOT NULL AUTO_INCREMENT,
    user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    question_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    question_version INT NOT NULL,
    grading_version INT NOT NULL,
    answer CHAR(1) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    correct BOOLEAN NOT NULL,
    submitted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (sequence_id),
    UNIQUE KEY uq_practice_request (user_id, request_id),
    INDEX ix_practice_user_recent (user_id, sequence_id),
    INDEX ix_practice_user_question (user_id, question_id, sequence_id),
    FOREIGN KEY (question_id, question_version) REFERENCES career_question_version (id, version),
    CHECK (answer IN ('A', 'B', 'C', 'D'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
