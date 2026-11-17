package com.searchagent.career.practice;

import static org.springframework.http.HttpStatus.NOT_FOUND;
import static org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE;
import static org.springframework.http.HttpStatus.TOO_MANY_REQUESTS;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.Semaphore;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.searchagent.career.job.JobService;
import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/career/judge")
class JudgePractice {
    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(JudgePractice.class);
    private final JdbcClient db;
    private final ObjectMapper json;
    private final Judge0 judge;
    private final JobService jobs;
    private final Semaphore workers = new Semaphore(2);

    JudgePractice(JdbcClient db, ObjectMapper json, Judge0 judge, JobService jobs) {
        this.db = db;
        this.json = json;
        this.judge = judge;
        this.jobs = jobs;
    }

    @GetMapping("/problems")
    CareerResponse<Catalog> problems(@CareerUser String user) {
        var list = db.sql("""
                SELECT p.id, p.version, p.kind, p.topic, p.prompt, p.starter
                FROM career_judge_problem p WHERE NOT EXISTS (
                    SELECT 1 FROM career_judge_problem n WHERE n.id = p.id AND n.version > p.version)
                ORDER BY p.kind, p.id
                """).query(Problem.class).list();
        return CareerResponse.ok(new Catalog(judge.configured(), list));
    }

    @GetMapping("/submissions")
    CareerResponse<List<Result>> history(@CareerUser String user, @RequestParam(required = false) UUID jobId) {
        return CareerResponse.ok(db.sql("""
                SELECT id, problem_id, job_id, version, status, passed, created_at FROM career_judge_submission
                WHERE user_id = :user AND (:job IS NULL OR job_id = :job) ORDER BY created_at DESC, id DESC LIMIT 30
                """).param("user", user).param("job", jobId == null ? null : jobId.toString()).query(Result.class).list());
    }

    @GetMapping("/submissions/{id}")
    CareerResponse<Result> get(@CareerUser String user, @PathVariable UUID id) {
        return CareerResponse.ok(owned(user, id).result());
    }

