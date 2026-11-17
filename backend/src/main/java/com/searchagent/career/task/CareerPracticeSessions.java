package com.searchagent.career.task;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.searchagent.career.job.JobService;
import com.searchagent.career.practice.PracticeService;
import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/career/practice/sessions")
class CareerPracticeSessions {
    private final JdbcClient db;
    private final ObjectMapper json;
    private final JobService jobs;
    private final PracticeService practice;
    private final CareerTasks tasks;
    private final CareerTaskStore taskStore;

    CareerPracticeSessions(JdbcClient db, ObjectMapper json, JobService jobs, PracticeService practice, CareerTasks tasks,
            CareerTaskStore taskStore) {
        this.db = db;
        this.json = json;
        this.jobs = jobs;
        this.practice = practice;
        this.tasks = tasks;
        this.taskStore = taskStore;
    }

    @PostMapping
    @Transactional(isolation = Isolation.READ_COMMITTED)
    CareerResponse<View> create(@CareerUser String user, @Valid @RequestBody Create input) {
        String job = input.jobId() == null ? null : jobs.find(user, input.jobId().toString()).id();
        if (new HashSet<>(input.questions()).size() != input.questions().size()) {
            throw new ResponseStatusException(BAD_REQUEST, "练习题目不能重复");
        }
        var items = new ArrayList<Item>();
        for (var item : input.questions()) {
            String topic;
            String prompt;
            if (item.type() == Type.OPEN) {
                if (job == null) throw new ResponseStatusException(BAD_REQUEST, "开放题练习需要目标岗位");
                var question = tasks.openQuestion(user, job, item.id(), item.version());
                topic = question.path("topic").asText();
                prompt = question.path("prompt").asText();
            } else {
                var question = practice.question(item.id(), item.version());
                topic = question.topic();
                prompt = question.prompt();
            }
            items.add(new Item(item.id(), item.version(), item.type(), topic, prompt));
        }
        String id = input.requestId().toString();
        db.sql("""
                INSERT INTO career_practice_session (id, user_id, job_id, questions)
                VALUES (?, ?, ?, ?) ON DUPLICATE KEY UPDATE id = id
                """).param(1, id).param(2, user).param(3, job).param(4, json.valueToTree(items).toString()).update();
        var row = find(user, input.requestId(), false);
        if (!Objects.equals(row.jobId(), job) || !row.questions().equals(items)) {
            throw new ResponseStatusException(CONFLICT, "此编号已用于另一组练习");
        }
        return CareerResponse.ok(view(user, row));
    }

    @GetMapping
    CareerResponse<List<Summary>> unfinished(@CareerUser String user, @RequestParam(required = false) UUID jobId) {
        return CareerResponse.ok(db.sql("""
                SELECT id, job_id, questions, position FROM career_practice_session
                WHERE user_id = ? AND job_id <=> ? AND finished_at IS NULL
                ORDER BY updated_at DESC, id DESC LIMIT 10
                """).param(1, user).param(2, jobId == null ? null : jobId.toString()).query(this::read).list()
                .stream().map(row -> new Summary(row.id(), row.position(), row.questions().size(),
                        row.questions().get(row.position()).prompt())).toList());
    }

    @GetMapping("/{id}")
    CareerResponse<View> get(@CareerUser String user, @PathVariable UUID id) {
        return CareerResponse.ok(view(user, find(user, id, false)));
    }

    @PostMapping("/{id}/advance")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    CareerResponse<View> advance(@CareerUser String user, @PathVariable UUID id, @Valid @RequestBody Advance input) {
        var row = find(user, id, true);
        if (row.position() > input.position()) return CareerResponse.ok(view(user, row));
        if (row.position() != input.position() || row.position() == row.questions().size()) {
            throw new ResponseStatusException(CONFLICT, "练习进度已更新");
        }
        var current = view(user, row);
        if (current.attempt() == null && current.taskId() == null) {
            throw new ResponseStatusException(CONFLICT, "请先提交当前问题的回答");
        }
        int next = row.position() + 1;
        db.sql("""
                UPDATE career_practice_session SET position = ?, finished_at = IF(?, CURRENT_TIMESTAMP(6), NULL)
                WHERE id = ? AND user_id = ?
                """).params(next, next == row.questions().size(), row.id(), user).update();
        return CareerResponse.ok(view(user, new Row(row.id(), row.jobId(), row.questions(), next)));
    }

    private Row find(String user, UUID id, boolean lock) {
        return db.sql("""
                SELECT id, job_id, questions, position FROM career_practice_session WHERE user_id = ? AND id = ?
                """ + (lock ? " FOR UPDATE" : "")).params(user, id.toString()).query(this::read).optional()
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "练习记录不存在"));
    }

    private Row read(java.sql.ResultSet result, int index) throws java.sql.SQLException {
        try {
            return new Row(result.getString("id"), result.getString("job_id"),
                    json.readValue(result.getString("questions"), new TypeReference<List<Item>>() {}), result.getInt("position"));
        } catch (JsonProcessingException error) {
            throw new java.sql.SQLException("Invalid practice questions", error);
        }
    }

    private View view(String user, Row row) {
        if (row.position() == row.questions().size()) {
            return new View(row.id(), row.jobId(), row.position(), row.questions().size(), null, null, null, null);
        }
        Item item = row.questions().get(row.position());
        UUID key = UUID.nameUUIDFromBytes((row.id() + ":" + row.position()).getBytes(StandardCharsets.UTF_8));
        PracticeService.Attempt attempt = item.type() != Type.SINGLE ? null : practice.attempt(user, key)
                .filter(value -> item.id().equals(value.questionId()) && item.version() == value.questionVersion()
                        && Objects.equals(row.jobId(), value.jobId())).orElse(null);
        String task = item.type() != Type.OPEN ? null : taskStore.byRequest(user, key)
                .filter(value -> "INTERVIEW".equals(value.kind()) && Objects.equals(row.jobId(), value.jobId())
                        && item.id().equals(value.request().path("questionId").asText())
                        && item.version() == value.request().path("questionVersion").asInt())
                .map(CareerTaskStore.Row::id).orElse(null);
        return new View(row.id(), row.jobId(), row.position(), row.questions().size(), item, key, attempt, task);
    }

    enum Type { SINGLE, OPEN }
    record Ref(@NotNull @Pattern(regexp = "[a-z0-9-]{1,64}") String id, @Positive int version, @NotNull Type type) {}
    record Item(String id, int version, Type type, String topic, String prompt) {}
    record Create(@NotNull UUID requestId, UUID jobId, @NotNull @Size(min = 1, max = 10) List<@NotNull @Valid Ref> questions) {}
    record Advance(@NotNull @PositiveOrZero Integer position) {}
    record Summary(String id, int position, int total, String prompt) {}
    record View(String id, String jobId, int position, int total, Item current, UUID answerRequestId,
            PracticeService.Attempt attempt, String taskId) {}
    private record Row(String id, String jobId, List<Item> questions, int position) {}
}

