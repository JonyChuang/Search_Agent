package com.searchagent.career.task;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;
import java.util.stream.StreamSupport;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.searchagent.career.job.JobService;
import com.searchagent.career.job.JobMemory;
import com.searchagent.career.practice.PracticeService;
import com.searchagent.career.profile.ExperienceService;

@Service
class CareerTasks {
    private final CareerTaskStore store;
    private final JobService jobs;
    private final ExperienceService experiences;
    private final PracticeService practice;
    private final ObjectMapper json;
    private final JobMemory memory;

    CareerTasks(CareerTaskStore store, JobService jobs, ExperienceService experiences,
            PracticeService practice, ObjectMapper json, JobMemory memory) {
        this.store = store;
        this.jobs = jobs;
        this.experiences = experiences;
        this.practice = practice;
        this.json = json;
        this.memory = memory;
    }

    Task training(String user, Training input) {
        return enqueue(user, input.requestId(), "TRAINING", input, () -> {
            var job = jobs.find(user, input.jobId().toString());
            var facts = experiences.list(user).stream().filter(ExperienceService.Entry::confirmed)
                    .limit(10).map(fact -> Map.of("id", fact.id(), "title", fact.title(),
                            "description", excerpt(fact.description(), 1800))).toList();
            var context = taskContext(user, job.id(), input.documentIds(), input.skillId());
            var jobSnapshot = jobContext(job);
            context.set("job", json.valueToTree(jobSnapshot));
            context.set("experiences", json.valueToTree(facts));
            if (input.role() != null) {
                context.put("role", input.role());
            }
            if (input.preparationId() != null) {
                preparation(user, job.id(), input.preparationId());
                if (input.preferredQuestion() != null) {
                    if (!input.preferredQuestion().matches(input.preparationId() + "-[0-4]")) {
                        throw new ResponseStatusException(BAD_REQUEST, "指定题目不属于所选模拟题批次");
                    }
                    openQuestion(user, job.id(), input.preferredQuestion(), 1);
                    context.put("preferredQuestion", input.preferredQuestion());
                }
            } else if (input.preferredQuestion() != null) {
                throw new ResponseStatusException(BAD_REQUEST, "请指定模拟题批次");
            } else if (input.role() == null && practice.recommendations(job.company(), job.title(),
                    jobSnapshot.get("jd"), jobSnapshot.get("skills")).questions().isEmpty()) {
                throw new ResponseStatusException(CONFLICT, "请先在面经与题库生成该岗位的模拟题");
            }
            return new Snapshot(job.id(), context);
        });
    }

    Task prepare(String user, PreparationRequest input) {
        return enqueue(user, input.requestId(), "PREPARATION", input, () -> {
            var job = jobs.find(user, input.jobId().toString());
            var context = taskContext(user, job.id(), input.documentIds(), input.skillId());
            context.set("job", json.valueToTree(jobContext(job)));
            return new Snapshot(job.id(), context);
        });
    }

    Task discover(String user, JobRequest input) {
        return enqueue(user, input.requestId(), "DISCOVERY", input, () -> {
            var job = jobs.find(user, input.jobId().toString());
            return new Snapshot(job.id(), Map.of("job", Map.of("label", job.company() + " · " + job.title(),
                    "company", job.company(), "title", job.title())));
        });
    }

    Task review(String user, Review input) {
        return enqueue(user, input.requestId(), "REVIEW", input, () -> {
            var plan = owned(user, input.planId());
            if (!"TRAINING".equals(plan.kind()) || !"SUCCEEDED".equals(plan.status())) {
                throw new ResponseStatusException(CONFLICT, "请选择已完成的训练计划");
            }
            var selected = plan.result().path("questions");
            var questions = StreamSupport.stream(selected.spliterator(), false)
                    .filter(q -> !"OPEN".equals(q.path("kind").asText()))
                    .map(q -> new PracticeService.QuestionVersion(q.path("id").asText(), q.path("version").asInt())).toList();
            var feedback = new ArrayList<Object>();
            if (!questions.isEmpty()) {
                feedback.addAll(practice.feedback(user, questions, plan.jobId(), plan.context().has("role")));
            }
            var openIds = StreamSupport.stream(selected.spliterator(), false)
                    .filter(q -> "OPEN".equals(q.path("kind").asText())).map(q -> q.path("id").asText()).toList();
            for (var answer : store.interviewFeedback(user, plan.jobId(), openIds)) {
                feedback.add(Map.of("question", answer.context().path("question").path("prompt"),
                        "answer", answer.context().path("answer"), "feedback", answer.result().path("feedback")));
            }
            if (feedback.isEmpty()) {
                throw new ResponseStatusException(CONFLICT, "请先完成计划中的至少一道练习");
            }
            var context = json.createObjectNode();
            context.set("job", plan.context().path("job"));
            context.set("plan", plan.result());
            context.set("feedback", json.valueToTree(feedback));
            return new Snapshot(plan.jobId(), context);
        });
    }

