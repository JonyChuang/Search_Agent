package com.searchagent.career.job;

import java.net.URI;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class JobService {
    private final JobMapper mapper;

    JobService(JobMapper mapper) {
        this.mapper = mapper;
    }

    List<Entry> list(String userId) {
        return mapper.list(userId);
    }

    public Entry find(String userId, String id) {
        Entry entry = mapper.find(userId, id);
        if (entry == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "岗位不存在");
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
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "岗位不存在");
        }
    }

    private void validate(Input entry) {
        if (entry.sourceUrl() == null) {
            return;
        }

        URI url;
        try {
            url = URI.create(entry.sourceUrl());
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请输入有效的招聘来源链接");
        }
        if (url.getHost() == null || url.getRawUserInfo() != null
                || !("http".equalsIgnoreCase(url.getScheme()) || "https".equalsIgnoreCase(url.getScheme()))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "来源链接须为 HTTP 或 HTTPS 地址");
        }
    }

    record Input(
            @NotBlank(message = "请输入公司名称") @Size(max = 160, message = "公司名称最多 160 字") String company,
            @NotBlank(message = "请输入岗位名称") @Size(max = 160, message = "岗位名称最多 160 字") String title,
            @Size(max = 160, message = "工作地点最多 160 字") String location,
            @NotBlank(message = "请输入岗位描述") @Size(max = 40000, message = "岗位描述最多 40000 字") String description,
            @NotBlank(message = "请填写招聘来源") @Size(max = 160, message = "招聘来源最多 160 字") String sourceName,
            @Size(max = 2048, message = "来源链接最多 2048 字符") String sourceUrl,
            @NotNull(message = "请填写来源记录日期") LocalDate sourcedOn) {
    }

    public record Entry(
            String id, String company, String title, String location,
            String description, String sourceName, String sourceUrl, LocalDate sourcedOn) {
    }
}
