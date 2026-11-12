package com.searchagent.career.task;

import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.UNAUTHORIZED;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;

@RestController
@RequestMapping("/api/career/tasks")
class CareerTaskController {
    private final CareerTasks tasks;

    CareerTaskController(CareerTasks tasks) {
        this.tasks = tasks;
    }

    @PostMapping("/training")
    CareerResponse<CareerTasks.Task> training(@CareerUser String user, @Valid @RequestBody CareerTasks.Training input) {
        return CareerResponse.ok(tasks.training(user, input));
    }

    @PostMapping("/preparation")
    CareerResponse<CareerTasks.Task> prepare(@CareerUser String user, @Valid @RequestBody CareerTasks.JobRequest input) {
        return CareerResponse.ok(tasks.prepare(user, input));
    }

    @PostMapping("/discovery")
    CareerResponse<CareerTasks.Task> discover(@CareerUser String user, @Valid @RequestBody CareerTasks.JobRequest input) {
        return CareerResponse.ok(tasks.discover(user, input));
    }

    @PostMapping("/review")
    CareerResponse<CareerTasks.Task> review(@CareerUser String user, @Valid @RequestBody CareerTasks.Review input) {
        return CareerResponse.ok(tasks.review(user, input));
    }

    @PostMapping("/interview")
    CareerResponse<CareerTasks.Task> interview(@CareerUser String user, @Valid @RequestBody CareerTasks.Interview input) {
        return CareerResponse.ok(tasks.interview(user, input));
    }

    @GetMapping
    CareerResponse<CareerTasks.TaskPage> list(@CareerUser String user, @RequestParam String kind,
            @RequestParam(required = false) UUID jobId,
            @RequestParam(defaultValue = "1") int page) {
        return CareerResponse.ok(tasks.list(user, kind, jobId, page));
    }

    @GetMapping("/{id}")
    CareerResponse<CareerTasks.Task> get(@CareerUser String user, @PathVariable UUID id) {
        return CareerResponse.ok(tasks.get(user, id));
    }

    @PostMapping("/{id}/retry")
    CareerResponse<CareerTasks.Task> retry(@CareerUser String user, @PathVariable UUID id) {
        return CareerResponse.ok(tasks.retry(user, id));
    }
}

@RestController
@RequestMapping("/internal/career/tasks/{id}")
class CareerTaskTools {
    private final CareerTaskStore store;
    private final CareerTasks tasks;
    private final byte[] secret;

    CareerTaskTools(CareerTaskStore store, CareerTasks tasks, @Value("${career.agent.internal-token}") String token) {
        this.store = store;
        this.tasks = tasks;
        this.secret = token.isBlank() ? new byte[0] : token.getBytes(StandardCharsets.UTF_8);
    }

    @PutMapping("/questions")
    JsonNode questions(@PathVariable UUID id, @RequestHeader("X-Career-Service") String token,
            @RequestHeader("X-Career-Lease") UUID lease) {
        return tasks.checkpointQuestions(requireTraining(id, token, lease));
    }

    @PutMapping("/plan")
    void plan(@PathVariable UUID id, @RequestHeader("X-Career-Service") String token,
            @RequestHeader("X-Career-Lease") UUID lease, @Valid @RequestBody CareerTasks.Plan input) {
        tasks.checkpointPlan(requireTraining(id, token, lease), input);
    }

    private CareerTaskStore.Row requireTraining(UUID id, String token, UUID lease) {
        if (secret.length == 0 || !MessageDigest.isEqual(secret, token.getBytes(StandardCharsets.UTF_8))) {
            throw new ResponseStatusException(UNAUTHORIZED, "内部服务认证失败");
        }
        return store.active(id, lease).filter(row -> "TRAINING".equals(row.kind()))
                .orElseThrow(() -> new ResponseStatusException(CONFLICT, "训练任务执行代次已失效"));
    }
}
