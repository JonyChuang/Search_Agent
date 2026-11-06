package com.searchagent.career.profile;

import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import org.springframework.stereotype.Service;

@Service
class ProfileService {
    static final String MONTH_PATTERN = "[0-9]{4}-(0[1-9]|1[0-2])";

    private final ProfileMapper mapper;

    ProfileService(ProfileMapper mapper) {
        this.mapper = mapper;
    }

    Profile find(String userId) {
        return mapper.find(userId);
    }

    Profile save(String userId, Profile profile) {
        mapper.save(userId, profile);
        return profile;
    }

    record Profile(
            @Size(max = 160, message = "求职目标最多 160 字") String targetRole,
            @Pattern(regexp = MONTH_PATTERN, message = "毕业月份须为 YYYY-MM") String graduationMonth,
            @Size(max = 2000, message = "求职偏好最多 2000 字") String preferences) {
    }
}
