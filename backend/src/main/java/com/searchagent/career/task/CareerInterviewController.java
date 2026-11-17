package com.searchagent.career.task;

import java.util.UUID;

import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.searchagent.career.task.CareerInterviewSessions.Answer;
import com.searchagent.career.task.CareerInterviewSessions.Decision;
import com.searchagent.career.task.CareerInterviewSessions.Page;
import com.searchagent.career.task.CareerInterviewSessions.Start;
import com.searchagent.career.task.CareerInterviewSessions.StatusChange;
import com.searchagent.career.task.CareerInterviewSessions.View;
import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;

@RestController
@RequestMapping("/api/career/interviews")
class CareerInterviewController {
    private final CareerInterviewSessions interviews;

    CareerInterviewController(CareerInterviewSessions interviews) {
        this.interviews = interviews;
    }

    @GetMapping
    CareerResponse<Page> list(@CareerUser String user, @RequestParam(defaultValue = "1") int page) {
        return CareerResponse.ok(interviews.list(user, page));
    }

    @PostMapping
    CareerResponse<View> start(@CareerUser String user, @Valid @RequestBody Start input) {
        return CareerResponse.ok(interviews.start(user, input));
    }

    @GetMapping("/{id}")
    CareerResponse<View> get(@CareerUser String user, @PathVariable UUID id) {
        return CareerResponse.ok(interviews.get(user, id));
    }

    @PostMapping("/{id}/answer")
    CareerResponse<View> answer(@CareerUser String user, @PathVariable UUID id, @Valid @RequestBody Answer input) {
        return CareerResponse.ok(interviews.answer(user, id, input));
    }

    @PostMapping("/{id}/advance")
    CareerResponse<View> advance(@CareerUser String user, @PathVariable UUID id, @Valid @RequestBody Decision input) {
        return CareerResponse.ok(interviews.advance(user, id, input));
    }

    @PostMapping("/{id}/retry")
    CareerResponse<View> retry(@CareerUser String user, @PathVariable UUID id, @Valid @RequestBody Decision input) {
        return CareerResponse.ok(interviews.retry(user, id, input));
    }

    @PostMapping("/{id}/status")
    CareerResponse<View> status(@CareerUser String user, @PathVariable UUID id, @Valid @RequestBody StatusChange input) {
        return CareerResponse.ok(interviews.status(user, id, input));
    }
}