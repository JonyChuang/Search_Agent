package com.searchagent.career.task;

import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.searchagent.career.job.JobService;
import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/career/learning/jobs/{jobId}")
class CareerLearningController {
    private final JobService jobs;
    private final CareerTaskStore tasks;
    private final JdbcClient db;

    CareerLearningController(JobService jobs, CareerTaskStore tasks, JdbcClient db) {
        this.jobs = jobs;
        this.tasks = tasks;
        this.db = db;
    }

    @GetMapping("/questions")
    CareerResponse<List<Question>> questions(@CareerUser String user, @PathVariable UUID jobId) {
        String job = jobs.find(user, jobId.toString()).id();
        var result = new ArrayList<Question>();
        var prompts = new HashSet<String>();
        for (var task : tasks.learningQuestions(user, job)) {
            var questions = task.result().path("openQuestions");
            for (int index = 0; index < questions.size(); index++) {
                var question = questions.path(index);
                String prompt = question.path("prompt").asText();
                if (!prompts.add(prompt.strip().replaceAll("\\s+", " ").toLowerCase(Locale.ROOT))) continue;
                result.add(toQuestion(task, index));
            }
        }
        return CareerResponse.ok(List.copyOf(result));
    }

    @GetMapping("/questions/{id}")
    CareerResponse<Question> question(@CareerUser String user, @PathVariable UUID jobId, @PathVariable String id) {
        if (!id.matches("[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}-[0-4]")) throw missing();
        var task = tasks.owned(user, UUID.fromString(id.substring(0, 36))).filter(row ->
                jobId.toString().equals(row.jobId()) && "PREPARATION".equals(row.kind()) && "SUCCEEDED".equals(row.status()))
                .orElseThrow(CareerLearningController::missing);
        return CareerResponse.ok(toQuestion(task, id.charAt(37) - '0'));
    }

    private static Question toQuestion(CareerTaskStore.Row row, int index) {
        var question = row.result().path("openQuestions").path(index);
        if (!question.isObject()) throw missing();
        var references = row.agentContext() == null ? null : row.agentContext().get("references");
        return new Question(row.id() + "-" + index, 1, question.path("topic").asText(), question.path("prompt").asText(), references);
    }

    @GetMapping("/notes")
    CareerResponse<List<Note>> notes(@CareerUser String user, @PathVariable UUID jobId) {
        String job = jobs.find(user, jobId.toString()).id();
        return CareerResponse.ok(db.sql("""
                SELECT source_key, title, summary, source_url, document_id, document_title, document_revision, collected_at
                FROM career_learning_note WHERE user_id = ? AND job_id = ? ORDER BY collected_at DESC, source_key
                """).params(user, job).query(Note.class).list());
    }

    @PostMapping("/notes")
    CareerResponse<String> save(@CareerUser String user, @PathVariable UUID jobId, @Valid @RequestBody NoteInput input) {
        String job = jobs.find(user, jobId.toString()).id();
        var task = tasks.owned(user, input.taskId()).filter(row ->
                job.equals(row.jobId()) && "SUCCEEDED".equals(row.status())).orElseThrow(CareerLearningController::missing);
        Note note = switch (task.kind()) {
            case "DISCOVERY" -> webNote(task, input.index());
            case "PREPARATION" -> documentNote(task, input.index());
            default -> throw missing();
        };
        db.sql("""
                INSERT INTO career_learning_note (user_id, job_id, source_key, title, summary, source_url,
                    document_id, document_title, document_revision, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    title = IF(collected_at <= VALUES(collected_at), VALUES(title), title),
                    summary = IF(collected_at <= VALUES(collected_at), VALUES(summary), summary),
                    source_url = IF(collected_at <= VALUES(collected_at), VALUES(source_url), source_url),
                    document_title = IF(collected_at <= VALUES(collected_at), VALUES(document_title), document_title),
                    document_revision = IF(collected_at <= VALUES(collected_at), VALUES(document_revision), document_revision),
                    collected_at = GREATEST(collected_at, VALUES(collected_at))
                """).param(1, user).param(2, job).param(3, note.sourceKey()).param(4, note.title()).param(5, note.summary())
                .param(6, note.sourceUrl()).param(7, note.documentId()).param(8, note.documentTitle())
                .param(9, note.documentRevision()).param(10, note.collectedAt()).update();
        return CareerResponse.ok(note.sourceKey());
    }

    private static Note webNote(CareerTaskStore.Row task, int index) {
        var source = task.result().path("sources").path(index);
        if (!source.isObject()) throw missing();
        String url = source.path("url").asText();
        String identity = normalizeUrl(url);
        if (identity == null) throw missing();
        Instant collected = Instant.parse(task.result().path("searchedAt").asText(task.updatedAt().toString()));
        return new Note(key(identity), source.path("title").asText(), source.path("snippet").asText(),
                url, null, null, null, Timestamp.from(collected));
    }

    private static Note documentNote(CareerTaskStore.Row task, int index) {
        var note = task.result().path("notes").path(index);
        if (!note.isObject() || task.agentContext() == null) throw missing();
        var reference = task.agentContext().path("references").path(note.path("reference").asInt() - 1);
        if (!reference.isObject()) throw missing();
        String id = reference.path("id").asText();
        String title = note.path("title").asText();
        return new Note(key(id + "\n" + title.strip().replaceAll("\\s+", " ").toLowerCase(Locale.ROOT)), title,
                note.path("summary").asText(), null, id, reference.path("title").asText(),
                reference.path("revision").asText(), Timestamp.from(task.updatedAt()));
    }

    static String normalizeUrl(String value) {
        try {
            URI uri = new URI(value.strip()).normalize();
            if (uri.getHost() == null || uri.getScheme() == null || uri.getRawUserInfo() != null
                    || !List.of("http", "https").contains(uri.getScheme().toLowerCase(Locale.ROOT))) return null;
            String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
            int port = uri.getPort();
            if ((port == 443 && scheme.equals("https")) || (port == 80 && scheme.equals("http"))) port = -1;
            String path = uri.getRawPath().isEmpty() ? "/" : uri.getRawPath();
            String query = uri.getRawQuery() == null ? "" : java.util.Arrays.stream(uri.getRawQuery().split("&"))
                    .filter(part -> !part.toLowerCase(Locale.ROOT).startsWith("utm_")).collect(java.util.stream.Collectors.joining("&"));
            return scheme + "://" + uri.getHost().toLowerCase(Locale.ROOT) + (port < 0 ? "" : ":" + port)
                    + path + (query.isEmpty() ? "" : "?" + query);
        } catch (URISyntaxException error) {
            return null;
        }
    }

    private static String key(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException(error);
        }
    }

    private static ResponseStatusException missing() {
        return new ResponseStatusException(NOT_FOUND, "找不到所选的备考内容");
    }

    record Question(String id, int version, String topic, String prompt, JsonNode references) {}
    record Note(String sourceKey, String title, String summary, String sourceUrl, String documentId,
            String documentTitle, String documentRevision, Timestamp collectedAt) {}
    record NoteInput(@NotNull UUID taskId, @NotNull @Min(0) @Max(9) Integer index) {}
}

