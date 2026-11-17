package com.searchagent.career.material;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.net.URI;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Instant;
import java.sql.Timestamp;
import java.util.Base64;
import java.util.HexFormat;
import java.util.UUID;
import java.time.temporal.ChronoUnit;

import com.searchagent.career.job.JobService;
import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/career/application-browser")
class ApplicationBrowser {
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final java.util.Set<String> PRE_SUBMISSION = java.util.Set.of("PREPARED", "NEEDS_USER");
    private final JdbcClient db;
    private final CareerMaterials materials;
    private final JobService jobs;

    ApplicationBrowser(JdbcClient db, CareerMaterials materials, JobService jobs) {
        this.db = db;
        this.materials = materials;
        this.jobs = jobs;
    }

    @PostMapping("/applications/{applicationId}/ticket")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    CareerResponse<Ticket> issue(@CareerUser String user, @PathVariable UUID applicationId,
            @RequestBody @Valid Applicant input) {
        var application = application(user, applicationId.toString());
        if (!"DRAFT".equals(application.stage()) || application.resumeId() == null) {
            throw new ResponseStatusException(CONFLICT, "请先保存待投递的简历版本和网申草稿");
        }
        var prior = db.sql("SELECT state FROM career_application_browser WHERE application_id = ?")
                .param(applicationId.toString()).query(String.class).optional();
        if (prior.filter(state -> state.equals("VERIFYING") || state.equals("CONFIRMED")).isPresent()) {
            throw new ResponseStatusException(CONFLICT, "已有投递正在核对，请先查看原申请结果");
        }
        String source = jobs.find(user, application.jobId()).sourceUrl();
        String target = targetPath(source);
        var workspace = materials.workspace(user, UUID.fromString(application.jobId()));
        var answers = workspace.workspace().content().form();
        if (answers.email() == null || answers.email().isBlank()) {
            throw new ResponseStatusException(BAD_REQUEST, "请先在网申材料填好邮箱并保存");
        }
        byte[] token = new byte[32];
        RANDOM.nextBytes(token);
        String id = UUID.randomUUID().toString();
        Instant expires = Instant.now().plus(1, ChronoUnit.DAYS);
        db.sql("""
                INSERT INTO career_application_browser
                    (application_id, id, revision, token_hash, target_path, state, expires_at)
                VALUES (?, ?, ?, ?, ?, 'PREPARED', ?)
                ON DUPLICATE KEY UPDATE id = VALUES(id), revision = VALUES(revision), token_hash = VALUES(token_hash),
                    target_path = VALUES(target_path), state = 'PREPARED', expires_at = VALUES(expires_at),
                    requested_at = NULL, evidence_url = NULL
                """).params(applicationId.toString(), id, application.revision(), HexFormat.of().formatHex(hash(token)),
                        target, Timestamp.from(expires)).update();
        return CareerResponse.ok(new Ticket(id, Base64.getUrlEncoder().withoutPadding().encodeToString(token),
                source, input.firstName().strip(), input.lastName().strip(), new Contact(answers.email(), answers.phone()), expires));
    }

    @GetMapping("/applications/{applicationId}/status")
    CareerResponse<String> status(@CareerUser String user, @PathVariable UUID applicationId) {
        db.sql("SELECT id FROM career_application WHERE id = ? AND user_id = ?")
                .params(applicationId.toString(), user).query(String.class).optional().orElseThrow(ApplicationBrowser::missing);
        return CareerResponse.ok(db.sql("SELECT state FROM career_application_browser WHERE application_id = ?")
                .param(applicationId.toString()).query(String.class).optional().orElse("NONE"));
    }

    @PostMapping("/applications/{applicationId}/release")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    CareerResponse<String> release(@CareerUser String user, @PathVariable UUID applicationId) {
        var current = application(user, applicationId.toString());
        if (!"DRAFT".equals(current.stage()) || db.sql("""
                UPDATE career_application_browser SET state = 'RELEASED' WHERE application_id = ? AND state = 'VERIFYING'
                """).param(applicationId.toString()).update() != 1) throw conflict();
        return CareerResponse.ok("RELEASED");
    }