    List<PracticeService.QuestionVersion> trainingProgress(String user, UUID id) {
        var plan = owned(user, id);
        if (!"TRAINING".equals(plan.kind()) || !"SUCCEEDED".equals(plan.status())) {
            throw new ResponseStatusException(CONFLICT, "训练计划尚未生成");
        }
        var objective = new ArrayList<PracticeService.QuestionVersion>();
        var open = new ArrayList<String>();
        for (var question : plan.result().path("questions")) {
            String questionId = question.path("id").asText();
            if ("OPEN".equals(question.path("kind").asText())) {
                open.add(questionId);
            } else {
                objective.add(new PracticeService.QuestionVersion(questionId, question.path("version").asInt()));
            }
        }
        var completed = new ArrayList<>(practice.completedQuestions(user, objective, plan.jobId(), plan.context().has("role")));
        store.completedInterviews(user, plan.jobId(), open).forEach(
                question -> completed.add(new PracticeService.QuestionVersion(question, 1)));
        return completed;
    }

    Task interview(String user, Interview input) {
        return enqueue(user, input.requestId(), "INTERVIEW", input, () -> {
            var job = jobs.find(user, input.jobId().toString());
            Object question = input.questionId().matches("[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}-[0-9]")
                    ? openQuestion(user, job.id(), input.questionId(), input.questionVersion())
                    : practice.interviewQuestion(input.questionId(), input.questionVersion());
            var context = taskContext(user, job.id(), input.documentIds(), input.skillId());
            context.set("job", json.valueToTree(jobContext(job)));
            context.set("question", json.valueToTree(question));
            context.put("answer", input.answer().strip());
            return new Snapshot(job.id(), context);
        });
    }

    private JsonNode openQuestion(String user, String jobId, String id, int version) {
        var task = preparation(user, jobId, UUID.fromString(id.substring(0, 36)));
        var question = task.result().path("openQuestions").path(id.charAt(37) - '0');
        if (version != 1 || !(question instanceof ObjectNode openQuestion)) {
            throw new ResponseStatusException(NOT_FOUND, "岗位模拟题不存在");
        }
        var snapshot = json.createObjectNode().put("gradingVersion", 1).put("kind", "OPEN");
        snapshot.setAll(openQuestion);
        return snapshot;
    }

    private CareerTaskStore.Row preparation(String user, String jobId, UUID id) {
        var task = owned(user, id);
        if (!"PREPARATION".equals(task.kind()) || !jobId.equals(task.jobId()) || !"SUCCEEDED".equals(task.status())) {
            throw new ResponseStatusException(NOT_FOUND, "该岗位的模拟题不存在");
        }
        return task;
    }

    Task get(String user, UUID id) {
        return view(owned(user, id));
    }

    List<CareerTaskStore.Event> events(String user, UUID id) {
        owned(user, id);
        return store.events(id);
    }

    JsonNode checkpointContext(CareerTaskStore.Row row, JsonNode context) {
        var documents = row.context().path("documentIds");
        var references = context.path("references");
        var preferences = row.context().path("preferences");
        if (preferences.has("revision")) {
            int current = memory.read(row.user(), row.jobId()).revision();
            if (current != preferences.path("revision").asInt()) {
                throw new ResponseStatusException(CONFLICT, "备考偏好已修改，请重新创建任务");
            }
        }
        if (!context.path("payload").isObject() || context.path("payload").has("documents") || !references.isArray()
                || references.size() != documents.size() || context.toString().length() > 100_000
                || "DISCOVERY".equals(row.kind())) {
            throw new ResponseStatusException(BAD_REQUEST, "备考上下文格式无效");
        }
        for (int index = 0; index < references.size(); index++) {
            var ref = references.get(index);
            if (!documents.get(index).asText().equals(ref.path("id").asText())
                    || !ref.path("revision").asText().matches("[a-f0-9]{64}")
                    || ref.path("title").asText().isBlank() || ref.path("title").asText().length() > 512) {
                throw new ResponseStatusException(BAD_REQUEST, "备考资料引用不在本次任务范围内");
            }
        }
        var saved = store.checkpointContext(row, context).map(CareerTaskStore.Row::agentContext)
                .orElseThrow(() -> new ResponseStatusException(CONFLICT, "任务执行代次已失效"));
        if (!saved.equals(context)) throw new ResponseStatusException(CONFLICT, "备考上下文已保存");
        return saved;
    }

