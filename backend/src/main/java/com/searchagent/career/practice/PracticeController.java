package com.searchagent.career.practice;

import java.util.List;

import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import jakarta.validation.Valid;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/career")
class PracticeController {
    private final PracticeService service;

    PracticeController(PracticeService service) {
        this.service = service;
    }

    @GetMapping("/interview-notes")
    CareerResponse<List<PracticeService.InterviewNote>> notes() {
        return CareerResponse.ok(service.notes());
    }

    @GetMapping("/questions")
    CareerResponse<List<PracticeService.Question>> questions(@RequestParam(required = false) String role) {
        return CareerResponse.ok(service.questions(role));
    }

    @GetMapping("/questions/{id}")
    CareerResponse<PracticeService.Question> question(@PathVariable String id, @RequestParam(required = false) Integer version) {
        return CareerResponse.ok(service.question(id, version));
    }

    @PostMapping("/practice/attempts")
    CareerResponse<PracticeService.Attempt> submit(
            @CareerUser String userId, @Valid @RequestBody PracticeService.Submission submission) {
        return CareerResponse.ok(service.submit(userId, submission));
    }

    @GetMapping("/practice/attempts")
    CareerResponse<PracticeService.AttemptPage> attempts(
            @CareerUser String userId, @RequestParam(defaultValue = "1") int page) {
        return CareerResponse.ok(service.attempts(userId, page));
    }

    @GetMapping("/practice/wrong-questions")
    CareerResponse<List<PracticeService.WrongQuestion>> wrongQuestions(@CareerUser String userId) {
        return CareerResponse.ok(service.wrongQuestions(userId));
    }
}
