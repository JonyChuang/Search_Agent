ALTER TABLE career_application
    ADD COLUMN workspace_json JSON NULL,
    ADD COLUMN workspace_request_id CHAR(36) NULL;

ALTER TABLE career_application_event ADD COLUMN receipt_json JSON NULL;

CREATE TABLE career_application_file (
    application_id CHAR(36) NOT NULL,
    id CHAR(36) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size INT NOT NULL,
    content MEDIUMBLOB NOT NULL,
    retained BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (application_id, id),
    CONSTRAINT fk_application_file_owner FOREIGN KEY (application_id) REFERENCES career_application (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
