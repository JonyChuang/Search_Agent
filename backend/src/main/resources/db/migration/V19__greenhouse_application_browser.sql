CREATE TABLE career_application_browser (
    application_id CHAR(36) PRIMARY KEY,
    id CHAR(36) NOT NULL UNIQUE,
    revision INT NOT NULL,
    token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    target_path VARCHAR(500) NOT NULL,
    state VARCHAR(16) NOT NULL,
    requested_at TIMESTAMP(6),
    evidence_url VARCHAR(2048),
    expires_at TIMESTAMP(6) NOT NULL,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_application_browser FOREIGN KEY (application_id) REFERENCES career_application(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