    Task retry(String user, UUID id) {
        var task = owned(user, id);
        if ("FAILED".equals(task.status())) {
            store.retry(user, id);
        }
        return get(user, id);
    }

    TaskPage list(String user, String kind, UUID jobId, int page) {
        if (!List.of("TRAINING", "REVIEW", "INTERVIEW", "PREPARATION", "DISCOVERY").contains(kind) || page < 1) {
            throw new ResponseStatusException(BAD_REQUEST, "任务类型或页码无效");
        }
        var rows = store.list(user, kind, jobId == null ? null : jobId.toString(), (page - 1L) * 20);
        return new TaskPage(rows.stream().limit(20).map(this::view).toList(), rows.size() > 20);
    }

    JsonNode checkpointQuestions(CareerTaskStore.Row row) {
        if (row.trainingCatalog() != null) {
            return row.trainingCatalog();
        }
        var job = row.context().path("job");
        var role = row.context().path("role").asText(null);
        var publicQuestions = role == null
                ? practice.recommendations(job.path("company").asText(), job.path("title").asText(),
                        job.path("jd").asText(), job.path("skills").asText()).questions()
                : practice.questions(role);
        var catalog = json.createArrayNode();
        var preparationId = row.request().path("preparationId").asText(null);
        if (preparationId != null) {
            var saved = preparation(row.user(), row.jobId(), UUID.fromString(preparationId));
            var questions = saved.result().path("openQuestions");
            for (int index = 0; index < questions.size(); index++) {
                var question = questions.get(index);
                catalog.addObject().put("id", saved.id() + "-" + index).put("version", 1)
                        .put("kind", "OPEN").put("sourceName", "AI 模拟题")
                        .put("topic", question.path("topic").asText()).put("prompt", question.path("prompt").asText());
            }
        }
        publicQuestions.stream().limit(30 - catalog.size()).<JsonNode>map(json::valueToTree).forEach(catalog::add);
        if (catalog.isEmpty()) {
            throw new ResponseStatusException(CONFLICT, "当前岗位方向暂无训练题目");
        }
        return store.checkpointCatalog(row, catalog).map(CareerTaskStore.Row::trainingCatalog)
                .orElseThrow(() -> new ResponseStatusException(CONFLICT, "训练任务执行代次已失效"));
    }

    void checkpointPlan(CareerTaskStore.Row row, Plan input) {
        var catalog = row.trainingCatalog();
        if (catalog == null) {
            throw new ResponseStatusException(CONFLICT, "请先完成查题");
        }
        var ids = new HashSet<String>();
        var selected = input.questions().stream().map(ref -> {
            if (!ids.add(ref.id())) {
                throw new ResponseStatusException(BAD_REQUEST, "训练题目不能重复");
            }
            return StreamSupport.stream(catalog.spliterator(), false)
                    .filter(q -> q.path("id").asText().equals(ref.id()) && q.path("version").asInt() == ref.version())
                    .findFirst().orElseThrow(() -> new ResponseStatusException(BAD_REQUEST, "训练题目或版本无效"));
        }).toList();
        var preferred = row.context().path("preferredQuestion").asText(null);
        if (preferred != null && !ids.contains(preferred)) {
            throw new ResponseStatusException(BAD_REQUEST, "计划必须包含用户指定的题目");
        }
        var result = json.valueToTree(Map.of("analysis", input.analysis(), "steps", input.steps(),
                "questions", selected));
        var saved = store.checkpointDraft(row, result).map(CareerTaskStore.Row::trainingDraft)
                .orElseThrow(() -> new ResponseStatusException(CONFLICT, "训练任务执行代次已失效"));
        if (!saved.equals(result)) {
            throw new ResponseStatusException(CONFLICT, "训练任务已有不同的计划草稿");
        }
    }

