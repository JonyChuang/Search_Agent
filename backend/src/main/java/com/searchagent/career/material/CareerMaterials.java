package com.searchagent.career.material;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import com.searchagent.career.job.JobService;
import com.searchagent.career.profile.ExperienceService;

@Service
class CareerMaterials {
    private final JdbcClient db;
    private final JobService jobs;
    private final ExperienceService experiences;
    private final ObjectMapper json;
    private final ResumeProfiles profiles;
    private final ApplicationWorkspace workspaces;

    CareerMaterials(JdbcClient db, JobService jobs, ExperienceService experiences, ObjectMapper json,
            ResumeProfiles profiles, ApplicationWorkspace workspaces) {
        this.db = db;
        this.jobs = jobs;
        this.experiences = experiences;
        this.json = json;
        this.profiles = profiles;
        this.workspaces = workspaces;
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
        if (existing == null || existing.profileRevision() != null || !jobId.equals(existing.jobId())
                || !java.util.stream.StreamSupport.stream(existing.evidence().spliterator(), false)
                    .map(fact -> UUID.fromString(fact.path("id").asText())).toList().equals(input.experienceIds())) {
            throw new ResponseStatusException(CONFLICT, "版本编号已用于另一份简历");
        }
        return existing;
    }

    List<Resume> resumes(String user) {
        return db.sql(RESUME_SELECT + " WHERE user_id = ? ORDER BY created_at DESC, id DESC")
                .param(user).query(this::resumeRow).list();
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    Resume compose(String user, CompositionInput input) {
        String requestId = input.requestId().toString();
        String jobId = input.jobId() == null ? null : input.jobId().toString();
        var saved = resumeQuery(user, requestId, true);
        if (saved == null) {
            var profile = profiles.get(user);
            if (profile.revision() != input.revision()) {
                // A simultaneous request may have already committed this version.
                saved = resumeQuery(user, requestId, true);
                if (saved == null) {
                    throw new ResponseStatusException(CONFLICT, "简历资料已更新，请核对后重新生成");
                }
            } else {
                var content = profile.content();
                if (content.name().isBlank() || content.entries().isEmpty()) {
                    throw new ResponseStatusException(BAD_REQUEST, "请填写姓名并添加至少一条经历");
                }
                var job = jobId == null ? null : jobs.find(user, jobId);
                String title = job != null ? job.title() : content.targetRole().isBlank() ? "通用简历" : content.targetRole();
                var design = content.snapshot(json);
                if (job != null && content.targetRole().isBlank()) {
                    design.put("targetRole", job.title());
                }
                db.sql("""
                        INSERT INTO career_resume_version
                            (id, user_id, job_id, company, job_title, request_id, evidence_json, profile_revision, design_json)
                        VALUES (:id, :user, :job, :company, :title, :request, '[]', :revision, :design)
                        ON DUPLICATE KEY UPDATE id = id
                        """).param("id", UUID.randomUUID().toString()).param("user", user)
                        .param("job", jobId, java.sql.Types.CHAR).param("company", job == null ? "" : job.company())
                        .param("title", title).param("request", requestId).param("revision", profile.revision())
                        .param("design", design.toString()).update();
                saved = resumeQuery(user, requestId, true);
            }
        }
        if (saved == null || !Objects.equals(saved.jobId(), jobId)
                || !Objects.equals(saved.profileRevision(), input.revision())) {
            throw new ResponseStatusException(CONFLICT, "版本编号已用于另一份简历");
        }
        return saved;
    }

    JsonNode composition(String user, UUID id) {
        return db.sql("""
                SELECT design_json FROM career_resume_version
                WHERE user_id = ? AND id = ? AND design_json IS NOT NULL
                """).params(user, id.toString()).query((rs, index) -> parse(rs.getString("design_json")))
                .optional().orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "找不到该简历版本"));
    }

    private static final String RESUME_SELECT = """
            SELECT id, job_id, company, job_title, evidence_json, created_at, profile_revision,
                   JSON_UNQUOTE(JSON_EXTRACT(design_json, '$.template')) AS template
            FROM career_resume_version
            """;

    private Resume resumeQuery(String user, String id, boolean byRequest) {
        return db.sql(RESUME_SELECT + " WHERE user_id = ? AND " + (byRequest ? "request_id" : "id") + " = ?")
                .params(user, id).query(this::resumeRow).optional().orElse(null);
    }

    private Resume resumeRow(java.sql.ResultSet rs, int index) throws java.sql.SQLException {
        return new Resume(rs.getString("id"), rs.getString("job_id"), rs.getString("company"),
                rs.getString("job_title"), parse(rs.getString("evidence_json")), rs.getTimestamp("created_at"),
                rs.getObject("profile_revision", Integer.class), rs.getString("template"));
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
        var existing = applicationByJob(user, jobId, false);
        if (existing.isPresent()) {
            return existing.get();
        }
        var job = jobs.find(user, jobId);
        var resume = validateResume(user, jobId, input.resumeId());
        return insertDraft(user, job, resume, answers(input.answers()), UUID.randomUUID().toString());
    }

    private Application insertDraft(String user, JobService.Entry job, String resume, String answers, String id) {
        db.sql("""
                INSERT INTO career_application (id, user_id, job_id, company, job_title, source_url, resume_id, answers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE id = id
                """).param(1, id).param(2, user).param(3, job.id()).param(4, job.company()).param(5, job.title())
                .param(6, job.sourceUrl()).param(7, resume).param(8, answers).update();
        var saved = applicationByJob(user, job.id(), true).orElseThrow();
        if (saved.id().equals(id)) {
            event(id, 1, Stage.DRAFT, null, null, null, EventType.STAGE);
        }
        return saved;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    WorkspaceState workspace(String user, UUID jobId) {
        String job = jobId.toString();
        var application = applicationByJob(user, job, false);
        if (application.isPresent()) return workspaceState(application.get());
        jobs.find(user, job);
        return new WorkspaceState(null, new ApplicationWorkspace.View(ApplicationWorkspace.Draft.empty(), List.of()), null);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    WorkspaceState saveWorkspace(String user, UUID jobId, WorkspaceInput input, Map<String, List<MultipartFile>> uploads) {
        String job = jobId.toString();
        var current = applicationByJob(user, job, true).orElse(null);
        if (current == null && input.revision() != 0) checkUpdate(0);
        var resume = validateResume(user, job, input.resumeId());
        String savedAnswers = answers(input.answers());
        boolean created = false;
        if (current == null) {
            String id = UUID.randomUUID().toString();
            current = insertDraft(user, jobs.find(user, job), resume, savedAnswers, id);
            created = id.equals(current.id());
        }
        String requestId = input.requestId().toString();
        String previousRequest = db.sql("SELECT COALESCE(workspace_request_id, '') FROM career_application WHERE id = ?")
                .param(current.id()).query(String.class).single();
        if (requestId.equals(previousRequest)) {
            if (!Objects.equals(current.resumeId(), resume) || !current.answers().equals(savedAnswers)
                    || !workspaces.load(current.id()).equals(input.content())) {
                throw new ResponseStatusException(CONFLICT, "保存编号已使用，请重新保存");
            }
            workspaces.saveFiles(current.id(), input.content(), uploads);
            return workspaceState(current);
        }
        if (!created && current.revision() != input.revision()) checkUpdate(0);
        requireEditable(current.id());

        workspaces.saveFiles(current.id(), input.content(), uploads);
        int revision = current.revision();
        checkUpdate(db.sql("""
                UPDATE career_application
                SET resume_id = ?, answers = ?, workspace_json = ?, workspace_request_id = ?, revision = revision + 1
                WHERE user_id = ? AND id = ? AND revision = ?
                """).param(1, resume).param(2, savedAnswers).param(3, json.valueToTree(input.content()).toString())
                .param(4, requestId).param(5, user).param(6, current.id()).param(7, revision).update());
        workspaces.prune(current.id(), input.content());
        var updated = application(user, UUID.fromString(current.id()));
        recordMaterialsUpdate(user, updated);
        return workspaceState(updated);
    }

    ApplicationWorkspace.Download applicationFile(String user, UUID applicationId, UUID fileId) {
        application(user, applicationId);
        return workspaces.download(applicationId.toString(), fileId);
    }

    private WorkspaceState workspaceState(Application application) {
        return new WorkspaceState(application, workspaces.view(application.id(), workspaces.load(application.id())),
                latestReceipt(application.id()));
    }

    private Optional<Application> applicationByJob(String user, String jobId, boolean lock) {
        return db.sql("SELECT * FROM career_application WHERE user_id = ? AND job_id = ?" + (lock ? " FOR UPDATE" : ""))
                .params(user, jobId).query(Application.class).optional();
    }

    @Transactional
    Application update(String user, UUID id, DraftInput input) {
        var current = db.sql("SELECT * FROM career_application WHERE user_id = ? AND id = ? FOR UPDATE")
                .params(user, id.toString()).query(Application.class).optional()
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "投递记录不存在"));
        var resume = validateResume(user, current.jobId(), input.resumeId());
        String updatedAnswers = answers(input.answers());
        if (current.revision() != input.revision()) checkUpdate(0);
        if (Objects.equals(current.resumeId(), resume) && current.answers().equals(updatedAnswers)) return current;
        requireEditable(current.id());
        checkUpdate(db.sql("""
                UPDATE career_application SET resume_id = ?, answers = ?, revision = revision + 1
                WHERE user_id = ? AND id = ? AND revision = ?
                """).param(1, resume).param(2, updatedAnswers).param(3, user)
                .param(4, id.toString()).param(5, input.revision()).update());
        var updated = application(user, id);
        recordMaterialsUpdate(user, updated);
        return updated;
    }

    private void requireEditable(String applicationId) {
        if (db.sql("SELECT COUNT(*) FROM career_application_browser WHERE application_id = ? AND state = 'VERIFYING'")
                .param(applicationId).query(Integer.class).single() != 0) {
            throw new ResponseStatusException(CONFLICT, "官网投递结果待核对，请先查看回执或确认未投递");
        }
    }

    @Transactional
    Application stage(String user, UUID id, StageInput input) {
        var current = application(user, id);
        if (input.receipt() != null && input.stage() != Stage.SUBMITTED) {
            throw new ResponseStatusException(BAD_REQUEST, "仅在记录已投递时填写回执");
        }
        if (current.stage() == input.stage()) {
            if (input.receipt() != null && !json.valueToTree(input.receipt()).equals(latestReceipt(current.id()))) {
                throw new ResponseStatusException(CONFLICT, "此岗位的投递状态已更新，请查看阶段历史");
            }
            return current;
        }
        checkUpdate(db.sql("""
                UPDATE career_application SET stage = ?, revision = revision + 1
                WHERE user_id = ? AND id = ? AND revision = ?
                """).params(input.stage().name(), user, id.toString(), input.revision()).update());
        var snapshot = input.stage() == Stage.SUBMITTED ? materials(user, current) : null;
        event(id.toString(), input.revision() + 1, input.stage(), input.note(), snapshot, input.receipt(), EventType.STAGE);
        if (input.stage() == Stage.SUBMITTED && input.receipt() != null) {
            db.sql("UPDATE career_application_browser SET state = 'CONFIRMED' WHERE application_id = ? AND state = 'VERIFYING'")
                    .param(id.toString()).update();
        }
        return application(user, id);
    }

    List<Application> applications(String user) {
        return db.sql("SELECT * FROM career_application WHERE user_id = ? ORDER BY updated_at DESC, id DESC")
                .param(user).query(Application.class).list();
    }

    List<Event> events(String user, UUID id) {
        application(user, id);
        return db.sql("""
                SELECT stage, note, created_at, event_type, material_snapshot, receipt_json FROM career_application_event
                WHERE application_id = ? ORDER BY revision DESC
                """).param(id.toString()).query((row, index) -> {
                    String snapshot = row.getString("material_snapshot");
                    return new Event(Stage.valueOf(row.getString("stage")), row.getString("note"), row.getTimestamp("created_at"),
                            EventType.valueOf(row.getString("event_type")), snapshot == null ? null : parse(snapshot),
                            row.getString("receipt_json") == null ? null : parse(row.getString("receipt_json")));
                }).list();
    }

    private JsonNode latestReceipt(String id) {
        return db.sql("""
                SELECT receipt_json FROM career_application_event
                WHERE application_id = ? AND receipt_json IS NOT NULL ORDER BY revision DESC LIMIT 1
                """).param(id).query((row, index) -> parse(row.getString(1))).optional().orElse(null);
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
        if (resume == null || !job.equals(resume.jobId())) {
            throw new ResponseStatusException(BAD_REQUEST, "请选择此岗位自己的简历版本");
        }
        return resume.id();
    }

    private MaterialsSnapshot materials(String user, Application application) {
        var resume = application.resumeId() == null ? null : resumeQuery(user, application.resumeId(), false);
        var workspace = workspaces.view(application.id(), workspaces.load(application.id()));
        workspaces.retain(application.id(), workspace);
        return new MaterialsSnapshot(application.resumeId(), resume == null ? null : resume.jobTitle(),
                resume == null ? null : resume.createdAt().toInstant(), application.answers(), workspace);
    }

    private void recordMaterialsUpdate(String user, Application updated) {
        if (updated.stage() != Stage.DRAFT) {
            event(updated.id(), updated.revision(), updated.stage(), null, materials(user, updated), null, EventType.MATERIALS_UPDATED);
        }
    }

    private void event(String id, int revision, Stage stage, String note, MaterialsSnapshot snapshot, Receipt receipt, EventType type) {
        db.sql("""
                INSERT INTO career_application_event (application_id, revision, stage, note, material_snapshot, receipt_json, event_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """).param(1, id).param(2, revision).param(3, stage.name()).param(4, note)
                .param(5, snapshot == null ? null : json.valueToTree(snapshot).toString())
                .param(6, receipt == null ? null : json.valueToTree(receipt).toString()).param(7, type.name()).update();
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
    enum EventType { STAGE, MATERIALS_UPDATED }

    record ResumeInput(@NotNull UUID requestId, @NotNull UUID jobId,
            @NotNull @Size(min = 1, max = 12) List<@NotNull UUID> experienceIds) {}
    record CompositionInput(@NotNull UUID requestId, UUID jobId, @NotNull @Positive Integer revision) {}
    record ApplicationInput(@NotNull UUID jobId, UUID resumeId, @Size(max = 12000) String answers) {}
    record DraftInput(@NotNull @Positive Integer revision, UUID resumeId, @Size(max = 12000) String answers) {}
    record WorkspaceInput(@NotNull UUID requestId, @NotNull @PositiveOrZero Integer revision, UUID resumeId,
            @Size(max = 12000) String answers, @NotNull @Valid ApplicationWorkspace.Draft content) {}
    record Receipt(@NotNull Instant submittedAt, @Size(max = 160) String applicationNumber) {}
    record StageInput(@NotNull @Positive Integer revision, @NotNull Stage stage, @Size(max = 1000) String note,
            @Valid Receipt receipt) {}

    record Resume(String id, String jobId, String company, String jobTitle, JsonNode evidence, Timestamp createdAt,
            Integer profileRevision, String template) {}
    record Application(String id, String jobId, String company, String jobTitle, String sourceUrl,
            String resumeId, String answers, Stage stage, int revision, Timestamp createdAt, Timestamp updatedAt) {}
    record WorkspaceState(Application application, ApplicationWorkspace.View workspace, JsonNode receipt) {}
    record MaterialsSnapshot(String resumeId, String resumeTitle, Instant resumeCreatedAt, String answers,
            ApplicationWorkspace.View workspace) {}
    record Event(Stage stage, String note, Timestamp createdAt, EventType eventType, JsonNode materials, JsonNode receipt) {}
}
