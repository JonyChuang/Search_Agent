package com.searchagent.career.profile;

import java.util.List;
import java.util.UUID;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ExperienceService {
    private final ExperienceMapper mapper;

    ExperienceService(ExperienceMapper mapper) {
        this.mapper = mapper;
    }

    public List<Entry> list(String userId) {
        return mapper.list(userId);
    }

    public Entry find(String userId, String id) {
        Entry entry = mapper.find(userId, id);
        if (entry == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "经历不存在");
        }
        return entry;
    }

    @Transactional
    Entry create(String userId, Input entry) {
        validate(entry);
        String id = UUID.randomUUID().toString();
        mapper.insert(userId, id, entry);
        return find(userId, id);
    }

    @Transactional
    Entry update(String userId, String id, Input entry) {
        validate(entry);
        mapper.update(userId, id, entry);
        return find(userId, id);
    }

    void delete(String userId, String id) {
        if (mapper.delete(userId, id) == 0) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "经历不存在");
        }
    }

    private void validate(Input entry) {
        if (entry.startMonth() != null && entry.endMonth() != null
                && entry.endMonth().compareTo(entry.startMonth()) < 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "结束月份应晚于或等于起始月份");
        }
    }

    record Input(
            @Pattern(regexp = "education|research|project|internship", message = "请选择有效的经历类型")
            @NotBlank(message = "请选择经历类型") String type,
            @NotBlank(message = "请输入经历名称") @Size(max = 160, message = "经历名称最多 160 字") String title,
            @Size(max = 160, message = "组织名称最多 160 字") String organization,
            @Pattern(regexp = ProfileService.MONTH_PATTERN, message = "起始月份须为 YYYY-MM") String startMonth,
            @Pattern(regexp = ProfileService.MONTH_PATTERN, message = "结束月份须为 YYYY-MM") String endMonth,
            @NotBlank(message = "请填写经历内容") @Size(max = 12000, message = "经历内容最多 12000 字") String description,
            @Size(max = 500, message = "事实依据最多 500 字") String sourceNote,
            boolean confirmed) {
    }

    public record Entry(
            String id, String type, String title, String organization,
            String startMonth, String endMonth, String description, String sourceNote, boolean confirmed) {
    }
}
