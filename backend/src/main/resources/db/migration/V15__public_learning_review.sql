CREATE TABLE career_content_draft (
    id CHAR(36) NOT NULL,
    source_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin UNIQUE,
    kind VARCHAR(12) NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'DRAFT',
    payload JSON NOT NULL,
    base_version INT,
    revision INT NOT NULL DEFAULT 1,
    reviewed_by CHAR(36),
    published_at TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_content_review (status, updated_at)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

