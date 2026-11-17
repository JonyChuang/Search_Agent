package com.searchagent.career.task;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
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
    private final CareerInterviewStore interviews;
    private final JobService jobs;
    private final ExperienceService experiences;
    private final PracticeService practice;
    private final ObjectMapper json;
    private final JobMemory memory;

    CareerTasks(CareerTaskStore store, CareerInterviewStore interviews, JobService jobs, ExperienceService experiences,
            PracticeService practice, ObjectMapper json, JobMemory memory) {
        this.store = store;
        this.interviews = interviews;
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
            if (input.previousPlanId() != null || input.reviewTaskId() != null) {
                if (input.previousPlanId() == null || input.reviewTaskId() == null) {
                    throw new ResponseStatusException(BAD_REQUEST, "请选择原计划和复盘记录");
                }
                var previous = owned(user, input.previousPlanId());
                var review = owned(user, input.reviewTaskId());
                if (!"TRAINING".equals(previous.kind()) || !"REVIEW".equals(review.kind())
                        || !"SUCCEEDED".equals(previous.status()) || !"SUCCEEDED".equals(review.status())
                        || !job.id().equals(previous.jobId()) || !job.id().equals(review.jobId())
                        || !previous.id().equals(review.request().path("planId").asText())) {
                    throw new ResponseStatusException(CONFLICT, "请选择本岗位原计划对应的已完成复盘");
                }
                context.set("plan", previous.result());
                context.put("revisionReview", excerpt(review.result().path("feedback").asText(), 2000));
            }
            var interviewFeedback = recentInterviewFeedback(user, job.id());
            if (!interviewFeedback.isEmpty()) context.set("interviewFeedback", json.valueToTree(interviewFeedback));
            if (input.role() != null) {
                context.put("role", input.role());
            }
            var preparationId = input.preparationId();
            if (preparationId == null && input.role() == null && input.preferredQuestion() == null) {
                preparationId = store.interviewPreparations(user, job.id()).stream().findFirst()
                        .map(item -> UUID.fromString(item.id())).orElse(null);
            }
            if (preparationId != null) {
                preparation(user, job.id(), preparationId);
                context.put("preparationId", preparationId.toString());
                if (input.preferredQuestion() != null) {
                    if (!input.preferredQuestion().matches(preparationId + "-[0-4]")) {
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
            if ("NOTES".equals(input.purpose()) && !context.has("documentIds")) {
                throw new ResponseStatusException(BAD_REQUEST, "请先选择用于整理面经的资料");
            }
            context.set("job", json.valueToTree(jobContext(job)));
            if (input.purpose() != null) context.put("purpose", input.purpose());
            if (input.topic() != null && !input.topic().isBlank()) context.put("topic", input.topic().strip());
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
            var interviewFeedback = recentInterviewFeedback(user, plan.jobId());
            if (feedback.isEmpty() && interviewFeedback.isEmpty()) {
                throw new ResponseStatusException(CONFLICT, "请先完成计划练习或本岗位的模拟面试");
            }
            var context = json.createObjectNode();
            context.set("job", plan.context().path("job"));
            context.set("plan", plan.result());
            context.set("feedback", json.valueToTree(feedback));
            if (!interviewFeedback.isEmpty()) context.set("interviewFeedback", json.valueToTree(interviewFeedback));
            return new Snapshot(plan.jobId(), context);
        });
    }

    List<PracticeService.QuestionVersion> trainingProgress(String user, UUID id) {
        var plan = owned(user, id);
        if (!"TRAINING".equals(plan.kind()) || !"SUCCEEDED".equals(plan.status())) {
            throw new ResponseStatusException(CONFLICT, "训练计划尚未生成");
        }
        var objective = new ArrayList<PracticeService.QuestionVersion>();
        var open = new ArrayList<PracticeService.QuestionVersion>();
        for (var question : plan.result().path("questions")) {
            var ref = new PracticeService.QuestionVersion(question.path("id").asText(), question.path("version").asInt());
            if ("OPEN".equals(question.path("kind").asText())) {
                open.add(ref);
            } else {
                objective.add(ref);
            }
        }
        var completed = new LinkedHashSet<>(practice.completedQuestions(user, objective, plan.jobId(), plan.context().has("role")));
        store.completedInterviews(user, plan.jobId(), open.stream().filter(ref -> ref.version() == 1)
                .map(PracticeService.QuestionVersion::id).toList()).forEach(
                question -> completed.add(new PracticeService.QuestionVersion(question, 1)));
        completed.addAll(interviews.completedQuestions(user, plan.jobId(), open));
        return List.copyOf(completed);
    }

    private List<Map<String, Object>> recentInterviewFeedback(String user, String jobId) {
        return interviews.recentCompleted(user, jobId).stream().flatMap(session -> session.rounds().stream()
                .filter(round -> round.main() != null && round.main().evaluation() != null)
                .map(round -> {
                    var question = round.question();
                    var evaluation = round.main().evaluation();
                    return Map.<String, Object>of("sessionId", session.id(), "topic", question.topic(),
                            "question", question.prompt(), "questionId", question.id(), "version", question.version(),
                            "answer", excerpt(round.main().answer(), 600), "feedback", evaluation.feedback(),
                            "scores", List.of(evaluation.accuracy(), evaluation.evidence(), evaluation.structure()),
                            "followUpFeedback", round.extra() != null && round.extra().evaluation() != null
                                    ? round.extra().evaluation().feedback() : "");
                })).limit(8).toList();
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

    JsonNode openQuestion(String user, String jobId, String id, int version) {
        if (!id.matches("[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}-[0-4]")) {
            throw new ResponseStatusException(NOT_FOUND, "岗位模拟题不存在");
        }
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
        return view(publicTask(user, id));
    }

    List<CareerTaskStore.Event> events(String user, UUID id) {
        publicTask(user, id);
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
        var task = publicTask(user, id);
        if ("FAILED".equals(task.status())) {
            store.retry(user, id);
        }
        return get(user, id);
    }

    Task changeState(String user, UUID id, TaskTransition input) {
        var task = publicTask(user, id);
        String target = switch (input.action()) {
            case PAUSE -> "WAITING_USER";
            case RESUME -> "QUEUED";
            case CANCEL -> "CANCELLED";
        };
        if (task.status().equals(target) && task.generation() == input.generation()) return view(task);
        boolean allowed = switch (input.action()) {
            case PAUSE -> List.of("QUEUED", "RUNNING").contains(task.status())
                    && !("TRAINING".equals(task.kind()) && task.trainingDraft() != null);
            case RESUME -> "WAITING_USER".equals(task.status());
            case CANCEL -> List.of("QUEUED", "RUNNING", "WAITING_USER", "FAILED").contains(task.status())
                    && !("TRAINING".equals(task.kind()) && task.trainingDraft() != null);
        };
        if (!allowed || store.changeState(user, id, input.status(), input.generation(), target) != 1) {
            throw new ResponseStatusException(CONFLICT, "任务状态已变化，请刷新后重试");
        }
        return get(user, id);
    }

    TaskPage list(String user, String kind, UUID jobId, String content, int page) {
        if (!List.of("TRAINING", "REVIEW", "INTERVIEW", "PREPARATION", "DISCOVERY").contains(kind) || page < 1) {
            throw new ResponseStatusException(BAD_REQUEST, "任务类型或页码无效");
        }
        if (content != null && (!"PREPARATION".equals(kind) || !List.of("notes", "questions").contains(content))) {
            throw new ResponseStatusException(BAD_REQUEST, "备考内容类型无效");
        }
        var rows = store.list(user, kind, jobId == null ? null : jobId.toString(), content, (page - 1L) * 20);
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
        var preparationId = row.context().path("preparationId").asText(row.request().path("preparationId").asText(null));
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

    private CareerTaskStore.Row publicTask(String user, UUID id) {
        var row = owned(user, id);
        if ("INTERVIEW_TURN".equals(row.kind())) throw new ResponseStatusException(NOT_FOUND, "任务不存在");
        return row;
    }

    private Task view(CareerTaskStore.Row row) {
        var question = row.context().path("question");
        JsonNode interview = null;
        if ("INTERVIEW".equals(row.kind())) {
            var detail = json.createObjectNode().put("prompt", question.path("prompt").asText())
                    .put("gradingVersion", question.path("gradingVersion").asInt())
                    .put("sourceUrl", question.path("sourceUrl").asText())
                    .put("answer", row.context().path("answer").asText());
            if ("SUCCEEDED".equals(row.status()) && "OPEN".equals(question.path("kind").asText())) {
                detail.set("rubric", question.path("rubric"));
                if (question.hasNonNull("referenceAnswer")) detail.set("referenceAnswer", question.path("referenceAnswer"));
            }
            interview = detail;
        }
        var job = row.context().path("job");
        var prepared = row.agentContext();
        JsonNode result = row.result();
        if (result != null && result.has("openQuestions")) {
            result = result.deepCopy();
            for (var item : result.path("openQuestions")) {
                if (item instanceof ObjectNode questionResult) {
                    questionResult.remove(List.of("rubric", "referenceAnswer"));
                }
            }
        }
        return new Task(row.id(), row.kind(), row.status(), row.request(), job.path("label").asText(), interview,
                result, row.error(), row.generation(), trainingStep(row),
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
            @JsonInclude(JsonInclude.Include.NON_NULL) UUID skillId,
            @JsonInclude(JsonInclude.Include.NON_NULL) @Pattern(regexp = "NOTES") String purpose,
            @JsonInclude(JsonInclude.Include.NON_NULL) @Size(max = 80) String topic) {}
    record Training(@NotNull UUID requestId, @NotNull UUID jobId,
            @Pattern(regexp = "backend|algorithm|llm") String role,
            @JsonInclude(JsonInclude.Include.NON_NULL) UUID preparationId,
            @JsonInclude(JsonInclude.Include.NON_NULL)
            @Pattern(regexp = "[a-z0-9-]{1,64}") String preferredQuestion,
            @JsonInclude(JsonInclude.Include.NON_EMPTY) @Size(max = 3) List<@NotNull UUID> documentIds,
            @JsonInclude(JsonInclude.Include.NON_NULL) UUID skillId,
            @JsonInclude(JsonInclude.Include.NON_NULL) UUID previousPlanId,
            @JsonInclude(JsonInclude.Include.NON_NULL) UUID reviewTaskId) {}
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
    enum TaskAction { PAUSE, RESUME, CANCEL }
    record TaskTransition(@NotNull TaskAction action, @NotBlank String status,
            @NotNull @jakarta.validation.constraints.PositiveOrZero Integer generation) {}
}
