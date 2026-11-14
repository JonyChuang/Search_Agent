package com.searchagent.career.task;

import static org.springframework.http.HttpStatus.TOO_MANY_REQUESTS;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Repository
class CareerTaskStore {
    private final JdbcClient db;
    private final ObjectMapper json;

    CareerTaskStore(JdbcClient db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    @Transactional
    Row insert(String user, UUID requestId, String kind, String jobId, JsonNode request, JsonNode context) {
        lockScheduler();
        var existing = byRequest(user, requestId);
        if (existing.isPresent()) return existing.get();
        checkQueue(user);
        db.sql("""
                INSERT INTO career_task (id, user_id, request_id, kind, job_id, request_json, context_json)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE id = id
                """).params(UUID.randomUUID().toString(), user, requestId.toString(), kind, jobId,
                request.toString(), context.toString()).update();
        return byRequest(user, requestId).orElseThrow();
    }

    Optional<Row> byRequest(String user, UUID requestId) {
        return db.sql("SELECT * FROM career_task WHERE user_id = ? AND request_id = ?")
                .params(user, requestId.toString()).query(this::row).optional();
    }

    Optional<Row> owned(String user, UUID id) {
        return db.sql("SELECT * FROM career_task WHERE user_id = ? AND id = ?")
                .params(user, id.toString()).query(this::row).optional();
    }

    List<Row> list(String user, String kind, String jobId, long offset) {
        return db.sql("""
                SELECT * FROM career_task WHERE user_id = :user AND kind = :kind
                    AND (:jobId IS NULL OR job_id = :jobId)
                ORDER BY created_at DESC, id DESC LIMIT 21 OFFSET :offset
                """).param("user", user).param("kind", kind).param("jobId", jobId)
                .param("offset", offset).query(this::row).list();
    }

    List<Row> interviewFeedback(String user, String jobId, List<String> questionIds) {
        if (questionIds.isEmpty()) return List.of();
        return db.sql("""
                SELECT * FROM career_task WHERE user_id = :user AND job_id = :jobId
                    AND kind = 'INTERVIEW' AND status = 'SUCCEEDED'
                    AND JSON_UNQUOTE(JSON_EXTRACT(request_json, '$.questionId')) IN (:questionIds)
                ORDER BY created_at DESC LIMIT 20
                """).param("user", user).param("jobId", jobId).param("questionIds", questionIds)
                .query(this::row).list();
    }

    List<String> completedInterviews(String user, String jobId, List<String> questionIds) {
        if (questionIds.isEmpty()) return List.of();
        return db.sql("""
                SELECT DISTINCT request_json->>'$.questionId' AS question_id
                FROM career_task WHERE user_id = :user AND job_id = :jobId
                    AND kind = 'INTERVIEW' AND status = 'SUCCEEDED'
                    AND request_json->>'$.questionId' IN (:questionIds)
                """).param("user", user).param("jobId", jobId).param("questionIds", questionIds)
                .query(String.class).list();
    }

    @Transactional
    Optional<Row> claim() {
        // Serialize the short claim transaction across Java instances. No model call holds this lock.
        lockScheduler();
        var pending = db.sql("""
                SELECT t.id FROM career_task t
                WHERE (t.status = 'QUEUED' OR (t.status = 'RUNNING' AND t.lease_until <= CURRENT_TIMESTAMP(6)))
                  AND (SELECT COUNT(*) FROM career_task r WHERE r.status = 'RUNNING'
                       AND r.lease_until > CURRENT_TIMESTAMP(6)) < 4
                  AND (SELECT COUNT(*) FROM career_task r WHERE r.status = 'RUNNING'
                       AND r.lease_until > CURRENT_TIMESTAMP(6) AND r.user_id = t.user_id) < 2
                  AND NOT EXISTS (SELECT 1 FROM career_task r
                      WHERE r.user_id = t.user_id AND r.job_id <=> t.job_id AND r.id <> t.id
                        AND ((r.status = 'RUNNING' AND r.lease_until > CURRENT_TIMESTAMP(6))
                          OR (r.status IN ('RUNNING', 'QUEUED') AND (r.queued_at, r.id) < (t.queued_at, t.id))))
                ORDER BY t.queued_at, t.id LIMIT 1 FOR UPDATE SKIP LOCKED
                """).query(String.class).optional();
        return pending.map(id -> {
            String lease = UUID.randomUUID().toString();
            db.sql("""
                    UPDATE career_task SET status = 'RUNNING', generation = generation + 1, lease_token = ?,
                        lease_until = DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 120 SECOND)
                    WHERE id = ?
                    """).params(lease, id).update();
            return db.sql("SELECT * FROM career_task WHERE id = ?").param(id).query(this::row).single();
        });
    }

    Optional<Row> active(UUID id, UUID lease) {
        return db.sql("""
                SELECT * FROM career_task WHERE id = ? AND lease_token = ? AND status = 'RUNNING'
                    AND lease_until > CURRENT_TIMESTAMP(6)
                """).params(id.toString(), lease.toString()).query(this::row).optional();
    }

    Optional<Row> checkpointCatalog(Row row, JsonNode catalog) {
        db.sql("""
                UPDATE career_task SET training_catalog_json = ?, training_catalog_at = CURRENT_TIMESTAMP(6)
                WHERE id = ? AND generation = ? AND lease_token = ? AND status = 'RUNNING'
                    AND lease_until > CURRENT_TIMESTAMP(6) AND training_catalog_json IS NULL
                """).params(catalog.toString(), row.id(), row.generation(), row.lease()).update();
        return active(UUID.fromString(row.id()), UUID.fromString(row.lease()));
    }

    Optional<Row> checkpointContext(Row row, JsonNode context) {
        db.sql("""
                UPDATE career_task SET agent_context_json = ?
                WHERE id = ? AND generation = ? AND lease_token = ? AND status = 'RUNNING'
                    AND lease_until > CURRENT_TIMESTAMP(6) AND agent_context_json IS NULL
                """).params(context.toString(), row.id(), row.generation(), row.lease()).update();
        return active(UUID.fromString(row.id()), UUID.fromString(row.lease()));
    }

    boolean recordEvent(Row row, EventInput event) {
        db.sql("""
                INSERT INTO career_task_event (task_id, generation, sequence_no, step, outcome,
                                               elapsed_ms, input_tokens, output_tokens)
                SELECT id, generation, :seq, :step, :outcome, :elapsed, :input, :output FROM career_task
                WHERE id = :id AND generation = :generation AND lease_token = :lease AND status = 'RUNNING'
                    AND lease_until > CURRENT_TIMESTAMP(6)
                ON DUPLICATE KEY UPDATE sequence_no = career_task_event.sequence_no
                """).param("seq", event.sequenceNo()).param("step", event.step()).param("outcome", event.outcome())
                .param("elapsed", event.elapsedMs()).param("input", event.inputTokens()).param("output", event.outputTokens())
                .param("id", row.id()).param("generation", row.generation()).param("lease", row.lease()).update();
        return active(UUID.fromString(row.id()), UUID.fromString(row.lease())).isPresent();
    }

    List<Event> events(UUID id) {
        return db.sql("""
                SELECT generation, sequence_no, step, outcome, elapsed_ms, input_tokens, output_tokens, created_at
                FROM career_task_event WHERE task_id = ?
                ORDER BY generation DESC, sequence_no DESC LIMIT 100
                """).param(id.toString()).query(Event.class).list();
    }

    Optional<Row> checkpointDraft(Row row, JsonNode draft) {
        db.sql("""
                UPDATE career_task SET training_draft_json = ?, training_draft_at = CURRENT_TIMESTAMP(6)
                WHERE id = ? AND generation = ? AND lease_token = ? AND status = 'RUNNING'
                    AND lease_until > CURRENT_TIMESTAMP(6) AND training_catalog_json IS NOT NULL
                    AND training_draft_json IS NULL
                """).params(draft.toString(), row.id(), row.generation(), row.lease()).update();
        return active(UUID.fromString(row.id()), UUID.fromString(row.lease()));
    }

    boolean finish(Row row, JsonNode result, String error) {
        return db.sql("""
                UPDATE career_task SET status = ?, result_json = ?, error_message = ?,
                    lease_token = NULL, lease_until = NULL
                WHERE id = ? AND generation = ? AND lease_token = ? AND status = 'RUNNING'
                    AND lease_until > CURRENT_TIMESTAMP(6)
                """).param(1, error == null ? "SUCCEEDED" : "FAILED")
                .param(2, result == null ? null : result.toString()).param(3, error)
                .param(4, row.id()).param(5, row.generation()).param(6, row.lease()).update() == 1;
    }

    @Transactional
    void retry(String user, UUID id) {
        lockScheduler();
        if (owned(user, id).filter(row -> "FAILED".equals(row.status())).isEmpty()) return;
        checkQueue(user);
        db.sql("""
                UPDATE career_task SET status = 'QUEUED', error_message = NULL, queued_at = CURRENT_TIMESTAMP(6)
                WHERE user_id = ? AND id = ? AND status = 'FAILED'
                """).params(user, id.toString()).update();
    }

    private void lockScheduler() {
        db.sql("SELECT id FROM career_task_scheduler WHERE id = 1 FOR UPDATE").query(Integer.class).single();
    }

    private void checkQueue(String user) {
        int queued = db.sql("SELECT COUNT(*) FROM career_task WHERE user_id = ? AND status = 'QUEUED'")
                .param(user).query(Integer.class).single();
        int total = db.sql("SELECT COUNT(*) FROM career_task WHERE status = 'QUEUED'").query(Integer.class).single();
        if (queued >= 20 || total >= 200) {
            throw new ResponseStatusException(TOO_MANY_REQUESTS, "待处理任务已满，请等部分任务完成后再试");
        }
    }

    private Row row(ResultSet rs, int index) throws SQLException {
        return new Row(rs.getString("id"), rs.getString("user_id"), rs.getString("kind"), rs.getString("status"),
                rs.getString("job_id"),
                tree(rs.getString("request_json")), tree(rs.getString("context_json")), tree(rs.getString("result_json")),
                tree(rs.getString("training_catalog_json")), tree(rs.getString("training_draft_json")),
                rs.getString("error_message"), rs.getInt("generation"), rs.getString("lease_token"),
                tree(rs.getString("agent_context_json")),
                rs.getTimestamp("created_at").toInstant(), rs.getTimestamp("updated_at").toInstant());
    }

    private JsonNode tree(String value) throws SQLException {
        try {
            return value == null ? null : json.readTree(value);
        } catch (JsonProcessingException error) {
            throw new SQLException("Invalid stored career task JSON", error);
        }
    }

    record Row(String id, String user, String kind, String status, String jobId, JsonNode request, JsonNode context,
            JsonNode result, JsonNode trainingCatalog, JsonNode trainingDraft, String error,
            int generation, String lease, JsonNode agentContext, Instant createdAt, Instant updatedAt) {}

    public record Event(int generation, int sequenceNo, String step, String outcome, int elapsedMs,
            Integer inputTokens, Integer outputTokens, Instant createdAt) {}
    record EventInput(@NotNull @Positive @Max(60) Integer sequenceNo,
            @NotNull @Pattern(regexp = "[a-z_]{1,48}") String step,
            @NotNull @Pattern(regexp = "succeeded|failed") String outcome,
            @NotNull @PositiveOrZero Integer elapsedMs, @PositiveOrZero Integer inputTokens,
            @PositiveOrZero Integer outputTokens) {}
}
