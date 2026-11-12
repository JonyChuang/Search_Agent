ALTER TABLE career_job ADD COLUMN skills VARCHAR(1000);

ALTER TABLE career_profile
    ADD COLUMN active_job_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
    ADD CONSTRAINT fk_career_profile_active_job FOREIGN KEY (active_job_id)
        REFERENCES career_job (id) ON DELETE SET NULL;

ALTER TABLE career_task
    ADD COLUMN job_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
    ADD INDEX ix_career_task_job (user_id, job_id, kind, created_at);

ALTER TABLE career_practice_attempt
    ADD COLUMN job_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
    ADD INDEX ix_career_attempt_job (user_id, job_id, sequence_id);

UPDATE career_task SET job_id = JSON_UNQUOTE(JSON_EXTRACT(request_json, '$.jobId'))
WHERE JSON_TYPE(JSON_EXTRACT(request_json, '$.jobId')) = 'STRING';

UPDATE career_task review_task
JOIN career_task plan ON plan.id = JSON_UNQUOTE(JSON_EXTRACT(review_task.request_json, '$.planId'))
    AND plan.user_id = review_task.user_id AND plan.kind = 'TRAINING'
SET review_task.job_id = plan.job_id WHERE review_task.kind = 'REVIEW';