    @PostMapping("/runs/{id}/event")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    CareerResponse<String> callback(@PathVariable UUID id, @RequestHeader("X-Application-Run") String token,
            @RequestBody @Valid Event input) {
        // Lock the parent first; creation, work authorization and receipt use the same order.
        var prior = run(id, false);
        application(prior.owner(), prior.applicationId());
        var current = run(id, true);
        verify(current, token);
        if (!current.targetPath().equals(targetPath(input.url()))) {
            throw new ResponseStatusException(CONFLICT, "当前页面不属于此岗位");
        }
        var application = application(current.owner(), current.applicationId());
        String state;
        switch (input.action()) {
            case "REVIEW" -> {
                if (!PRE_SUBMISSION.contains(current.state()) || application.revision() != current.revision()) throw conflict();
                state = "NEEDS_USER";
            }
            case "PERMIT" -> {
                if (!"NEEDS_USER".equals(current.state()) || !"DRAFT".equals(application.stage())
                        || application.revision() != current.revision()) throw conflict();
                String source = jobs.find(current.owner(), application.jobId()).sourceUrl();
                if (!current.targetPath().equals(targetPath(source))) throw conflict();
                db.sql("UPDATE career_application_browser SET requested_at = CURRENT_TIMESTAMP(6) WHERE id = ?")
                        .param(id.toString()).update();
                state = "VERIFYING";
            }
            case "CONFIRM" -> {
                if ("CONFIRMED".equals(current.state())) return CareerResponse.ok(current.state());
                if (!"VERIFYING".equals(current.state()) || !"DRAFT".equals(application.stage())
                        || current.requestedAt() == null || application.revision() != current.revision()) throw conflict();
                materials.stage(current.owner(), UUID.fromString(current.applicationId()), new CareerMaterials.StageInput(
                        application.revision(), CareerMaterials.Stage.SUBMITTED, "Greenhouse 招聘页确认",
                        new CareerMaterials.Receipt(current.requestedAt().toInstant(), input.applicationNumber())));
                db.sql("UPDATE career_application_browser SET evidence_url = ? WHERE id = ?")
                        .params(input.url(), id.toString()).update();
                state = "CONFIRMED";
            }
            default -> throw new ResponseStatusException(BAD_REQUEST, "浏览器操作无效");
        }
        db.sql("UPDATE career_application_browser SET state = ? WHERE id = ?").params(state, id.toString()).update();
        return CareerResponse.ok(state);
    }

    private AppRow application(String user, String id) {
        return db.sql("""
                SELECT job_id, resume_id, stage, revision FROM career_application WHERE id = ? AND user_id = ? FOR UPDATE
                """).params(id, user).query(AppRow.class).optional().orElseThrow(ApplicationBrowser::missing);
    }

    private Run run(UUID id, boolean lock) {
        return db.sql("""
                SELECT b.application_id, a.user_id AS owner, b.revision, b.token_hash, b.target_path, b.state,
                    b.requested_at, b.expires_at
                FROM career_application_browser b JOIN career_application a ON a.id = b.application_id WHERE b.id = ?
                """ + (lock ? " FOR UPDATE" : "")).param(id.toString()).query(Run.class)
                .optional().orElseThrow(ApplicationBrowser::missing);
    }

    static String targetPath(String source) {
        try {
            URI uri = URI.create(source == null ? "" : source);
            if ("https".equals(uri.getScheme()) && "job-boards.greenhouse.io".equals(uri.getHost())
                    && uri.getPort() == -1 && uri.getUserInfo() == null
                    && uri.getPath().matches("/[a-zA-Z0-9_-]{1,100}/jobs/[0-9]{1,20}/?")) {
                return uri.getPath().replaceFirst("/$", "");
            }
        } catch (IllegalArgumentException ignored) {
            // Report unsupported addresses consistently.
        }
        throw new ResponseStatusException(BAD_REQUEST, "请使用 job-boards.greenhouse.io 上的岗位申请链接");
    }

    private static void verify(Run run, String token) {
        try {
            if (token.length() == 43 && run.expiresAt().toInstant().isAfter(Instant.now()) && MessageDigest.isEqual(
                    HexFormat.of().parseHex(run.tokenHash()), hash(Base64.getUrlDecoder().decode(token)))) return;
        } catch (IllegalArgumentException ignored) {
            // Invalid encoding is treated as an invalid ticket.
        }
        throw missing();
    }

    private static byte[] hash(byte[] token) {
        try { return MessageDigest.getInstance("SHA-256").digest(token); }
        catch (NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }

    private static ResponseStatusException missing() { return new ResponseStatusException(NOT_FOUND, "浏览器填表凭证不存在或已过期"); }
    private static ResponseStatusException conflict() { return new ResponseStatusException(CONFLICT, "投递状态或材料已变化，请返回网申助手核对"); }

    record Applicant(@NotBlank @Size(max = 80) String firstName, @NotBlank @Size(max = 80) String lastName) {}
    record Event(@NotBlank @Size(max = 20) String action, @NotBlank @Size(max = 2048) String url,
            @Size(max = 160) String applicationNumber) {}
    record Ticket(String id, String token, String target, String firstName, String lastName,
            Contact answers, Instant expiresAt) {}
    record Contact(String email, String phone) {}
    private record AppRow(String jobId, String resumeId, String stage, int revision) {}
    private record Run(String applicationId, String owner, int revision, String tokenHash, String targetPath,
            String state, Timestamp requestedAt, Timestamp expiresAt) {}
}

