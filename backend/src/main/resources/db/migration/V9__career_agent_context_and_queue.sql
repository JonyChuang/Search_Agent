ALTER TABLE career_task
    ADD COLUMN agent_context_json JSON,
    ADD COLUMN queued_at TIMESTAMP(6) NULL,
    ADD INDEX ix_career_task_scope_queue (user_id, job_id, status, queued_at, id);

UPDATE career_task SET queued_at = created_at;
ALTER TABLE career_task MODIFY queued_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6);

CREATE TABLE career_task_scheduler (
    id TINYINT PRIMARY KEY
);
INSERT INTO career_task_scheduler (id) VALUES (1);

CREATE TABLE career_job_memory (
    job_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    revision INT NOT NULL,
    notes VARCHAR(3000),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (job_id),
    CONSTRAINT fk_career_memory_job FOREIGN KEY (job_id) REFERENCES career_job (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE career_task_event (
    task_id CHAR(36) NOT NULL,
    generation INT NOT NULL,
    sequence_no INT NOT NULL,
    step VARCHAR(48) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    elapsed_ms INT NOT NULL,
    input_tokens INT,
    output_tokens INT,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (task_id, generation, sequence_no),
    CONSTRAINT fk_career_event_task FOREIGN KEY (task_id) REFERENCES career_task (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
