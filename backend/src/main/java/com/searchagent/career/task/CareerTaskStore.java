package com.searchagent.career.task;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
class CareerTaskStore {
    private final JdbcClient db;
    private final ObjectMapper json;

    CareerTaskStore(JdbcClient db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    Row insert(String user, UUID requestId, String kind, JsonNode request, JsonNode context) {
        db.sql("""
                INSERT INTO career_task (id, user_id, request_id, kind, request_json, context_json)
                VALUES (?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE id = id
                """).params(UUID.randomUUID().toString(), user, requestId.toString(), kind,
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

    List<Row> list(String user, String kind, long offset) {
        return db.sql("""
                SELECT * FROM career_task WHERE user_id = ? AND kind = ?
                ORDER BY created_at DESC, id DESC LIMIT 21 OFFSET ?
                """).params(user, kind, offset).query(this::row).list();
    }

    @Transactional
    Optional<Row> claim() {
        var pending = db.sql("""
                SELECT id FROM career_task
                WHERE status = 'QUEUED' OR (status = 'RUNNING' AND lease_until <= CURRENT_TIMESTAMP(6))
                ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
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

    void retry(String user, UUID id) {
        db.sql("""
                UPDATE career_task SET status = 'QUEUED', error_message = NULL
                WHERE user_id = ? AND id = ? AND status = 'FAILED'
                """).params(user, id.toString()).update();
    }

    private Row row(ResultSet rs, int index) throws SQLException {
        return new Row(rs.getString("id"), rs.getString("user_id"), rs.getString("kind"), rs.getString("status"),
                tree(rs.getString("request_json")), tree(rs.getString("context_json")), tree(rs.getString("result_json")),
                rs.getString("error_message"), rs.getInt("generation"), rs.getString("lease_token"),
                rs.getTimestamp("created_at").toInstant(), rs.getTimestamp("updated_at").toInstant());
    }

    private JsonNode tree(String value) throws SQLException {
        try {
            return value == null ? null : json.readTree(value);
        } catch (JsonProcessingException error) {
            throw new SQLException("Invalid stored career task JSON", error);
        }
    }

    record Row(String id, String user, String kind, String status, JsonNode request, JsonNode context,
            JsonNode result, String error, int generation, String lease, Instant createdAt, Instant updatedAt) {}
}
