CREATE TABLE career_reminder (
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    job_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
    type VARCHAR(16) NOT NULL,
    title VARCHAR(160) NOT NULL,
    due_at TIMESTAMP(6) NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'PENDING',
    external_delivery BOOLEAN NOT NULL DEFAULT FALSE,
    delivery_state VARCHAR(12) NOT NULL DEFAULT 'IN_APP',
    delivery_started_at TIMESTAMP(6),
    revision INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX ix_reminder_owner_due (user_id, status, due_at),
    INDEX ix_reminder_delivery (delivery_state, status, due_at),
    CONSTRAINT fk_reminder_job FOREIGN KEY (job_id) REFERENCES career_job(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