    private Task enqueue(String user, UUID key, String kind, Object input, Supplier<Snapshot> snapshot) {
        JsonNode request = json.valueToTree(input);
        var row = store.byRequest(user, key).orElseGet(() -> {
            var data = snapshot.get();
            return store.insert(user, key, kind, data.jobId(), request, json.valueToTree(data.context()));
        });
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
        var prepared = row.agentContext();
        return new Task(row.id(), row.kind(), row.status(), row.request(), job.path("label").asText(), interview,
                row.result(), row.error(), row.generation(), trainingStep(row),
                prepared == null ? null : prepared.get("references"), row.createdAt(), row.updatedAt());
    }

    private static String trainingStep(CareerTaskStore.Row row) {
        if (!"TRAINING".equals(row.kind())) return null;
        if ("SUCCEEDED".equals(row.status())) return "COMPLETE";
        if (row.trainingDraft() != null) return "SAVE_PLAN";
        return row.trainingCatalog() == null ? "FIND_QUESTIONS" : "GENERATE_PLAN";
    }

    private static Map<String, String> jobContext(JobService.Entry job) {
        return Map.of("label", job.company() + " · " + job.title(), "jd", excerpt(job.description(), 8000),
                "company", job.company(), "title", job.title(), "skills", job.skills() == null ? "" : job.skills());
    }

    private ObjectNode taskContext(String user, String job, List<UUID> documents, UUID skillId) {
        var context = json.createObjectNode();
        var preferences = memory.read(user, job);
        if (preferences.notes() != null) context.set("preferences", json.valueToTree(preferences));
        if (documents != null && !documents.isEmpty()) {
            if (new HashSet<>(documents).size() != documents.size()) {
                throw new ResponseStatusException(BAD_REQUEST, "备考资料不能重复");
            }
            context.set("documentIds", json.valueToTree(documents));
        }
        if (skillId != null) context.put("skillId", skillId.toString());
        return context;
    }

    private static String excerpt(String value, int limit) {
        return value.codePoints().limit(limit).collect(StringBuilder::new, StringBuilder::appendCodePoint,
                StringBuilder::append).toString();
    }

    private record Snapshot(String jobId, Object context) {}
    record JobRequest(@NotNull UUID requestId, @NotNull UUID jobId) {}
    record PreparationRequest(@NotNull UUID requestId, @NotNull UUID jobId,
            @JsonInclude(JsonInclude.Include.NON_EMPTY) @Size(max = 3) List<@NotNull UUID> documentIds,
            @JsonInclude(JsonInclude.Include.NON_NULL) UUID skillId) {}
    record Training(@NotNull UUID requestId, @NotNull UUID jobId,
            @Pattern(regexp = "backend|algorithm|llm") String role,
            @JsonInclude(JsonInclude.Include.NON_NULL) UUID preparationId,
            @JsonInclude(JsonInclude.Include.NON_NULL)
            @Pattern(regexp = "[a-z0-9-]{1,64}") String preferredQuestion,
            @JsonInclude(JsonInclude.Include.NON_EMPTY) @Size(max = 3) List<@NotNull UUID> documentIds,
            @JsonInclude(JsonInclude.Include.NON_NULL) UUID skillId) {}
    record Review(@NotNull UUID requestId, @NotNull UUID planId) {}
    record Interview(@NotNull UUID requestId, @NotNull UUID jobId,
            @NotNull @Pattern(regexp = "[a-z0-9-]{1,64}") String questionId, @NotNull @Positive Integer questionVersion,
            @NotBlank @Size(max = 6000) String answer,
            @JsonInclude(JsonInclude.Include.NON_EMPTY) @Size(max = 3) List<@NotNull UUID> documentIds,
            @JsonInclude(JsonInclude.Include.NON_NULL) UUID skillId) {}
    record Plan(@NotBlank @Size(max = 4000) String analysis,
            @NotNull @Size(min = 1, max = 8) List<@NotBlank @Size(max = 600) String> steps,
            @NotNull @Size(min = 1, max = 8) List<@NotNull @Valid QuestionRef> questions) {}
    record QuestionRef(@NotNull @Pattern(regexp = "[a-z0-9-]{1,64}") String id,
            @NotNull @Positive Integer version) {}
    record Task(String id, String kind, String status, JsonNode request, String job, JsonNode interview,
            JsonNode result, String error, int generation, String trainingStep, JsonNode references,
            Instant createdAt, Instant updatedAt) {}
    record TaskPage(List<Task> items, boolean hasMore) {}
}
