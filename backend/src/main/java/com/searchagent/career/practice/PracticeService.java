package com.searchagent.career.practice;

import java.time.Instant;
import java.time.LocalDate;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.UUID;

import com.searchagent.career.job.JobService;

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
    private final JobService jobs;

    PracticeService(PracticeMapper mapper, JobService jobs) {
        this.mapper = mapper;
        this.jobs = jobs;
    }

    List<InterviewNote> notes() {
        return mapper.notes();
    }

    public List<Question> questions(String role) {
        return mapper.questions(role).stream().map(QuestionRow::view).toList();
    }

    public Recommendations recommendations(JobService.Entry job) {
        return recommendations(job.company(), job.title(), job.description(), job.skills() == null ? "" : job.skills());
    }

    public Recommendations recommendations(String company, String title, String description, String skills) {
        String text = (title + " " + description + " " + skills).toLowerCase(Locale.ROOT);
        var notes = notes().stream().filter(note -> note.company().equalsIgnoreCase(company)
                || text.contains(note.role().toLowerCase(Locale.ROOT))).limit(12).toList();
        var questions = questions(null).stream().filter(question -> {
            String topic = question.topic().toLowerCase(Locale.ROOT);
            return text.contains(topic) || Arrays.stream(topic.split("[\\s、/]+"))
                    .anyMatch(word -> word.length() > 1 && text.contains(word));
        }).limit(30).toList();
        return new Recommendations(notes, questions);
    }

    public record Recommendations(List<InterviewNote> notes, List<Question> questions) {}

    Question question(String id, Integer version) {
        var question = mapper.question(id, version);
        if (question == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "题目不存在");
        }
        return question.view();
    }

    public List<Attempt> feedback(String userId, List<QuestionVersion> questions, String jobId, boolean includeUnscoped) {
        return mapper.feedback(userId, questions, jobId, includeUnscoped);
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
        String jobId = submission.jobId() == null ? null : submission.jobId().toString();
        if (jobId != null && mapper.attempt(userId, requestId) == null) jobs.find(userId, jobId);
        var rule = mapper.gradingRule(submission.questionId(), submission.questionVersion());
        if (rule == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "题目版本不存在");
        }
        mapper.saveAttempt(userId, requestId, jobId, submission, rule.gradingVersion(),
                rule.correctAnswer().equals(submission.answer()));

        var attempt = mapper.attempt(userId, requestId);
        if (!attempt.questionId().equals(submission.questionId())
                || attempt.questionVersion() != submission.questionVersion()
                || !Objects.equals(attempt.jobId(), jobId)
                || !attempt.answer().equals(submission.answer())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "提交编号已用于另一条作答");
        }
        return attempt;
    }

    AttemptPage attempts(String userId, int page, UUID jobId) {
        if (page < 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "页码须为正整数");
        }
        var attempts = mapper.attempts(userId, jobId == null ? null : jobId.toString(), PAGE_SIZE + 1, (page - 1L) * PAGE_SIZE);
        return new AttemptPage(attempts.stream().limit(PAGE_SIZE).toList(), attempts.size() > PAGE_SIZE);
    }

    List<WrongQuestion> wrongQuestions(String userId, UUID jobId) {
        return mapper.wrongQuestions(userId, jobId == null ? null : jobId.toString());
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
            @NotNull @Pattern(regexp = "[A-D]", message = "请选择一个有效选项") String answer,
            UUID jobId) {
    }

    public record Attempt(String requestId, String questionId, int questionVersion, int gradingVersion,
            String prompt, String answer, boolean correct, String correctAnswer, String answerText,
            String correctAnswerText, String explanation, Instant submittedAt, String jobId) {
    }

    record AttemptPage(List<Attempt> items, boolean hasMore) {
    }

    record WrongQuestion(String questionId, String prompt, String topic, long wrongCount, boolean reviewed) {
    }
}
