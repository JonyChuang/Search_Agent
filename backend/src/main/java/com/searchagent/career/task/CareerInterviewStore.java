package com.searchagent.career.task;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import com.searchagent.career.practice.PracticeService;
import com.searchagent.career.task.CareerInterviewSessions.Session;

@Repository
class CareerInterviewStore {
    private final JdbcClient db;
    private final ObjectMapper json;

    CareerInterviewStore(JdbcClient db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    Optional<Session> find(String user, UUID id, boolean lock) {
        return db.sql("SELECT state_json FROM career_mock_interview WHERE user_id = ? AND id = ?"
                + (lock ? " FOR UPDATE" : "")).params(user, id.toString())
                .query((row, index) -> read(row.getString(1))).optional();
    }

    Session insert(String user, Session state) {
        db.sql("""
                INSERT INTO career_mock_interview (id, user_id, job_id, state_json)
                VALUES (?, ?, ?, ?) ON DUPLICATE KEY UPDATE id = id
                """).params(state.id().toString(), user, state.jobId(), write(state)).update();
        return find(user, state.id(), false).orElseThrow();
    }

    void save(String user, Session state) {
        db.sql("UPDATE career_mock_interview SET state_json = ? WHERE user_id = ? AND id = ?")
                .params(write(state), user, state.id().toString()).update();
    }

    List<Session> list(String user, String jobId, int limit, long offset) {
        return db.sql("""
                SELECT state_json FROM career_mock_interview
                WHERE user_id = :user AND (:jobId IS NULL OR job_id = :jobId)
                ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset
                """).param("user", user).param("jobId", jobId).param("limit", limit).param("offset", offset)
                .query((row, index) -> read(row.getString(1))).list();
    }

    List<PendingSession> completedPending() {
        return db.sql("""
                SELECT s.user_id, s.id, s.pending_task_id
                FROM career_mock_interview s JOIN career_task t ON t.id = s.pending_task_id
                    AND t.user_id = CONVERT(s.user_id USING utf8mb4) COLLATE utf8mb4_0900_ai_ci
                WHERE s.pending_task_id IS NOT NULL AND t.kind = 'INTERVIEW_TURN' AND t.status = 'SUCCEEDED'
                ORDER BY s.created_at LIMIT 25
                """).query((row, index) -> new PendingSession(row.getString(1),
                        UUID.fromString(row.getString(2)), UUID.fromString(row.getString(3)))).list();
    }

    List<Session> recentCompleted(String user, String jobId) {
        return db.sql("""
                SELECT state_json FROM career_mock_interview
                WHERE user_id = ? AND job_id = ? AND state_json->>'$.status' = 'FINISHED'
                ORDER BY created_at DESC, id DESC LIMIT 5
                """).params(user, jobId).query((row, index) -> read(row.getString(1))).list();
    }

    List<PracticeService.QuestionVersion> completedQuestions(String user, String jobId,
            List<PracticeService.QuestionVersion> refs) {
        if (refs.isEmpty()) return List.of();
        return db.sql("""
                SELECT DISTINCT q.question_id, q.question_version
                FROM career_mock_interview s
                JOIN JSON_TABLE(s.state_json, '$.rounds[*]' COLUMNS (
                    question_id VARCHAR(80) PATH '$.question.id',
                    question_version INT PATH '$.question.version',
                    evaluated INT PATH '$.main.evaluation.accuracy'
                )) q
                WHERE s.user_id = :user AND s.job_id = :job AND s.state_json->>'$.status' = 'FINISHED'
                    AND q.evaluated IS NOT NULL AND q.question_id IN (:ids)
                """).param("user", user).param("job", jobId)
                .param("ids", refs.stream().map(PracticeService.QuestionVersion::id).distinct().toList())
                .query((row, index) -> new PracticeService.QuestionVersion(row.getString(1), row.getInt(2)))
                .list().stream().filter(refs::contains).toList();
    }

    record PendingSession(String user, UUID sessionId, UUID taskId) {}

    private Session read(String value) {
        try {
            return json.readValue(value, Session.class);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("Invalid mock interview state", error);
        }
    }

    private String write(Session state) {
        try {
            return json.writeValueAsString(state);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("Could not serialize mock interview state", error);
        }
    }
}
