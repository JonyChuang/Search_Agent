ALTER TABLE career_mock_interview
    ADD COLUMN pending_task_id CHAR(36) COLLATE utf8mb4_0900_ai_ci
        GENERATED ALWAYS AS (NULLIF(state_json->>'$.pending', 'null')) STORED,
    ADD INDEX ix_mock_interview_pending (pending_task_id);

ALTER TABLE career_application_event
    ADD COLUMN material_snapshot JSON NULL,
    ADD COLUMN event_type VARCHAR(24) NOT NULL DEFAULT 'STAGE';
