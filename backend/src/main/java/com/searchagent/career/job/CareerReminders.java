package com.searchagent.career.job;

import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/career/reminders")
class CareerReminders {
    private static final String COLUMNS = "id, job_id, type, title, due_at, status, revision, external_delivery, delivery_state, "
            + "(status = 'PENDING' AND due_at <= CURRENT_TIMESTAMP(6)) AS due";
    private final JdbcClient db;
    private final JobService jobs;

    CareerReminders(JdbcClient db, JobService jobs) {
        this.db = db;
        this.jobs = jobs;
    }

    @GetMapping
    CareerResponse<List<Reminder>> list(@CareerUser String user, @RequestParam(required = false) UUID jobId) {
        return CareerResponse.ok(db.sql("SELECT " + COLUMNS + """
                 FROM career_reminder WHERE user_id = :user AND (:job IS NULL OR job_id = :job)
                    ORDER BY (status = 'PENDING') DESC, due_at ASC, id ASC LIMIT 100
                """).param("user", user).param("job", jobId == null ? null : jobId.toString()).query(Reminder.class).list());
    }

    @GetMapping("/due-count")
    CareerResponse<Integer> count(@CareerUser String user) {
        return CareerResponse.ok(db.sql("""
                SELECT COUNT(*) FROM career_reminder WHERE user_id = ? AND status = 'PENDING'
                    AND due_at <= CURRENT_TIMESTAMP(6)
                """).param(user).query(Integer.class).single());
    }

    @PostMapping
    CareerResponse<Reminder> create(@CareerUser String user, @Valid @RequestBody Create input) {
        var item = input.reminder();
        var job = ownedJob(user, item.jobId());
        String id = input.requestId().toString();
        Instant timestamp = item.dueAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS);
        db.sql("""
                INSERT INTO career_reminder (id, user_id, job_id, type, title, due_at, external_delivery, delivery_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE id = id
                """).param(1, id).param(2, user).param(3, job).param(4, item.type().name())
                .param(5, item.title().strip()).param(6, Timestamp.from(timestamp)).param(7, item.externalDelivery())
                .param(8, item.externalDelivery() ? "READY" : "IN_APP").update();
        var reminder = find(user, input.requestId());
        if (!Objects.equals(reminder.jobId(), job) || !reminder.type().equals(item.type().name())
                || !reminder.title().equals(item.title().strip()) || !reminder.dueAt().toInstant().equals(timestamp)
                || reminder.externalDelivery() != item.externalDelivery()) {
            throw new ResponseStatusException(CONFLICT, "此编号已用于另一条提醒");
        }
        return CareerResponse.ok(reminder);
    }

    @PutMapping("/{id}")
    CareerResponse<Reminder> edit(@CareerUser String user, @PathVariable UUID id, @Valid @RequestBody Edit input) {
        find(user, id);
        var item = input.reminder();
        var job = ownedJob(user, item.jobId());
        var changed = db.sql("""
                UPDATE career_reminder SET job_id = :job, type = :type, title = :title,
                   delivery_state = CASE WHEN delivery_state IN ('SENT', 'UNDELIVERED') AND due_at = :due
                       THEN delivery_state ELSE :delivery END,
                   due_at = :due, revision = revision + 1, external_delivery = :external, delivery_started_at = NULL
                WHERE id = :id AND user_id = :user AND status = 'PENDING' AND revision = :revision
                   AND delivery_state NOT IN ('SENDING', 'UNKNOWN')
                   AND (delivery_state NOT IN ('SENT', 'UNDELIVERED') OR due_at = :due OR :due > CURRENT_TIMESTAMP(6))
                """).param("job", job).param("type", item.type().name()).param("title", item.title().strip())
                .param("due", Timestamp.from(item.dueAt())).param("external", item.externalDelivery())
                .param("delivery", item.externalDelivery() ? "READY" : "IN_APP").param("id", id.toString())
                .param("user", user).param("revision", input.revision()).update();
        if (changed != 1) throw new ResponseStatusException(CONFLICT, "提醒已更新，请刷新后重试");
        return CareerResponse.ok(find(user, id));
    }

    @PostMapping("/{id}/state")
    CareerResponse<Reminder> change(@CareerUser String user, @PathVariable UUID id, @Valid @RequestBody Transition input) {
        var current = find(user, id);
        if (current.status().equals(input.status().name()) && current.revision() == input.revision() + 1) {
            return CareerResponse.ok(current);
        }
        var changed = db.sql("""
                UPDATE career_reminder SET status = ?, revision = revision + 1
                WHERE id = ? AND user_id = ? AND status = 'PENDING' AND revision = ?
                """).params(input.status().name(), id.toString(), user, input.revision()).update();
        if (changed != 1) throw new ResponseStatusException(CONFLICT, "提醒已更新，请刷新后重试");
        return CareerResponse.ok(find(user, id));
    }

    private String ownedJob(String user, UUID id) {
        return id == null ? null : jobs.find(user, id.toString()).id();
    }

    private Reminder find(String user, UUID id) {
        return db.sql("SELECT " + COLUMNS + " FROM career_reminder WHERE user_id = ? AND id = ?")
                .params(user, id.toString()).query(Reminder.class).optional()
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "提醒不存在"));
    }

    enum Type { REVIEW, INTERVIEW, APPLICATION }
    enum Status { DONE, CANCELLED }
    record Input(UUID jobId, @NotNull Type type, @NotBlank @Size(max = 160) String title, @NotNull Instant dueAt,
            boolean externalDelivery) {}
    record Create(@NotNull UUID requestId, @NotNull @Valid Input reminder) {}
    record Edit(@Positive int revision, @NotNull @Valid Input reminder) {}
    record Transition(@Positive int revision, @NotNull Status status) {}
    record Reminder(String id, String jobId, String type, String title, Timestamp dueAt, String status, int revision,
            boolean externalDelivery, String deliveryState, boolean due) {}
}

