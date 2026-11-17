CREATE TABLE career_resume_profile (
    user_id CHAR(36) NOT NULL PRIMARY KEY,
    revision INT NOT NULL,
    content_json JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE career_resume_version
    MODIFY job_id CHAR(36) NULL,
    ADD COLUMN profile_revision INT NULL,
    ADD COLUMN design_json JSON NULL;
