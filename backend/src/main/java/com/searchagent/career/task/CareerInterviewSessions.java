package com.searchagent.career.task;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.CONFLICT;
import static org.springframework.http.HttpStatus.NOT_FOUND;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.regex.Pattern;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import com.searchagent.career.job.JobService;
import com.searchagent.career.practice.PracticeService;
import com.searchagent.career.task.InterviewQuestions.Phase;
import com.searchagent.career.task.InterviewQuestions.Question;

@Service
class CareerInterviewSessions {
    private static final int FOLLOW_UP_LIMIT = 2;
    private static final int PAGE_SIZE = 20;
    private static final Map<String, Pattern> ROLE_HINTS = Map.of(
            "backend", Pattern.compile("后端|服务端|\\b(backend|java|mysql|spring)\\b"),
            "algorithm", Pattern.compile("算法|数据结构|\\balgorithm\\b"),
            "llm", Pattern.compile("大模型|人工智能|智能体|\\b(agent|rag|llm|nlp)\\b"));

    private final CareerInterviewStore store;
    private final CareerTaskStore tasks;
    private final JobService jobs;
    private final PracticeService practice;
    private final InterviewQuestions bank;
    private final ObjectMapper json;

    CareerInterviewSessions(CareerInterviewStore store, CareerTaskStore tasks, JobService jobs, PracticeService practice,
            InterviewQuestions bank, ObjectMapper json) {
        this.store = store;
        this.tasks = tasks;
        this.jobs = jobs;
        this.practice = practice;
        this.bank = bank;
        this.json = json;
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    View start(String user, Start input) {
        if (!List.of(3, 5, 8).contains(input.count())) {
            throw new ResponseStatusException(BAD_REQUEST, "请选择 3、5 或 8 道主问题");
        }
        String jobId = input.jobId().toString();
        var state = store.find(user, input.requestId(), false).orElseGet(() -> {
            var job = jobs.find(user, jobId);
            var recent = new HashSet<String>();
            store.list(user, jobId, 5, 0).forEach(session -> session.rounds().forEach(round -> {
                if (round.main() != null) recent.add(round.question().id());
            }));
            var questions = bank.draw(job.title(), input.count(), jobQuestions(user, job), recent);
            var now = Instant.now();
            var jobContext = Map.of("company", job.company(), "title", job.title(), "jd", excerpt(job.description(), 6000),
                    "skills", Objects.requireNonNullElse(job.skills(), ""));
            var initial = new Session(input.requestId(), jobId, jobContext, input.mode(), Status.ACTIVE,
                    now, now, 0, 0, 0, questions.stream().map(question -> new Round(question, null, null, null)).toList(), null);
            return store.insert(user, initial);
        });
        if (!state.jobId().equals(jobId) || state.mode() != input.mode() || state.rounds().size() != input.count()) {
            throw conflict("开始编号已用于另一场面试");
        }
        return view(user, state);
    }

    Page list(String user, int page) {
        if (page < 1) throw new ResponseStatusException(BAD_REQUEST, "页码须为正整数");
        var rows = store.list(user, null, PAGE_SIZE + 1, (page - 1L) * PAGE_SIZE);
        return new Page(rows.stream().limit(PAGE_SIZE).map(Session::summary).toList(), rows.size() > PAGE_SIZE);
    }

    View get(String user, UUID id) {
        return view(user, owned(user, id, false));
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    View answer(String user, UUID id, Answer input) {
        var state = owned(user, id, true);
        for (var round : state.rounds()) {
            for (var turn : round.turns()) {
                if (turn.requestId().equals(input.requestId())) {
                    if (!turn.answer().equals(input.answer().strip())) throw conflict("提交编号已用于另一条回答");
                    return view(user, state);
                }
            }
        }
        checkRevision(state, input.revision());
        requireActive(state);
        if (state.pending() != null) throw conflict("请等待当前回答处理完成");
        var round = state.rounds().get(state.index());
        boolean extra = round.followUp() != null;
        boolean allowFollowUp = !extra && state.followUps() < FOLLOW_UP_LIMIT;
        String answer = input.answer().strip();
        var context = json.createObjectNode();
        context.set("job", json.valueToTree(state.job()));
        context.set("question", json.valueToTree(round.question()));
        context.put("answer", answer).put("allowFollowUp", allowFollowUp);
        if (extra) {
            context.put("followUp", round.followUp()).put("mainAnswer", excerpt(round.main().answer(), 1600));
        }
        var request = json.createObjectNode().put("sessionId", id.toString()).put("revision", state.revision());
        var task = tasks.insert(user, input.requestId(), "INTERVIEW_TURN", state.jobId(), request, context);
        if (!"INTERVIEW_TURN".equals(task.kind()) || !request.equals(task.request())) {
            throw conflict("提交编号已用于另一项任务");
        }
        var turn = new Turn(input.requestId(), answer, null, false);
        var updated = extra ? new Round(round.question(), round.main(), round.followUp(), turn)
                : new Round(round.question(), turn, null, null);
        return save(user, state.progress(state.index(), updated, UUID.fromString(task.id())));
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    View advance(String user, UUID id, Decision input) {
        var state = owned(user, id, true);
        if (!input.taskId().equals(state.pending())) return view(user, state);
        requireActive(state);
        var task = pending(user, state);
        boolean failed = "FAILED".equals(task.status());
        boolean succeeded = "SUCCEEDED".equals(task.status());
        if (!succeeded && !(failed && input.skipFailed())) return view(user, state);
        return save(user, applyEvaluation(state, succeeded ? json.convertValue(task.result(), Evaluation.class) : null, failed));
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    void finishTask(CareerTaskStore.Row task, JsonNode result, String error) {
        if (error != null) {
            tasks.finish(task, result, error);
            return;
        }
        var session = store.find(task.user(), UUID.fromString(task.request().path("sessionId").asText()), true);
        if (!tasks.finish(task, result, null)) return;
        session.filter(state -> task.id().equals(Objects.toString(state.pending(), null))).ifPresent(state ->
                store.save(task.user(), applyEvaluation(state, json.convertValue(result, Evaluation.class), false)));
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    void recover(CareerInterviewStore.PendingSession item) {
        var session = store.find(item.user(), item.sessionId(), true);
        session.filter(state -> item.taskId().equals(state.pending())).ifPresent(state -> {
            var task = pending(item.user(), state);
            if ("SUCCEEDED".equals(task.status())) {
                store.save(item.user(), applyEvaluation(state, json.convertValue(task.result(), Evaluation.class), false));
            }
        });
    }

    private Session applyEvaluation(Session state, Evaluation evaluation, boolean failed) {
        var round = state.rounds().get(state.index());
        boolean isFollowUp = round.followUp() != null;
        String followUp = isFollowUp ? round.followUp() : nextFollowUp(state, evaluation);
        var updated = isFollowUp
                ? new Round(round.question(), round.main(), followUp, round.extra().evaluated(evaluation, failed))
                : new Round(round.question(), round.main().evaluated(evaluation, failed), followUp, null);
        int next = !isFollowUp && followUp != null ? state.index() : state.index() + 1;
        var advanced = state.progress(next, updated, null);
        if (next == state.rounds().size()) advanced = advanced.changeStatus(Status.FINISHED);
        return advanced;
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    View retry(String user, UUID id, Decision input) {
        var state = owned(user, id, true);
        if (!input.taskId().equals(state.pending())) return view(user, state);
        requireActive(state);
        if ("FAILED".equals(pending(user, state).status())) tasks.retry(user, input.taskId());
        return view(user, state);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    View status(String user, UUID id, StatusChange input) {
        var state = owned(user, id, true);
        if (state.status() == input.status()) return view(user, state);
        checkRevision(state, input.revision());
        if (state.status() == Status.FINISHED) throw conflict("这场面试已结束");
        if (input.status() == Status.FINISHED && state.pending() != null) {
            throw conflict("请先完成当前回答的处理");
        }
        return save(user, state.changeStatus(input.status()));
    }

    private String nextFollowUp(Session state, Evaluation evaluation) {
        if (evaluation == null || evaluation.followUp() == null || state.followUps() >= FOLLOW_UP_LIMIT) return null;
        var prompt = evaluation.followUp().strip();
        var normalized = InterviewQuestions.normalize(prompt);
        if (normalized.isBlank()) return null;
        boolean repeated = state.rounds().stream().anyMatch(round ->
                normalized.equals(InterviewQuestions.normalize(round.question().prompt()))
                || (round.followUp() != null && normalized.equals(InterviewQuestions.normalize(round.followUp()))));
        return repeated ? null : prompt;
    }

    private List<Question> jobQuestions(String user, JobService.Entry job) {
        var result = new ArrayList<Question>();
        for (var task : tasks.interviewPreparations(user, job.id())) {
            var questions = task.result().path("openQuestions");
            for (int index = 0; index < questions.size(); index++) {
                var question = questions.get(index);
                var rubric = new ArrayList<String>();
                question.path("rubric").forEach(item -> rubric.add(item.asText()));
                result.add(new Question(task.id() + "-" + index, 1, 1, Phase.CORE,
                        question.path("topic").asText(), question.path("prompt").asText(), rubric, "岗位 AI 模拟题", null));
            }
        }
        var topics = new HashSet<>(practice.recommendations(job).questions());
        String direction = (job.title() + " " + Objects.requireNonNullElse(job.skills(), "")).toLowerCase(Locale.ROOT);
        ROLE_HINTS.entrySet().stream().filter(entry -> entry.getValue().matcher(direction).find())
                .map(Map.Entry::getKey).forEach(role -> topics.addAll(practice.questions(role)));
        for (var topic : topics) {
            result.add(new Question("topic-" + topic.id(), topic.version(), 1, Phase.CORE, topic.topic(),
                    "请用自己的话解释「%s」涉及的核心原理。举例说明它怎样用在「%s」的实际工作中，以及如何验证效果。"
                            .formatted(topic.topic(), job.title()),
                    List.of("原理描述准确", "举例与岗位职责相关", "说明验证方式或适用边界"), topic.sourceName(), topic.sourceUrl()));
        }
        return result;
    }

    private Session owned(String user, UUID id, boolean lock) {
        return store.find(user, id, lock).orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "面试记录不存在"));
    }

    private CareerTaskStore.Row pending(String user, Session state) {
        return tasks.owned(user, state.pending()).orElseThrow(() -> conflict("回答处理记录不可用"));
    }

    private View save(String user, Session state) {
        store.save(user, state);
        return view(user, state);
    }

    private View view(String user, Session state) {
        boolean finished = state.status() == Status.FINISHED;
        var transcript = new ArrayList<TranscriptLine>();
        var review = new ArrayList<Round>();
        for (var round : state.rounds()) {
            if (round.main() == null) continue;
            transcript.add(new TranscriptLine(round.question().prompt(), round.main().answer(), false));
            if (round.extra() != null) transcript.add(new TranscriptLine(round.followUp(), round.extra().answer(), true));
            if (finished) review.add(round);
        }
        var phases = List.of(Phase.values()).stream().map(phase -> new PhaseProgress(phase,
                state.rounds().stream().filter(round -> round.question().phase() == phase).count(),
                state.rounds().subList(0, state.index()).stream().filter(round -> round.question().phase() == phase).count())).toList();
        var current = finished ? null : state.rounds().get(state.index());
        var question = current == null ? null : new CurrentQuestion(state.index() + 1, current.question().phase(),
                current.followUp() == null ? current.question().prompt() : current.followUp(), current.followUp() != null);
        var task = state.pending() == null ? null : pending(user, state);
        var pending = task == null ? null : new Pending(state.pending(), task.status(), task.error(), task.generation());
        return new View(state.summary(), state.revision(), question, phases, transcript, pending, review);
    }

    private static void checkRevision(Session state, int revision) {
        if (state.revision() != revision) throw conflict("面试进度已更新，请刷新后继续");
    }

    private static void requireActive(Session state) {
        if (state.status() != Status.ACTIVE) throw conflict("请先继续面试");
    }

    private static ResponseStatusException conflict(String message) {
        return new ResponseStatusException(CONFLICT, message);
    }

    private static String excerpt(String text, int maxCodePoints) {
        return text.codePoints().limit(maxCodePoints).collect(StringBuilder::new, StringBuilder::appendCodePoint,
                StringBuilder::append).toString();
    }

    enum Mode { VIDEO, VOICE, TEXT }
    enum Status { ACTIVE, PAUSED, FINISHED }

    record Start(@NotNull UUID requestId, @NotNull UUID jobId, @NotNull Mode mode, @NotNull Integer count) {}
    record Answer(@NotNull UUID requestId, @NotNull @PositiveOrZero Integer revision,
            @NotBlank(message = "请输入本题回答") @Size(max = 4000, message = "回答最多 4000 字") String answer) {}
    record Decision(@NotNull UUID taskId, boolean skipFailed) {}
    record StatusChange(@NotNull @PositiveOrZero Integer revision, @NotNull Status status) {}
    record Evaluation(@NotNull @Min(1) @Max(5) Integer accuracy, @NotNull @Min(1) @Max(5) Integer evidence,
            @NotNull @Min(1) @Max(5) Integer structure, @NotBlank @Size(max = 1400) String feedback,
            @Size(max = 500) String followUp) {}

    record Turn(UUID requestId, String answer, Evaluation evaluation, boolean evaluationUnavailable) {
        Turn evaluated(Evaluation result, boolean unavailable) {
            return new Turn(requestId, answer, result == null ? null
                    : new Evaluation(result.accuracy(), result.evidence(), result.structure(), result.feedback(), null),
                    unavailable);
        }
    }

    record Round(Question question, Turn main, String followUp, Turn extra) {
        List<Turn> turns() {
            if (extra != null) return List.of(main, extra);
            return main == null ? List.of() : List.of(main);
        }
    }

    record Session(UUID id, String jobId, Map<String, String> job, Mode mode, Status status, Instant createdAt,
            Instant activeSince, long elapsedSeconds, int revision, int index, List<Round> rounds, UUID pending) {
        long elapsed(Instant now) {
            return elapsedSeconds + (activeSince == null ? 0 : Math.max(0, Duration.between(activeSince, now).toSeconds()));
        }

        int followUps() {
            return (int) rounds.stream().filter(round -> round.followUp() != null).count();
        }

        Session progress(int newIndex, Round round, UUID task) {
            var updated = new ArrayList<>(rounds);
            updated.set(index, round);
            return new Session(id, jobId, job, mode, status, createdAt, activeSince, elapsedSeconds, revision + 1,
                    newIndex, updated, task);
        }

        Session changeStatus(Status next) {
            Instant now = Instant.now();
            return new Session(id, jobId, job, mode, next, createdAt, next == Status.ACTIVE ? now : null,
                    elapsed(now), revision + 1, index, rounds, pending);
        }

        Summary summary() {
            return new Summary(id, jobId, job.get("company") + " · " + job.get("title"), mode, status, rounds.size(),
                    (int) rounds.stream().filter(round -> round.main() != null).count(),
                    (int) rounds.stream().filter(round -> round.extra() != null).count(), elapsed(Instant.now()), createdAt);
        }
    }

    record Summary(UUID id, String jobId, String job, Mode mode, Status status, int count, int answered,
            int followUps, long elapsedSeconds, Instant createdAt) {}
    record Page(List<Summary> items, boolean hasMore) {}
    record CurrentQuestion(int number, Phase phase, String prompt, boolean followUp) {}
    record PhaseProgress(Phase phase, long total, long completed) {}
    record TranscriptLine(String prompt, String answer, boolean followUp) {}
    record Pending(UUID id, String status, String error, int generation) {}
    record View(Summary summary, int revision, CurrentQuestion current, List<PhaseProgress> phases,
            List<TranscriptLine> transcript, Pending pending, List<Round> review) {}
}
