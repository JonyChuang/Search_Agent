package com.searchagent.career.practice;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.FORBIDDEN;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.ZoneId;
import java.sql.Timestamp;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
class PublicLearningContent {
    private final JdbcClient db;
    private final ObjectMapper json;
    private final List<String> curators;

    PublicLearningContent(JdbcClient db, ObjectMapper json, @Value("${career.content.curators:}") String curators) {
        this.db = db;
        this.json = json;
        this.curators = Arrays.stream(curators.split(",")).map(String::strip)
                .filter(value -> !value.isEmpty()).map(value -> UUID.fromString(value).toString()).toList();
    }

    boolean canReview(String user) {
        return curators.contains(user);
    }

    void authorize(String user) {
        if (!canReview(user)) throw new ResponseStatusException(FORBIDDEN, "只有题库维护者可以审核公开内容");
    }

    List<Draft> list(String user, String status, int page) {
        authorize(user);
        if (!List.of("DRAFT", "PUBLISHED", "DISMISSED").contains(status) || page < 1) throw invalid("审核筛选无效");
        return db.sql("""
                SELECT id, kind, status, payload, base_version, revision, updated_at FROM career_content_draft
                WHERE status = ? ORDER BY updated_at DESC, id DESC LIMIT 21 OFFSET ?
                """).params(status, (page - 1L) * 20).query(this::read).list();
    }

    @Transactional
    Draft create(String user, Kind kind, Content input) {
        authorize(user);
        Content content = clean(input);
        validate(kind, content);
        Integer base = kind == Kind.QUESTION && content.targetId() != null ? questionVersion(content.targetId()) : null;
        if (base != null && base == 0) throw invalid("找不到要修订的公开题目");
        String id = UUID.randomUUID().toString();
        db.sql("INSERT INTO career_content_draft (id, kind, payload, base_version) VALUES (?, ?, ?, ?)")
                .param(1, id).param(2, kind.name()).param(3, encode(content)).param(4, base).update();
        return find(id, false);
    }

    @Transactional
    Draft update(String user, UUID id, int revision, Content input) {
        authorize(user);
        var current = edit(id, revision);
        Content content = clean(input);
        if (!java.util.Objects.equals(content.targetId(), current.content().targetId())) {
            throw invalid("请重新创建草稿以选择另一道题");
        }
        validate(current.kind(), content);
        db.sql("UPDATE career_content_draft SET payload = ?, revision = revision + 1 WHERE id = ?")
                .params(encode(content), current.id()).update();
        return find(current.id(), false);
    }

    @Transactional
    Draft publish(String user, UUID id, int revision) {
        authorize(user);
        var current = find(id.toString(), true);
        if ("PUBLISHED".equals(current.status()) && current.revision() == revision + 1) return current;
        requireRevision(current, revision);
        var item = current.content();
        validate(current.kind(), item);
        LocalDate today = LocalDate.now(ZoneId.of("Asia/Shanghai"));
        if (current.kind() == Kind.NOTE) {
            String url = webUrl(item.sourceUrl());
            String noteId = db.sql("SELECT id FROM career_interview_note WHERE SUBSTRING_INDEX(source_url, '#', 1) = ? LIMIT 1")
                    .param(url).query(String.class).optional().orElseGet(() -> "managed-" + sourceKey(url));
            db.sql("""
                    INSERT INTO career_interview_note
                        (id, role, company, title, summary, source_name, source_url, published_on, sourced_on)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE role = VALUES(role), company = VALUES(company), title = VALUES(title),
                        summary = VALUES(summary), source_name = VALUES(source_name), source_url = VALUES(source_url),
                        published_on = VALUES(published_on), sourced_on = VALUES(sourced_on)
                    """).params(noteId, item.role(), item.company(), item.title(), item.explanation(),
                            item.sourceName(), item.sourceUrl(), item.publishedOn(), today).update();
        } else {
            int base = current.baseVersion() == null ? 0 : current.baseVersion();
            String question = item.targetId() == null ? "managed-" + id : item.targetId();
            if (item.targetId() != null) {
                int live = db.sql("""
                        SELECT version FROM career_question_version WHERE id = ? ORDER BY version DESC LIMIT 1 FOR UPDATE
                        """).param(question).query(Integer.class).optional().orElse(0);
                if (live != base) throw new ResponseStatusException(CONFLICT, "公开题目已更新，请基于新版本重新建稿");
            }
            int version = base + 1;
            var options = item.options();
            db.sql("""
                    INSERT INTO career_question_version (id, version, grading_version, role, topic, prompt,
                        option_a, option_b, option_c, option_d, correct_answer, explanation, source_name, source_url, sourced_on)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """).params(question, version, version, item.role(), item.topic(), item.title(), options.get(0), options.get(1),
                            options.get(2), options.get(3), item.correctAnswer(), item.explanation(), item.sourceName(),
                            item.sourceUrl(), today).update();
        }
        return changeStatus(current, "PUBLISHED", user);
    }

    @Transactional
    Draft dismiss(String user, UUID id, int revision) {
        authorize(user);
        return changeStatus(edit(id, revision), "DISMISSED", user);
    }

