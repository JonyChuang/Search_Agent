package com.searchagent.career.material;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

@Service
class ApplicationWorkspace {
    private static final int MAX_FILES = 6;
    private static final long MAX_BYTES = 10 * 1024 * 1024;
    private static final byte[] PDF = "%PDF-".getBytes(StandardCharsets.US_ASCII);
    private static final byte[] JPEG = {(byte) 255, (byte) 216, (byte) 255};
    private static final byte[] PNG = {(byte) 137, 80, 78, 71, 13, 10, 26, 10};

    private final JdbcClient db;
    private final ObjectMapper json;

    ApplicationWorkspace(JdbcClient db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    Draft load(String applicationId) {
        return db.sql("SELECT workspace_json FROM career_application WHERE id = ?")
                .param(applicationId).query((row, index) -> parse(row.getString(1))).single();
    }

    View view(String applicationId, Draft content) {
        var ids = fileIds(content);
        if (ids.isEmpty()) return new View(content, List.of());
        var files = db.sql("""
                SELECT id, file_name, file_size FROM career_application_file
                WHERE application_id = :application AND id IN (:ids)
                """).param("application", applicationId).param("ids", ids)
                .query((row, index) -> new FileInfo(row.getString(1), row.getString(2), row.getInt(3))).list();
        return new View(content, files);
    }

    void saveFiles(String applicationId, Draft content, Map<String, List<MultipartFile>> uploads) {
        var itemIds = new HashSet<UUID>();
        var attachments = fileIds(content);
        if (attachments.size() > MAX_FILES || new HashSet<>(attachments).size() != attachments.size()) {
            throw invalid("每份草稿最多保存 6 个文件，附件不能重复");
        }
        for (var item : content.attachments()) {
            if (!itemIds.add(item.id())) throw invalid("附件项目不能重复");
            boolean hasUrl = item.url() != null && !item.url().isBlank();
            if (item.kind() == Kind.FILE && hasUrl || item.kind() == Kind.LINK && item.fileId() != null) {
                throw invalid("附件类型与内容不一致");
            }
            if (hasUrl) validateUrl(item.url());
        }
        var questionIds = new HashSet<UUID>();
        for (var question : content.form().questions()) {
            if (!questionIds.add(question.id())) throw invalid("岗位问题不能重复");
        }

        for (var upload : uploads.entrySet()) {
            if (upload.getValue().size() != 1 || !attachments.contains(upload.getKey())) {
                throw invalid("上传文件与草稿中的附件不匹配");
            }
            saveFile(applicationId, upload.getKey(), upload.getValue().getFirst());
        }
        if (view(applicationId, content).files().size() != attachments.size()) {
            throw invalid("找不到所选文件，请重新添加附件");
        }
    }

    void prune(String applicationId, Draft content) {
        var ids = fileIds(content);
        String sql = "DELETE FROM career_application_file WHERE application_id = :application AND retained = FALSE";
        if (ids.isEmpty()) {
            db.sql(sql).param("application", applicationId).update();
        } else {
            db.sql(sql + " AND id NOT IN (:ids)").param("application", applicationId).param("ids", ids).update();
        }
    }

    void retain(String applicationId, View view) {
        if (!view.files().isEmpty()) {
            db.sql("UPDATE career_application_file SET retained = TRUE WHERE application_id = :application AND id IN (:ids)")
                    .param("application", applicationId).param("ids", view.files().stream().map(FileInfo::id).toList()).update();
        }
    }

    Download download(String applicationId, UUID fileId) {
        return storedFile(applicationId, fileId.toString())
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "附件不存在"));
    }

    private java.util.Optional<Download> storedFile(String applicationId, String fileId) {
        return db.sql("""
                SELECT file_name, content FROM career_application_file
                WHERE application_id = ? AND id = ?
                """).params(applicationId, fileId)
                .query((row, index) -> new Download(row.getString(1), row.getBytes(2)))
                .optional();
    }

    private void saveFile(String applicationId, String id, MultipartFile file) {
        var name = fileName(file.getOriginalFilename());
        if (file.isEmpty() || file.getSize() > MAX_BYTES) throw invalid("请添加不超过 10 MB 的有效文件");
        byte[] content;
        try {
            content = file.getBytes();
        } catch (IOException error) {
            throw invalid("无法读取附件，请重新选择文件");
        }
        byte[] signature = switch (name.substring(name.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT)) {
            case "pdf" -> PDF;
            case "jpg", "jpeg" -> JPEG;
            case "png" -> PNG;
            default -> throw invalid("附件支持 PDF、JPG 和 PNG");
        };
        if (content.length < signature.length || !Arrays.equals(signature, Arrays.copyOf(content, signature.length))) {
            throw invalid("附件内容与文件格式不匹配");
        }
        var existing = storedFile(applicationId, id);
        if (existing.isPresent()) {
            var saved = existing.get();
            if (!saved.name().equals(name) || !Arrays.equals(saved.content(), content)) {
                throw new ResponseStatusException(CONFLICT, "文件编号已使用，请重新添加附件");
            }
            return;
        }
        db.sql("""
                INSERT INTO career_application_file (application_id, id, file_name, file_size, content)
                VALUES (?, ?, ?, ?, ?)
                """).params(applicationId, id, name, content.length, content).update();
    }

    private static String fileName(String original) {
        if (original == null) throw invalid("附件缺少文件名");
        String safe = original.replace('\\', '/');
        safe = safe.substring(safe.lastIndexOf('/') + 1).strip();
        if (safe.isBlank() || safe.length() > 255 || safe.codePoints().anyMatch(Character::isISOControl)) {
            throw invalid("附件文件名无效");
        }
        return safe;
    }

    private static void validateUrl(String value) {
        try {
            URI url = URI.create(value.strip());
            if (url.getHost() != null && url.getRawUserInfo() == null
                    && ("http".equalsIgnoreCase(url.getScheme()) || "https".equalsIgnoreCase(url.getScheme()))) return;
        } catch (IllegalArgumentException ignored) {
            // Report the same validation error for malformed and unsupported links.
        }
        throw invalid("附件链接须为 HTTP 或 HTTPS 地址");
    }

    private static List<String> fileIds(Draft content) {
        return content.attachments().stream().map(Attachment::fileId).filter(java.util.Objects::nonNull)
                .map(UUID::toString).toList();
    }

    private Draft parse(String value) throws java.sql.SQLException {
        if (value == null) return Draft.empty();
        try {
            return json.readValue(value, Draft.class);
        } catch (JsonProcessingException error) {
            throw new java.sql.SQLException("Invalid stored application workspace", error);
        }
    }

    private static ResponseStatusException invalid(String message) {
        return new ResponseStatusException(BAD_REQUEST, message);
    }

    enum Kind { FILE, LINK }

    record Attachment(@NotNull UUID id, @NotNull Kind kind, @NotBlank @Size(max = 100) String label,
            boolean required, UUID fileId, @Size(max = 2048) String url) {}
    record Question(@NotNull UUID id, @NotBlank @Size(max = 160) String label, boolean required,
            @Size(max = 2500) String answer) {}
    record FormAnswers(@Size(max = 80) String name, @Size(max = 40) String phone,
            @Email @Size(max = 160) String email, @Size(max = 2000) String education, LocalDate startDate,
            @Min(1) @Max(7) Integer weeklyDays, @Size(max = 80) String duration, @Size(max = 2500) String motivation,
            @NotNull @Size(max = 12) List<@NotNull @Valid Question> questions) {}
    record Draft(@NotNull @Valid FormAnswers form, @NotNull @Size(max = 12) List<@NotNull @Valid Attachment> attachments) {
        static Draft empty() {
            return new Draft(new FormAnswers(null, null, null, null, null, null, null, null, List.of()), List.of());
        }
    }
    record FileInfo(String id, String name, int size) {}
    record View(Draft content, List<FileInfo> files) {}
    record Download(String name, byte[] content) {}
}
