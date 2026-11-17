package com.searchagent.career.task;

import java.sql.Timestamp;
import java.util.List;
import java.util.UUID;

import com.searchagent.career.job.JobService;
import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/career")
class CareerObservations {
    private final JdbcClient db;
    private final JobService jobs;

    CareerObservations(JdbcClient db, JobService jobs) {
        this.db = db;
        this.jobs = jobs;
    }

    @GetMapping("/jobs/{jobId}/learning-signals")
    CareerResponse<Learning> learning(@CareerUser String user, @PathVariable UUID jobId) {
        String job = jobs.find(user, jobId.toString()).id();
        var attempts = db.sql("""
                SELECT a.request_id AS attempt_id, a.question_id, a.question_version, a.correct, a.submitted_at, q.topic
                FROM career_practice_attempt a JOIN career_question_version q
                    ON q.id = a.question_id AND q.version = a.question_version
                WHERE a.user_id = ? AND a.job_id = ? ORDER BY a.sequence_id DESC LIMIT 12
                """).params(user, job).query(Attempt.class).list();
        var interviews = db.sql("""
                SELECT id, created_at, JSON_UNQUOTE(JSON_EXTRACT(state_json, '$.status')) AS status
                FROM career_mock_interview WHERE user_id = ? AND job_id = ?
                ORDER BY created_at DESC LIMIT 5
                """).params(user, job).query(Interview.class).list();
        return CareerResponse.ok(new Learning(attempts, interviews));
    }

    @GetMapping("/task-metrics")
    CareerResponse<List<StatusMetrics>> metrics(@CareerUser String user, @RequestParam(required = false) UUID jobId) {
        String job = jobId == null ? "" : jobs.find(user, jobId.toString()).id();
        return CareerResponse.ok(db.sql("""
                SELECT t.kind, t.status, COUNT(DISTINCT t.id) AS task_count, COUNT(e.task_id) AS recorded_steps,
                    COALESCE(SUM(e.elapsed_ms), 0) AS step_milliseconds, COUNT(e.input_tokens) AS measured_inputs,
                    COALESCE(SUM(e.input_tokens), 0) AS input_tokens, COALESCE(SUM(e.output_tokens), 0) AS output_tokens
                FROM career_task t LEFT JOIN career_task_event e ON e.task_id = t.id
                WHERE t.user_id = :user AND (:job = '' OR t.job_id = :job)
                    AND t.created_at >= CURRENT_TIMESTAMP - INTERVAL 30 DAY
                GROUP BY t.kind, t.status ORDER BY t.kind, t.status
                """).param("user", user).param("job", job).query(StatusMetrics.class).list());
    }

    record Attempt(String attemptId, String questionId, int questionVersion, boolean correct, Timestamp submittedAt, String topic) {}
    record Interview(String id, Timestamp createdAt, String status) {}
    record Learning(List<Attempt> objectiveAttempts, List<Interview> recentInterviews) {}
    record StatusMetrics(String kind, String status, long taskCount, long recordedSteps, long stepMilliseconds,
            long measuredInputs, long inputTokens, long outputTokens) {}
}
