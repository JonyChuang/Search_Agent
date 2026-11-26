ALTER TABLE career_task ADD COLUMN training_runtime_json JSON;
ALTER TABLE career_task_event
    ADD COLUMN details_json JSON,
    ADD INDEX ix_career_task_event_created (created_at);
