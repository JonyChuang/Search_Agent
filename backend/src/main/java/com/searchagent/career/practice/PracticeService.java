package com.searchagent.career.practice;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class PracticeService {
    private static final int PAGE_SIZE = 20;
    private final PracticeMapper mapper;

    PracticeService(PracticeMapper mapper) {
        this.mapper = mapper;
    }

    List<InterviewNote> notes() {
        return mapper.notes();
    }

    public List<Question> questions(String role) {
        return mapper.questions(role).stream().map(QuestionRow::view).toList();
    }

    Question question(String id, Integer version) {
        var question = mapper.question(id, version);
        if (question == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "题目不存在");
        }
        return question.view();
    }

    public List<Attempt> feedback(String userId, List<QuestionVersion> questions) {
        return mapper.feedback(userId, questions);
    }

    public InterviewQuestion interviewQuestion(String id, int version) {
        var question = mapper.interviewQuestion(id, version);
        if (question == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "题目版本不存在");
        }
        return question;
    }

    public record QuestionVersion(String id, int version) {}

    public record InterviewQuestion(String id, int version, int gradingVersion, String role,
            String prompt, String referenceAnswer, String explanation, String sourceUrl) {
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    Attempt submit(String userId, Submission submission) {
        String requestId = submission.requestId().toString();
        var rule = mapper.gradingRule(submission.questionId(), submission.questionVersion());
        if (rule == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "题目版本不存在");
        }
        mapper.saveAttempt(userId, requestId, submission, rule.gradingVersion(),
                rule.correctAnswer().equals(submission.answer()));

        var attempt = mapper.attempt(userId, requestId);
        if (!attempt.questionId().equals(submission.questionId())
                || attempt.questionVersion() != submission.questionVersion()
                || !attempt.answer().equals(submission.answer())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "提交编号已用于另一条作答");
        }
        return attempt;
    }

    AttemptPage attempts(String userId, int page) {
        if (page < 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "页码须为正整数");
        }
        var attempts = mapper.attempts(userId, PAGE_SIZE + 1, (page - 1L) * PAGE_SIZE);
        return new AttemptPage(attempts.stream().limit(PAGE_SIZE).toList(), attempts.size() > PAGE_SIZE);
    }

    List<WrongQuestion> wrongQuestions(String userId) {
        return mapper.wrongQuestions(userId);
    }

    record InterviewNote(String id, String role, String company, String title, String summary,
            String sourceName, String sourceUrl, LocalDate publishedOn, LocalDate sourcedOn) {
    }

    record QuestionRow(String id, int version, String role, String topic, String prompt,
            String optionA, String optionB, String optionC, String optionD,
            String sourceName, String sourceUrl, LocalDate sourcedOn) {
        Question view() {
            return new Question(id, version, role, topic, prompt, List.of(optionA, optionB, optionC, optionD),
                    sourceName, sourceUrl, sourcedOn);
        }
    }

    public record Question(String id, int version, String role, String topic, String prompt,
            List<String> options, String sourceName, String sourceUrl, LocalDate sourcedOn) {
    }

    record GradingRule(int gradingVersion, String correctAnswer) {
    }

    record Submission(
            @NotNull(message = "缺少提交编号") UUID requestId,
            @NotNull @Pattern(regexp = "[a-z0-9-]{1,64}", message = "题目编号无效") String questionId,
            @NotNull @Positive(message = "题目版本无效") Integer questionVersion,
            @NotNull @Pattern(regexp = "[A-D]", message = "请选择一个有效选项") String answer) {
    }

    public record Attempt(String requestId, String questionId, int questionVersion, int gradingVersion,
            String prompt, String answer, boolean correct, String correctAnswer, String answerText,
            String correctAnswerText, String explanation, Instant submittedAt) {
    }

    record AttemptPage(List<Attempt> items, boolean hasMore) {
    }

    record WrongQuestion(String questionId, String prompt, String topic, long wrongCount, boolean reviewed) {
    }
}