    @PostMapping("/submissions")
    @org.springframework.transaction.annotation.Transactional(isolation = org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    CareerResponse<Result> submit(@CareerUser String user, @Valid @RequestBody Input input) {
        if (!judge.configured()) throw new ResponseStatusException(SERVICE_UNAVAILABLE, "判题服务尚未配置");
        String job = input.jobId() == null ? null : jobs.find(user, input.jobId().toString()).id();
        var existing = submission(user, input.requestId());
        if (existing.isEmpty()) {
            // Serialize the per-user limit and insert across instances.
            db.sql("SELECT id FROM career_task_scheduler WHERE id = 1 FOR UPDATE").query(Integer.class).single();
            existing = submission(user, input.requestId());
        }
        if (existing.isEmpty()) {
            int count = db.sql("""
                    SELECT COUNT(*) FROM career_judge_submission WHERE user_id = ? AND created_at > CURRENT_TIMESTAMP(6) - INTERVAL 1 HOUR
                    """).param(user).query(Integer.class).single();
            if (count >= 20) throw new ResponseStatusException(TOO_MANY_REQUESTS, "本小时提交次数已达上限");
            db.sql("SELECT id FROM career_judge_problem WHERE id = ? AND version = ?")
                    .params(input.problemId(), input.version()).query(String.class).optional()
                    .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "该题目版本不存在"));
            db.sql("""
                    INSERT INTO career_judge_submission (id, user_id, job_id, problem_id, version, submission)
                    VALUES (?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE id = id
                    """).param(1, input.requestId().toString()).param(2, user).param(3, job).param(4, input.problemId())
                    .param(5, input.version()).param(6, input.source()).update();
        }
        var saved = owned(user, input.requestId());
        var result = saved.result();
        if (!Objects.equals(result.jobId(), job) || !result.problemId().equals(input.problemId())
                || result.version() != input.version() || !saved.source().equals(input.source())) {
            throw new ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT, "提交编号已用于另一次作答");
        }
        return CareerResponse.ok(result);
    }

    @PostMapping("/submissions/{id}/retry")
    CareerResponse<Result> retry(@CareerUser String user, @PathVariable UUID id) {
        owned(user, id);
        db.sql("""
                UPDATE career_judge_submission SET status = 'QUEUED', sandbox_token = NULL, expires_at = NULL, ready_at = CURRENT_TIMESTAMP(6)
                WHERE user_id = ? AND id = ? AND status = 'SYSTEM_ERROR'
                """).params(user, id.toString()).update();
        return get(user, id);
    }

    @Scheduled(fixedDelay = 900)
    void dispatch() {
        if (!judge.configured() || !workers.tryAcquire()) return;
        Thread.startVirtualThread(() -> {
            try {
                String lease = UUID.randomUUID().toString();
                int changed = db.sql("""
                        UPDATE career_judge_submission
                        SET lease = :lease, ready_at = CURRENT_TIMESTAMP(6) + INTERVAL 20 SECOND, status = 'RUNNING'
                        WHERE status IN ('QUEUED','RUNNING') AND ready_at <= CURRENT_TIMESTAMP(6)
                        ORDER BY ready_at, created_at LIMIT 1
                        """).param("lease", lease).update();
                if (changed == 1) {
                    var work = db.sql("""
                            SELECT s.id, s.submission, s.sandbox_token, s.expires_at, s.passed, p.kind, p.tests
                            FROM career_judge_submission s JOIN career_judge_problem p ON p.id = s.problem_id AND p.version = s.version
                            WHERE s.lease = ?
                            """).param(lease).query((row, index) -> new Work(row.getString("id"), row.getString("submission"),
                                    row.getString("sandbox_token"), row.getTimestamp("expires_at"), row.getInt("passed"),
                                    row.getString("kind"), row.getString("tests"))).optional();
                    work.ifPresent(item -> execute(item, lease));
                }
            } finally {
                workers.release();
            }
        });
    }

    private void execute(Work work, String lease) {
        try {
            JsonNode tests = json.readTree(work.tests());
            if (work.token() == null) {
                String token = judge.submit(work.kind(), work.source(), tests.path(work.passed()));
                db.sql("""
                        UPDATE career_judge_submission SET sandbox_token = ?, lease = NULL,
                            expires_at = CURRENT_TIMESTAMP(6) + INTERVAL 90 SECOND, ready_at = CURRENT_TIMESTAMP(6)
                        WHERE id = ? AND lease = ?
                        """).params(token, work.id(), lease).update();
                return;
            }
            String status = judge.status(work.token());
            if ("ACCEPTED".equals(status)) {
                int passed = work.passed() + 1;
                save(work.id(), lease, passed == tests.size() ? "ACCEPTED" : "QUEUED", passed, false);
            } else if ("RUNNING".equals(status)) {
                if (work.expires().toInstant().isAfter(Instant.now())) save(work.id(), lease, "RUNNING", work.passed(), true);
                else save(work.id(), lease, "SYSTEM_ERROR", work.passed(), false);
            } else {
                save(work.id(), lease, status, work.passed(), false);
            }
        } catch (Exception failure) {
            log.warn("Judge attempt {} failed ({})", work.id(), failure instanceof org.springframework.web.client.RestClientResponseException http
                    ? http.getStatusCode() : failure.getClass().getSimpleName());
            save(work.id(), lease, "SYSTEM_ERROR", work.passed(), false);
        }
    }

    private void save(String id, String lease, String status, int passed, boolean retain) {
        db.sql("""
                UPDATE career_judge_submission SET status = :status, passed = :passed, lease = NULL,
                    sandbox_token = IF(:retain, sandbox_token, NULL), expires_at = IF(:retain, expires_at, NULL),
                    ready_at = CURRENT_TIMESTAMP(6)
                WHERE id = :id AND lease = :lease
                """).param("status", status).param("passed", passed).param("retain", retain).param("id", id).param("lease", lease).update();
    }

    private java.util.Optional<Stored> submission(String user, UUID id) {
        return db.sql("""
                SELECT id, job_id, problem_id, version, status, passed, created_at, submission
                FROM career_judge_submission WHERE user_id = ? AND id = ?
                """).params(user, id.toString()).query((row, index) -> new Stored(
                new Result(row.getString("id"), row.getString("problem_id"), row.getString("job_id"),
                        row.getInt("version"), row.getString("status"), row.getInt("passed"), row.getTimestamp("created_at")),
                row.getString("submission"))).optional();
    }

    private Stored owned(String user, UUID id) {
        return submission(user, id).orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "判题记录不存在"));
    }
    record Input(@NotNull UUID requestId, UUID jobId, @NotNull @Pattern(regexp = "[a-z0-9-]{1,64}") String problemId,
            @Positive int version, @NotBlank @Size(max = 16000) String source) {}
    record Problem(String id, int version, String kind, String topic, String prompt, String starter) {}
    record Catalog(boolean available, List<Problem> problems) {}
    record Result(String id, String problemId, String jobId, int version, String status, int passed, Timestamp createdAt) {}
    private record Stored(Result result, String source) {}
    private record Work(String id, String source, String token, Timestamp expires, int passed, String kind, String tests) {}
}

