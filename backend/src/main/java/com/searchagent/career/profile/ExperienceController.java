package com.searchagent.career.profile;

import java.util.List;

import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import jakarta.validation.Valid;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/career/experiences")
class ExperienceController {
    private final ExperienceService service;

    ExperienceController(ExperienceService service) {
        this.service = service;
    }

    @GetMapping
    CareerResponse<List<ExperienceService.Entry>> list(@CareerUser String userId) {
        return CareerResponse.ok(service.list(userId));
    }

    @GetMapping("/{id}")
    CareerResponse<ExperienceService.Entry> find(@CareerUser String userId, @PathVariable String id) {
        return CareerResponse.ok(service.find(userId, id));
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    CareerResponse<ExperienceService.Entry> create(
            @CareerUser String userId, @Valid @RequestBody ExperienceService.Input entry) {
        return CareerResponse.ok(service.create(userId, entry));
    }

    @PutMapping("/{id}")
    CareerResponse<ExperienceService.Entry> update(
            @CareerUser String userId, @PathVariable String id, @Valid @RequestBody ExperienceService.Input entry) {
        return CareerResponse.ok(service.update(userId, id, entry));
    }

    @DeleteMapping("/{id}")
    CareerResponse<Void> delete(@CareerUser String userId, @PathVariable String id) {
        service.delete(userId, id);
        return CareerResponse.ok(null);
    }
}
