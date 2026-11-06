package com.searchagent.career.profile;

import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import jakarta.validation.Valid;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/career/profile")
class ProfileController {
    private final ProfileService service;

    ProfileController(ProfileService service) {
        this.service = service;
    }

    @GetMapping
    CareerResponse<ProfileService.Profile> find(@CareerUser String userId) {
        return CareerResponse.ok(service.find(userId));
    }

    @PutMapping
    CareerResponse<ProfileService.Profile> save(
            @CareerUser String userId, @Valid @RequestBody ProfileService.Profile profile) {
        return CareerResponse.ok(service.save(userId, profile));
    }
}
