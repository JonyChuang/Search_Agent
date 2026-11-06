CREATE TABLE career_resume_version (
    id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    job_id CHAR(36) NOT NULL,
    company VARCHAR(160) NOT NULL,
    job_title VARCHAR(160) NOT NULL,
    request_id CHAR(36) NOT NULL,
    evidence_json JSON NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_resume_request (user_id, request_id),
    INDEX ix_resume_owner (user_id, created_at, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE career_application (
    id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    job_id CHAR(36) NOT NULL,
    company VARCHAR(160) NOT NULL,
    job_title VARCHAR(160) NOT NULL,
    source_url VARCHAR(2048),
    resume_id CHAR(36),
    answers TEXT NOT NULL,
    stage VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_application_job (user_id, job_id),
    INDEX ix_application_owner (user_id, updated_at, id),
    CONSTRAINT fk_application_resume FOREIGN KEY (resume_id) REFERENCES career_resume_version (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE career_application_event (
    application_id CHAR(36) NOT NULL,
    revision INT NOT NULL,
    stage VARCHAR(16) NOT NULL,
    note VARCHAR(1000),
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (application_id, revision),
    CONSTRAINT fk_event_application FOREIGN KEY (application_id) REFERENCES career_application (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
