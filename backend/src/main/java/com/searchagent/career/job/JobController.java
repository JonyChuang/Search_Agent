package com.searchagent.career.job;

import java.util.List;
import java.util.UUID;

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
@RequestMapping("/api/career/jobs")
class JobController {
    private final JobService service;

    JobController(JobService service) {
        this.service = service;
    }

    @GetMapping
    CareerResponse<List<JobService.Entry>> list(@CareerUser String userId) {
        return CareerResponse.ok(service.list(userId));
    }

    @GetMapping("/active")
    CareerResponse<ActiveJob> active(@CareerUser String userId) {
        var id = service.active(userId);
        return CareerResponse.ok(new ActiveJob(id == null ? null : UUID.fromString(id)));
    }

    @PutMapping("/active")
    CareerResponse<ActiveJob> selectActive(@CareerUser String userId, @RequestBody ActiveJob input) {
        service.selectActive(userId, input.jobId());
        return CareerResponse.ok(input);
    }

    @GetMapping("/{id}")
    CareerResponse<JobService.Entry> find(@CareerUser String userId, @PathVariable String id) {
        return CareerResponse.ok(service.find(userId, id));
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    CareerResponse<JobService.Entry> create(
            @CareerUser String userId, @Valid @RequestBody JobService.Input entry) {
        return CareerResponse.ok(service.create(userId, entry));
    }

    @PutMapping("/{id}")
    CareerResponse<JobService.Entry> update(
            @CareerUser String userId, @PathVariable String id, @Valid @RequestBody JobService.Input entry) {
        return CareerResponse.ok(service.update(userId, id, entry));
    }

    @DeleteMapping("/{id}")
    CareerResponse<Void> delete(@CareerUser String userId, @PathVariable String id) {
        service.delete(userId, id);
        return CareerResponse.ok(null);
    }

    record ActiveJob(UUID jobId) {}
}
