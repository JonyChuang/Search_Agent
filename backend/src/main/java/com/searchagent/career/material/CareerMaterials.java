package com.searchagent.career.material;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.sql.Timestamp;
import java.util.HashSet;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import com.searchagent.career.job.JobService;
import com.searchagent.career.profile.ExperienceService;

@Service
class CareerMaterials {
    private final JdbcClient db;
    private final JobService jobs;
    private final ExperienceService experiences;
    private final ObjectMapper json;

    CareerMaterials(JdbcClient db, JobService jobs, ExperienceService experiences, ObjectMapper json) {
        this.db = db;
        this.jobs = jobs;
        this.experiences = experiences;
        this.json = json;
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    Resume generate(String user, ResumeInput input) {
        String requestId = input.requestId().toString();
        String jobId = input.jobId().toString();
        var existing = resumeQuery(user, requestId, true);
        if (existing == null) {
            var job = jobs.find(user, jobId);
            if (new HashSet<>(input.experienceIds()).size() != input.experienceIds().size()) {
                throw new ResponseStatusException(BAD_REQUEST, "经历不能重复");
            }
            var evidence = input.experienceIds().stream().map(key -> {
                var entry = experiences.find(user, key.toString());
                if (!entry.confirmed()) {
                    throw new ResponseStatusException(BAD_REQUEST, "简历只能使用已确认的经历");
                }
                return entry;
            }).toList();
            db.sql("""
                    INSERT INTO career_resume_version (id, user_id, job_id, company, job_title, request_id, evidence_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE id = id
                    """).params(UUID.randomUUID().toString(), user, jobId, job.company(), job.title(),
                            requestId, json.valueToTree(evidence).toString()).update();
            existing = resumeQuery(user, requestId, true);
        }
        if (existing == null || !existing.jobId().equals(jobId)
                || !java.util.stream.StreamSupport.stream(existing.evidence().spliterator(), false)
                    .map(fact -> UUID.fromString(fact.path("id").asText())).toList().equals(input.experienceIds())) {
            throw new ResponseStatusException(CONFLICT, "版本编号已用于另一份简历");
        }
        return existing;
    }

    List<Resume> resumes(String user) {
        return db.sql("""
                SELECT id, job_id, company, job_title, evidence_json, created_at FROM career_resume_version
                WHERE user_id = ? ORDER BY created_at DESC, id DESC
                """).param(user).query((rs, index) -> new Resume(rs.getString("id"), rs.getString("job_id"),
                rs.getString("company"), rs.getString("job_title"), parse(rs.getString("evidence_json")),
                rs.getTimestamp("created_at"))).list();
    }

    private Resume resumeQuery(String user, String id, boolean byRequest) {
        return db.sql("""
                SELECT id, job_id, company, job_title, evidence_json, created_at FROM career_resume_version
                WHERE user_id = ? AND
                """ + (byRequest ? "request_id" : "id") + " = ?").params(user, id).query((rs, index) -> new Resume(rs.getString("id"), rs.getString("job_id"),
                rs.getString("company"), rs.getString("job_title"), parse(rs.getString("evidence_json")),
                rs.getTimestamp("created_at"))).optional().orElse(null);
    }

    private JsonNode parse(String value) throws java.sql.SQLException {
        try {
            return json.readTree(value);
        } catch (com.fasterxml.jackson.core.JsonProcessingException error) {
            throw new java.sql.SQLException("Invalid stored resume evidence", error);
        }
    }

    @Transactional
    Application create(String user, ApplicationInput input) {
        String jobId = input.jobId().toString();
        var existing = db.sql("SELECT * FROM career_application WHERE user_id = ? AND job_id = ?")
                .params(user, jobId).query(Application.class).optional();
        if (existing.isPresent()) {
            return existing.get();
        }
        var job = jobs.find(user, jobId);
        var resume = validateResume(user, jobId, input.resumeId());
        String id = UUID.randomUUID().toString();
        db.sql("""
                INSERT INTO career_application (id, user_id, job_id, company, job_title, source_url, resume_id, answers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE id = id
                """).param(1, id).param(2, user).param(3, jobId).param(4, job.company()).param(5, job.title())
                .param(6, job.sourceUrl()).param(7, resume).param(8, answers(input.answers())).update();
        var saved = db.sql("SELECT * FROM career_application WHERE user_id = ? AND job_id = ? FOR UPDATE")
                .params(user, jobId).query(Application.class).single();
        if (saved.id().equals(id)) {
            event(id, 1, Stage.DRAFT, null);
        }
        return saved;
    }

    @Transactional
    Application update(String user, UUID id, DraftInput input) {
        var current = application(user, id);
        var resume = validateResume(user, current.jobId(), input.resumeId());
        checkUpdate(db.sql("""
                UPDATE career_application SET resume_id = ?, answers = ?, revision = revision + 1
                WHERE user_id = ? AND id = ? AND revision = ?
                """).param(1, resume).param(2, answers(input.answers())).param(3, user)
                .param(4, id.toString()).param(5, input.revision()).update());
        return application(user, id);
    }

    @Transactional
    Application stage(String user, UUID id, StageInput input) {
        var current = application(user, id);
        if (current.stage() == input.stage()) {
            return current;
        }
        checkUpdate(db.sql("""
                UPDATE career_application SET stage = ?, revision = revision + 1
                WHERE user_id = ? AND id = ? AND revision = ?
                """).params(input.stage().name(), user, id.toString(), input.revision()).update());
        event(id.toString(), input.revision() + 1, input.stage(), input.note());
        return application(user, id);
    }

    List<Application> applications(String user) {
        return db.sql("SELECT * FROM career_application WHERE user_id = ? ORDER BY updated_at DESC, id DESC")
                .param(user).query(Application.class).list();
    }

    List<Event> events(String user, UUID id) {
        application(user, id);
        return db.sql("""
                SELECT stage, note, created_at FROM career_application_event
                WHERE application_id = ? ORDER BY revision DESC
                """).param(id.toString()).query(Event.class).list();
    }

    private Application application(String user, UUID id) {
        return db.sql("SELECT * FROM career_application WHERE user_id = ? AND id = ?")
                .params(user, id.toString()).query(Application.class).optional()
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "投递记录不存在"));
    }

    private String validateResume(String user, String job, UUID id) {
        if (id == null) {
            return null;
        }
        var resume = resumeQuery(user, id.toString(), false);
        if (resume == null || !resume.jobId().equals(job)) {
            throw new ResponseStatusException(BAD_REQUEST, "请选择此岗位自己的简历版本");
        }
        return resume.id();
    }

    private void event(String id, int revision, Stage stage, String note) {
        db.sql("INSERT INTO career_application_event (application_id, revision, stage, note) VALUES (?, ?, ?, ?)")
                .param(1, id).param(2, revision).param(3, stage.name()).param(4, note).update();
    }

    private static String answers(String value) {
        return value == null ? "" : value.strip();
    }

    private static void checkUpdate(int changed) {
        if (changed != 1) {
            throw new ResponseStatusException(CONFLICT, "记录已更新，请刷新后重试");
        }
    }

    enum Stage { DRAFT, SUBMITTED, SCREENING, INTERVIEW, OFFER, REJECTED, WITHDRAWN }

    record ResumeInput(@NotNull UUID requestId, @NotNull UUID jobId,
            @NotNull @Size(min = 1, max = 12) List<@NotNull UUID> experienceIds) {}
    record ApplicationInput(@NotNull UUID jobId, UUID resumeId, @Size(max = 12000) String answers) {}
    record DraftInput(@NotNull @Positive Integer revision, UUID resumeId, @Size(max = 12000) String answers) {}
    record StageInput(@NotNull @Positive Integer revision, @NotNull Stage stage, @Size(max = 1000) String note) {}

    record Resume(String id, String jobId, String company, String jobTitle, JsonNode evidence, Timestamp createdAt) {}
    record Application(String id, String jobId, String company, String jobTitle, String sourceUrl,
            String resumeId, String answers, Stage stage, int revision, Timestamp createdAt, Timestamp updatedAt) {}
    record Event(Stage stage, String note, Timestamp createdAt) {}
}
