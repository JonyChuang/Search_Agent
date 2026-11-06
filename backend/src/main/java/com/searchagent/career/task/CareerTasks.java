package com.searchagent.career.task;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;
import java.util.stream.StreamSupport;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.searchagent.career.job.JobService;
import com.searchagent.career.practice.PracticeService;
import com.searchagent.career.profile.ExperienceService;

@Service
class CareerTasks {
    private final CareerTaskStore store;
    private final JobService jobs;
    private final ExperienceService experiences;
    private final PracticeService practice;
    private final ObjectMapper json;

    CareerTasks(CareerTaskStore store, JobService jobs, ExperienceService experiences,
            PracticeService practice, ObjectMapper json) {
        this.store = store;
        this.jobs = jobs;
        this.experiences = experiences;
        this.practice = practice;
        this.json = json;
    }

    Task training(String user, Training input) {
        return enqueue(user, input.requestId(), "TRAINING", input, () -> {
            var job = jobs.find(user, input.jobId().toString());
            var facts = experiences.list(user).stream().filter(ExperienceService.Entry::confirmed)
                    .limit(10).map(fact -> Map.of("id", fact.id(), "title", fact.title(),
                            "description", excerpt(fact.description(), 1800))).toList();
            if (facts.isEmpty()) {
                throw new ResponseStatusException(BAD_REQUEST, "请先确认至少一条真实经历");
            }
            return Map.of("job", jobContext(job), "role", input.role(), "experiences", facts);
        });
    }

    Task review(String user, Review input) {
        return enqueue(user, input.requestId(), "REVIEW", input, () -> {
            var plan = owned(user, input.planId());
            if (!"TRAINING".equals(plan.kind()) || !"SUCCEEDED".equals(plan.status())) {
                throw new ResponseStatusException(CONFLICT, "请选择已完成的训练计划");
            }
            var questions = StreamSupport.stream(plan.result().path("questions").spliterator(), false)
                    .map(q -> new PracticeService.QuestionVersion(q.path("id").asText(), q.path("version").asInt())).toList();
            var feedback = practice.feedback(user, questions);
            if (feedback.isEmpty()) {
                throw new ResponseStatusException(CONFLICT, "请先完成计划中的至少一道练习");
            }
            return Map.of("job", plan.context().path("job"), "plan", plan.result(), "feedback", feedback);
        });
    }

    Task interview(String user, Interview input) {
        return enqueue(user, input.requestId(), "INTERVIEW", input, () -> {
            var job = jobs.find(user, input.jobId().toString());
            var question = practice.interviewQuestion(input.questionId(), input.questionVersion());
            return Map.of("job", jobContext(job), "question", question, "answer", input.answer().strip());
        });
    }

    Task get(String user, UUID id) {
        return view(owned(user, id));
    }

    Task retry(String user, UUID id) {
        var task = owned(user, id);
        if ("FAILED".equals(task.status())) {
            store.retry(user, id);
        }
        return get(user, id);
    }

    TaskPage list(String user, String kind, int page) {
        if (!List.of("TRAINING", "REVIEW", "INTERVIEW").contains(kind) || page < 1) {
            throw new ResponseStatusException(BAD_REQUEST, "任务类型或页码无效");
        }
        var rows = store.list(user, kind, (page - 1L) * 20);
        return new TaskPage(rows.stream().limit(20).map(this::view).toList(), rows.size() > 20);
    }

    List<PracticeService.Question> questions(CareerTaskStore.Row row) {
        return practice.questions(row.context().path("role").asText()).stream().limit(30).toList();
    }

    void savePlan(CareerTaskStore.Row row, Plan input) {
        var catalog = questions(row);
        var ids = new HashSet<String>();
        var selected = input.questions().stream().map(ref -> {
            if (!ids.add(ref.id())) {
                throw new ResponseStatusException(BAD_REQUEST, "训练题目不能重复");
            }
            return catalog.stream().filter(q -> q.id().equals(ref.id()) && q.version() == ref.version())
                    .findFirst().orElseThrow(() -> new ResponseStatusException(BAD_REQUEST, "训练题目或版本无效"));
        }).toList();
        var result = json.valueToTree(Map.of("analysis", input.analysis(), "steps", input.steps(),
                "questions", selected));
        if (!store.finish(row, result, null)) {
            throw new ResponseStatusException(CONFLICT, "任务执行已结束或代次已失效");
        }
    }

    private Task enqueue(String user, UUID key, String kind, Object input, Supplier<Object> context) {
        JsonNode request = json.valueToTree(input);
        var row = store.byRequest(user, key).orElseGet(() ->
                store.insert(user, key, kind, request, json.valueToTree(context.get())));
        if (!row.kind().equals(kind) || !row.request().equals(request)) {
            throw new ResponseStatusException(CONFLICT, "请求编号已用于另一项任务");
        }
        return view(row);
    }

    private CareerTaskStore.Row owned(String user, UUID id) {
        return store.owned(user, id).orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "任务不存在"));
    }

    private Task view(CareerTaskStore.Row row) {
        var question = row.context().path("question");
        JsonNode interview = null;
        if ("INTERVIEW".equals(row.kind())) {
            interview = json.createObjectNode().put("prompt", question.path("prompt").asText())
                    .put("gradingVersion", question.path("gradingVersion").asInt())
                    .put("sourceUrl", question.path("sourceUrl").asText())
                    .put("answer", row.context().path("answer").asText());
        }
        var job = row.context().path("job");
        return new Task(row.id(), row.kind(), row.status(), row.request(), job.path("label").asText(), interview,
                row.result(), row.error(), row.generation(), row.createdAt(), row.updatedAt());
    }

    private static Map<String, String> jobContext(JobService.Entry job) {
        return Map.of("label", job.company() + " · " + job.title(), "jd", excerpt(job.description(), 8000));
    }

    private static String excerpt(String value, int limit) {
        return value.codePoints().limit(limit).collect(StringBuilder::new, StringBuilder::appendCodePoint,
                StringBuilder::append).toString();
    }

    record Training(@NotNull UUID requestId, @NotNull UUID jobId,
            @NotNull @Pattern(regexp = "backend|algorithm|llm") String role) {}
    record Review(@NotNull UUID requestId, @NotNull UUID planId) {}
    record Interview(@NotNull UUID requestId, @NotNull UUID jobId,
            @NotNull @Pattern(regexp = "[a-z0-9-]{1,64}") String questionId, @NotNull @Positive Integer questionVersion,
            @NotBlank @Size(max = 6000) String answer) {}
    record Plan(@NotBlank @Size(max = 4000) String analysis,
            @NotNull @Size(min = 1, max = 8) List<@NotBlank @Size(max = 600) String> steps,
            @NotNull @Size(min = 1, max = 8) List<@NotNull @Valid QuestionRef> questions) {}
    record QuestionRef(@NotNull @Pattern(regexp = "[a-z0-9-]{1,64}") String id,
            @NotNull @Positive Integer version) {}
    record Task(String id, String kind, String status, JsonNode request, String job, JsonNode interview,
            JsonNode result, String error, int generation, Instant createdAt, Instant updatedAt) {}
    record TaskPage(List<Task> items, boolean hasMore) {}
}
