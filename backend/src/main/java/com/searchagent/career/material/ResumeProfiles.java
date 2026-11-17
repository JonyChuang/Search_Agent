package com.searchagent.career.material;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.Base64;
import java.util.HashSet;
import java.util.List;
import java.util.UUID;

import javax.imageio.ImageIO;
import javax.imageio.stream.MemoryCacheImageInputStream;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import com.searchagent.career.profile.ExperienceService;

@Service
class ResumeProfiles {
    private static final String MONTH = "^(?:|[0-9]{4}-(?:0[1-9]|1[0-2]))$";
    private final JdbcClient db;
    private final ObjectMapper json;
    private final ExperienceService experiences;

    ResumeProfiles(JdbcClient db, ObjectMapper json, ExperienceService experiences) {
        this.db = db;
        this.json = json;
        this.experiences = experiences;
    }

    Profile get(String user) {
        return read(user, false);
    }

    @Transactional
    Profile save(String user, Input input) {
        Content content = input.content();
        validate(content);
        String value = json.valueToTree(content).toString();
        db.sql("""
                INSERT INTO career_resume_profile (user_id, revision, content_json) VALUES (?, 0, ?)
                ON DUPLICATE KEY UPDATE user_id = user_id
                """).params(user, json.valueToTree(Content.empty()).toString()).update();
        Profile current = read(user, true);
        if (current.revision() > 0 && content.equals(current.content())) {
            confirmExperience(user, content, input.confirmExperienceId());
            return current;
        }
        if (current.revision() != input.revision()) {
            throw new ResponseStatusException(CONFLICT, "简历资料已在其他页面更新，请重新打开后再编辑");
        }
        confirmExperience(user, content, input.confirmExperienceId());
        int revision = current.revision() + 1;
        db.sql("UPDATE career_resume_profile SET content_json = ?, revision = ? WHERE user_id = ?")
                .params(value, revision, user).update();
        return new Profile(revision, content);
    }

    private void confirmExperience(String user, Content content, UUID id) {
        if (id == null) return;
        Entry entry = content.entries().stream().filter(item -> id.equals(item.id())).findFirst()
                .orElseThrow(() -> new ResponseStatusException(BAD_REQUEST, "请先填写要确认的经历"));
        if (entry.kind() == Kind.award || entry.description().isBlank()) {
            throw new ResponseStatusException(BAD_REQUEST, "请为教育、项目、科研或实习经历填写实际内容");
        }
        String description = entry.role().isBlank() ? entry.description() : "担任角色：" + entry.role() + "\n" + entry.description();
        if (description.length() > 12000) {
            throw new ResponseStatusException(BAD_REQUEST, "经历描述与担任角色合计最多 12000 字");
        }
        experiences.confirmFromResume(user, id, new ExperienceService.Input(entry.kind().name(), entry.title(),
                emptyAsNull(entry.organization()), emptyAsNull(entry.startMonth()), emptyAsNull(entry.endMonth()),
                description, emptyAsNull(entry.sourceNote()), true));
    }

    private static String emptyAsNull(String value) {
        return value == null || value.isBlank() ? null : value;
    }

    private Profile read(String user, boolean lock) {
        return db.sql("SELECT revision, content_json FROM career_resume_profile WHERE user_id = ?"
                        + (lock ? " FOR UPDATE" : "")).param(user).query((rs, index) -> {
                    try {
                        return new Profile(rs.getInt("revision"),
                                json.readValue(rs.getString("content_json"), Content.class));
                    } catch (IOException error) {
                        throw new java.sql.SQLException("Invalid stored resume profile", error);
                    }
                }).optional().orElseGet(() -> new Profile(0, Content.empty()));
    }

    private static void validate(Content content) {
        var ids = new HashSet<UUID>();
        for (Entry entry : content.entries()) {
            if (!ids.add(entry.id())) {
                throw new ResponseStatusException(BAD_REQUEST, "简历经历不能重复");
            }
            if (!entry.startMonth().isEmpty() && !entry.endMonth().isEmpty()
                    && entry.endMonth().compareTo(entry.startMonth()) < 0) {
                throw new ResponseStatusException(BAD_REQUEST, "结束月份应晚于或等于起始月份");
            }
        }
        if (content.photo() != null) {
            validatePhoto(content.photo());
        }
    }

    private static void validatePhoto(String data) {
        int separator = data.indexOf(',');
        String mime = separator > 0 ? data.substring(0, separator) : "";
        String format = switch (mime) {
            case "data:image/jpeg;base64" -> "JPEG";
            case "data:image/png;base64" -> "PNG";
            default -> "";
        };
        if (!format.isEmpty()) {
            try {
                byte[] bytes = Base64.getDecoder().decode(data.substring(separator + 1));
                try (var input = new MemoryCacheImageInputStream(new ByteArrayInputStream(bytes))) {
                    var readers = ImageIO.getImageReaders(input);
                    if (readers.hasNext()) {
                        var reader = readers.next();
                        try {
                            reader.setInput(input, true, true);
                            if (format.equalsIgnoreCase(reader.getFormatName())
                                    && reader.getWidth(0) <= 1024 && reader.getHeight(0) <= 1024) {
                                reader.read(0);
                                return;
                            }
                        } finally {
                            reader.dispose();
                        }
                    }
                }
            } catch (IllegalArgumentException | IOException ignored) {
                // Return the same validation message for corrupt and unsupported photos.
            }
        }
        throw new ResponseStatusException(BAD_REQUEST, "简历照片无效，请重新选择 JPG 或 PNG");
    }

    enum Template { classic, tech, campus, modern, academic, mono }
    enum Kind { education, project, internship, research, award }

    record Input(@NotNull @PositiveOrZero Integer revision, @NotNull @Valid Content content, UUID confirmExperienceId) {}
    record Profile(int revision, Content content) {}
    record Content(@NotNull @Size(max = 80) String name, @NotNull @Size(max = 40) String phone,
            @NotNull @Email @Size(max = 160) String email, @NotNull @Size(max = 160) String targetRole,
            @NotNull @Size(max = 1000) String skills, @Size(max = 700000) String photo,
            @NotNull Boolean showPhoto, @NotNull Template template,
            @NotNull @Size(max = 40) List<@NotNull @Valid Entry> entries) {
        static Content empty() {
            return new Content("", "", "", "", "", null, true, Template.classic, List.of());
        }

        ObjectNode snapshot(ObjectMapper json) {
            ObjectNode snapshot = json.valueToTree(this);
            if (!showPhoto) {
                snapshot.putNull("photo");
            }
            return snapshot;
        }
    }
    record Entry(@NotNull UUID id, @NotNull Kind kind, @NotBlank @Size(max = 160) String title,
            @NotNull @Size(max = 160) String organization, @NotNull @Size(max = 160) String role,
            @NotNull @Pattern(regexp = MONTH) String startMonth, @NotNull @Pattern(regexp = MONTH) String endMonth,
            @NotNull @Size(max = 12000) String description, @Size(max = 500) String sourceNote) {}
}

