ALTER TABLE career_profile
    ADD COLUMN target_role VARCHAR(160),
    ADD COLUMN graduation_month CHAR(7),
    ADD COLUMN preferences VARCHAR(2000);

CREATE TABLE career_experience (
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    type VARCHAR(16) NOT NULL,
    title VARCHAR(160) NOT NULL,
    organization VARCHAR(160),
    start_month CHAR(7),
    end_month CHAR(7),
    description TEXT NOT NULL,
    source_note VARCHAR(500),
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_experience_owner (user_id, created_at, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE career_job (
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    company VARCHAR(160) NOT NULL,
    title VARCHAR(160) NOT NULL,
    location VARCHAR(160),
    description MEDIUMTEXT NOT NULL,
    source_name VARCHAR(160) NOT NULL,
    source_url VARCHAR(2048),
    sourced_on DATE NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_job_owner (user_id, created_at, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
