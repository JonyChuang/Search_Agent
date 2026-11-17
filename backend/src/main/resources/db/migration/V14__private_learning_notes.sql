CREATE TABLE career_learning_note (
    user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    job_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    title VARCHAR(240) NOT NULL,
    summary TEXT NOT NULL,
    source_url VARCHAR(2048),
    document_id CHAR(36),
    document_title VARCHAR(512),
    document_revision VARCHAR(255),
    collected_at TIMESTAMP(6) NOT NULL,
    PRIMARY KEY (user_id, job_id, source_key),
    INDEX ix_learning_notes_order (user_id, job_id, collected_at),
    CONSTRAINT fk_learning_note_job FOREIGN KEY (job_id) REFERENCES career_job (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