    void stageFeedNote(String source, String url, String title, LocalDate publication) {
        String canonical = webUrl(url);
        if (canonical == null || canonical.length() > 2048 || title.isBlank()) return;
        String key = sourceKey(canonical + "\n" + title.strip() + "\n" + publication);
        var item = new Content(null, "", "", limit(title.strip(), 160), "", "", List.of(), null,
                limit(source, 160), canonical, publication);
        // Leave previously reviewed or edited candidates intact when the feed repeats them.
        db.sql("""
                INSERT INTO career_content_draft (id, source_key, kind, payload) VALUES (?, ?, 'NOTE', ?)
                ON DUPLICATE KEY UPDATE id = id
                """).params(UUID.randomUUID().toString(), key, encode(item)).update();
    }

    private Draft changeStatus(Draft current, String status, String reviewer) {
        db.sql("""
                UPDATE career_content_draft SET status = ?, reviewed_by = ?, revision = revision + 1,
                    published_at = IF(? = 'PUBLISHED', CURRENT_TIMESTAMP(6), NULL) WHERE id = ?
                """).params(status, reviewer, status, current.id()).update();
        return find(current.id(), false);
    }

    private Draft edit(UUID id, int revision) {
        var current = find(id.toString(), true);
        requireRevision(current, revision);
        return current;
    }

    private static void requireRevision(Draft draft, int revision) {
        if (!"DRAFT".equals(draft.status()) || draft.revision() != revision) {
            throw new ResponseStatusException(CONFLICT, "此草稿已变化，请重新读取");
        }
    }

    private Draft find(String id, boolean lock) {
        return db.sql("""
                SELECT id, kind, status, payload, base_version, revision, updated_at
                FROM career_content_draft WHERE id = ?
                """ + (lock ? " FOR UPDATE" : "")).param(id).query(this::read).optional()
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "内容草稿不存在"));
    }

    private Draft read(java.sql.ResultSet row, int index) throws java.sql.SQLException {
        try {
            return new Draft(row.getString("id"), Kind.valueOf(row.getString("kind")), row.getString("status"),
                    json.readValue(row.getString("payload"), Content.class), row.getObject("base_version", Integer.class),
                    row.getInt("revision"), row.getTimestamp("updated_at"));
        } catch (JsonProcessingException error) {
            throw new java.sql.SQLException("Invalid public content draft", error);
        }
    }

    private int questionVersion(String id) {
        return db.sql("SELECT COALESCE(MAX(version), 0) FROM career_question_version WHERE id = ?")
                .param(id).query(Integer.class).single();
    }

    private static Content clean(Content item) {
        return new Content(item.targetId(), item.role().strip(), strip(item.topic()), item.title().strip(),
                item.explanation().strip(), strip(item.company()), item.options() == null ? List.of() :
                    item.options().stream().map(String::strip).toList(), item.correctAnswer(),
                item.sourceName().strip(), item.sourceUrl().strip(), item.publishedOn());
    }

    private static void validate(Kind kind, Content item) {
        if (webUrl(item.sourceUrl()) == null || item.role().isEmpty() || item.title().isEmpty()
                || item.explanation().isEmpty() || item.sourceName().isEmpty()) throw invalid("请补齐内容和原文来源");
        if (kind == Kind.NOTE) {
            if (item.targetId() != null || item.title().length() > 160 || item.company().isEmpty() || item.publishedOn() == null) {
                throw invalid("公开面经需要公司、原文发布日期和不超过 160 字的标题");
            }
        } else if (!List.of("backend", "algorithm", "llm").contains(item.role()) || item.topic().isEmpty()
                || item.options().size() != 4 || item.options().stream().anyMatch(String::isBlank)
                || item.options().stream().map(value -> value.toLowerCase(Locale.ROOT)).distinct().count() != 4
                || item.correctAnswer() == null || !item.correctAnswer().matches("[A-D]")) {
            throw invalid("单选题需要主题、四个不同的选项以及一个正确答案");
        }
    }

    static String webUrl(String url) {
        try {
            URI uri = URI.create(url).normalize();
            if (uri.getHost() == null || uri.getRawUserInfo() != null
                    || !("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme()))) return null;
            String value = uri.toASCIIString();
            int hash = value.indexOf('#');
            return hash < 0 ? value : value.substring(0, hash);
        } catch (IllegalArgumentException error) {
            return null;
        }
    }

    private String encode(Content content) {
        return json.valueToTree(content).toString();
    }

    private static String sourceKey(String value) {
        return UUID.nameUUIDFromBytes(value.getBytes(StandardCharsets.UTF_8)).toString();
    }

    private static String strip(String value) { return value == null ? "" : value.strip(); }
    private static String limit(String value, int size) { return value.substring(0, Math.min(value.length(), size)); }
    private static ResponseStatusException invalid(String message) { return new ResponseStatusException(BAD_REQUEST, message); }

    enum Kind { NOTE, QUESTION }
    record Draft(String id, Kind kind, String status, Content content, Integer baseVersion, int revision, Timestamp updatedAt) {}
    record Content(@Size(max = 64) String targetId, @NotBlank @Size(max = 24) String role, @Size(max = 80) String topic,
            @NotBlank @Size(max = 1000) String title, @NotBlank @Size(max = 6000) String explanation,
            @Size(max = 160) String company, @Size(max = 4) List<@NotNull @Size(max = 500) String> options,
            @Size(max = 1) String correctAnswer, @NotBlank @Size(max = 160) String sourceName,
            @NotBlank @Size(max = 2048) String sourceUrl, LocalDate publishedOn) {}
}

