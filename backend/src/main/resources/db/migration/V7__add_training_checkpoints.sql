ALTER TABLE career_task
    ADD COLUMN training_catalog_json JSON,
    ADD COLUMN training_catalog_at TIMESTAMP(6),
    ADD COLUMN training_draft_json JSON,
    ADD COLUMN training_draft_at TIMESTAMP(6);
