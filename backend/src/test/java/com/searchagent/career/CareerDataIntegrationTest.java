package com.searchagent.career;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.awt.image.BufferedImage;
import java.nio.charset.StandardCharsets;
import java.io.ByteArrayOutputStream;
import java.time.Instant;
import java.util.Base64;
import java.util.Date;
import java.util.HashSet;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import javax.imageio.ImageIO;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.http.HttpMethod;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties = {
        "spring.datasource.url=${CAREER_TEST_MYSQL_URL}",
        "spring.datasource.username=${CAREER_TEST_MYSQL_USER}",
        "spring.datasource.password=${CAREER_TEST_MYSQL_PASSWORD:}",
        "career.auth.jwt-secret=" + CareerDataIntegrationTest.TEST_SECRET,
        "career.auth.jwt-algorithm=HS256",
        "career.agent.base-url=http://127.0.0.1:1",
        "career.agent.internal-token=integration-test-service-token",
        "career.agent.dispatch-enabled=false"
})
@AutoConfigureMockMvc
@EnabledIfEnvironmentVariable(named = "CAREER_TEST_MYSQL_URL", matches = "jdbc:mysql:.+")
class CareerDataIntegrationTest {
    static final String TEST_SECRET = "test-only-signing-secret-at-least-32-bytes";
    private static final String PROFILE = "/api/career/profile";
    private static final String EXPERIENCES = "/api/career/experiences";
    private static final String JOBS = "/api/career/jobs";
    private static final String QUESTIONS = "/api/career/questions";
    private static final String ATTEMPTS = "/api/career/practice/attempts";
    private static final String WRONG = "/api/career/practice/wrong-questions";
    private static final String HASHCODE = "backend-java-hashcode";

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @Autowired JdbcTemplate jdbc;

    private final String owner = UUID.randomUUID().toString();
    private final String other = UUID.randomUUID().toString();

    @AfterEach
    void removeTestData() {
        jdbc.update("""
                DELETE e FROM career_application_event e JOIN career_application a ON a.id = e.application_id
                WHERE a.user_id IN (?, ?)
                """, owner, other);
        jdbc.update("DELETE FROM career_application WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_resume_version WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_resume_profile WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_mock_interview WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_task WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_practice_attempt WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_experience WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_job WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_profile WHERE user_id IN (?, ?)", owner, other);
    }

    @Test
    void mockInterviewPersistsRandomRoundsAndBoundsAdaptiveFollowUps() throws Exception {
        String job = createWorkflowJob();
        String path = "/api/career/interviews";
        String requestId = UUID.randomUUID().toString();
        String input = """
                {"requestId":"%s","jobId":"%s","mode":"TEXT","count":5}
                """.formatted(requestId, job);
        JsonNode first = interviewPost(path, input);
        String id = first.path("summary").path("id").asText();
        String session = path + "/" + id;
        assertEquals(first.path("current"), interviewPost(path, input).path("current"));
        assertEquals("WARMUP", first.path("current").path("phase").asText());
        assertEquals(3, first.path("phases").get(1).path("total").asInt());
        assertTrue(first.path("review").isEmpty());
        mvc.perform(get(session).header("Authorization", access(other))).andExpect(status().isNotFound());
        mvc.perform(post(path).header("Authorization", access(other)).contentType("application/json")
                .content(input)).andExpect(status().isNotFound());

        JsonNode state = interviewPost(session + "/status", "{\"revision\":0,\"status\":\"PAUSED\"}");
        assertEquals(first.path("current"), state.path("current"));
        state = interviewPost(session + "/status", "{\"revision\":1,\"status\":\"ACTIVE\"}");
        var prompts = new HashSet<String>();
        for (int number = 1; number <= 5; number++) {
            assertEquals(number, state.path("current").path("number").asInt());
            assertTrue(prompts.add(state.path("current").path("prompt").asText()));
            int revision = state.path("revision").asInt();
            String answer = """
                    {"revision":%s,"requestId":"%s","answer":"我用对照实验验证方案"}
                    """.formatted(revision, UUID.randomUUID());
            state = interviewPost(session + "/answer", answer);
            assertEquals(state.path("pending"), interviewPost(session + "/answer", answer).path("pending"));
            mvc.perform(post(session + "/answer").header("Authorization", access(owner)).contentType("application/json")
                    .content("""
                            {"revision":%s,"requestId":"%s","answer":"旧窗口提交"}
                            """.formatted(revision, UUID.randomUUID()))).andExpect(status().isConflict());
            var reloaded = json.readTree(mvc.perform(get(session).header("Authorization", access(owner)))
                    .andExpect(status().isOk()).andReturn().getResponse().getContentAsByteArray()).path("data");
            assertEquals("我用对照实验验证方案", reloaded.path("transcript").get(reloaded.path("transcript").size() - 1).path("answer").asText());
            assertTrue(reloaded.path("review").isEmpty());

            state = resolveInterviewTurn(session, reloaded, "第 " + number + " 题中，你如何控制实验变量？");
            if (number <= 2) {
                assertTrue(state.path("current").path("followUp").asBoolean());
                assertEquals(number, state.path("current").path("number").asInt());
                state = interviewPost(session + "/answer", """
                        {"revision":%s,"requestId":"%s","answer":"我只修改一个变量"}
                        """.formatted(state.path("revision").asInt(), UUID.randomUUID()));
                state = resolveInterviewTurn(session, state, "追问之后不能连续追问");
            }
        }
        assertEquals("FINISHED", state.path("summary").path("status").asText());
        assertEquals(5, state.path("summary").path("answered").asInt());
        assertEquals(2, state.path("summary").path("followUps").asInt());
        assertEquals(5, state.path("review").size());
        assertTrue(state.path("review").findValuesAsText("sourceUrl").stream().anyMatch(url -> url.startsWith("https://")));
        assertEquals(1, state.path("review").get(0).path("question").path("gradingVersion").asInt());
        assertEquals(4, state.path("review").get(0).path("extra").path("evaluation").path("evidence").asInt());

        var answered = state.path("review").get(0).path("question");
        String training = savedId("/api/career/tasks/training", """
                {"requestId":"%s","jobId":"%s","role":"backend"}
                """.formatted(UUID.randomUUID(), job));
        var linked = json.createArrayNode();
        linked.addObject().put("kind", "OPEN").put("id", answered.path("id").asText()).put("version", 1);
        linked.addObject().put("kind", "OPEN").put("id", answered.path("id").asText()).put("version", 2);
        jdbc.update("UPDATE career_task SET status = 'SUCCEEDED', result_json = ? WHERE id = ?",
                json.createObjectNode().set("questions", linked).toString(), training);
        mvc.perform(get("/api/career/tasks/" + training + "/training-progress").header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.length()").value(1))
                .andExpect(jsonPath("$.data[0].version").value(1));
        String review = savedId("/api/career/tasks/review", """
                {"requestId":"%s","planId":"%s"}
                """.formatted(UUID.randomUUID(), training));
        var feedback = json.readTree(jdbc.queryForObject("SELECT context_json FROM career_task WHERE id = ?", String.class, review));
        assertEquals(id, feedback.path("interviewFeedback").get(0).path("sessionId").asText());

        JsonNode next = interviewPost(path, input.replace(requestId, UUID.randomUUID().toString()));
        assertTrue(!prompts.contains(next.path("current").path("prompt").asText()));
    }

    @Test
    void mockInterviewRecoversWhenAnalysisFailsAndPreservesPartialReview() throws Exception {
        String path = "/api/career/interviews";
        var session = interviewPost(path, """
                {"requestId":"%s","jobId":"%s","mode":"VIDEO","count":3}
                """.formatted(UUID.randomUUID(), createWorkflowJob()));
        String endpoint = path + "/" + session.path("summary").path("id").asText();
        session = interviewPost(endpoint + "/answer", """
                {"revision":0,"requestId":"%s","answer":"部分回答"}
                """.formatted(UUID.randomUUID()));
        String taskId = session.path("pending").path("id").asText();
        jdbc.update("UPDATE career_task SET status = 'FAILED', error_message = '模型不可用' WHERE id = ?", taskId);
        String event = "{\"taskId\":\"" + taskId + "\",\"skipFailed\":true}";
        assertEquals("QUEUED", interviewPost(endpoint + "/retry", event).path("pending").path("status").asText());
        jdbc.update("UPDATE career_task SET status = 'FAILED' WHERE id = ?", taskId);
        session = interviewPost(endpoint + "/advance", event);
        assertEquals(2, session.path("current").path("number").asInt());
        session = interviewPost(endpoint + "/status", """
                {"revision":%s,"status":"FINISHED"}
                """.formatted(session.path("revision").asInt()));
        assertEquals(1, session.path("review").size());
        assertTrue(session.path("review").get(0).path("main").path("evaluationUnavailable").asBoolean());
        assertEquals("部分回答", session.path("review").get(0).path("main").path("answer").asText());
    }

    private JsonNode resolveInterviewTurn(String session, JsonNode state, String followUp) throws Exception {
        String taskId = state.path("pending").path("id").asText();
        jdbc.update("UPDATE career_task SET status = 'SUCCEEDED', result_json = ? WHERE id = ?", """
                {"accuracy":3,"evidence":4,"structure":5,"feedback":"补充关键指标","followUp":"%s"}
                """.formatted(followUp), taskId);
        mvc.perform(get("/api/career/tasks/" + taskId).header("Authorization", access(owner)))
                .andExpect(status().isNotFound());
        return interviewPost(session + "/advance", "{\"taskId\":\"" + taskId + "\"}");
    }

    private JsonNode interviewPost(String path, String input) throws Exception {
        var response = mvc.perform(post(path).header("Authorization", access(owner)).contentType("application/json")
                .content(input)).andExpect(status().isOk()).andReturn().getResponse();
        return json.readTree(response.getContentAsByteArray()).path("data");
    }

    @Test
    void checkpointsAcceptOnlySelectedReferencesAndExposeOnlyOwnersEvents() throws Exception {
        String job = createWorkflowJob();
        String document = UUID.randomUUID().toString();
        String task = savedId("/api/career/tasks/preparation", """
                {"jobId":"%s","requestId":"%s","documentIds":["%s"]}
                """.formatted(job, UUID.randomUUID(), document));
        String memory = JOBS + "/" + job + "/memory";
        mvc.perform(put(memory).header("Authorization", access(owner)).contentType("application/json")
                .content("{\"revision\":0,\"notes\":\"每天复习 30 分钟\"}")).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.revision").value(1));
        mvc.perform(get(memory).header("Authorization", access(other))).andExpect(status().isNotFound());
        mvc.perform(put(memory).header("Authorization", access(owner)).contentType("application/json")
                .content("{\"revision\":0,\"notes\":null}")).andExpect(status().isConflict());
        mvc.perform(put(memory).header("Authorization", access(owner)).contentType("application/json")
                .content("{\"revision\":1,\"notes\":null}")).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.revision").value(2));
        String lease = UUID.randomUUID().toString();
        jdbc.update("""
                UPDATE career_task SET status = 'RUNNING', generation = 1, lease_token = ?,
                    lease_until = DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 120 SECOND) WHERE id = ?
                """, lease, task);
        String tool = "/internal/career/tasks/" + task;
        String input = """
                {"payload":{"job":{"label":"目标岗位"}},"references":[{"id":"%s","title":"备考资料",
                 "revision":"%s"}],"skill":{"id":"preparation","version":1,"instructions":"生成模拟题"}}
                """.formatted(document, "a".repeat(64));
        mvc.perform(put(tool + "/context").header("X-Career-Service", "integration-test-service-token")
                .header("X-Career-Lease", lease).contentType("application/json")
                .content(input.replace(document, UUID.randomUUID().toString()))).andExpect(status().isBadRequest());
        mvc.perform(put(tool + "/context").header("X-Career-Service", "integration-test-service-token")
                .header("X-Career-Lease", lease).contentType("application/json").content(input)).andExpect(status().isOk());
        mvc.perform(put(tool + "/context").header("X-Career-Service", "integration-test-service-token")
                .header("X-Career-Lease", lease).contentType("application/json")
                .content(input.replace("目标岗位", "其他岗位"))).andExpect(status().isConflict());
        String event = """
                {"sequenceNo":1,"step":"assemble_context","outcome":"succeeded","elapsedMs":20}
                """;
        for (int i = 0; i < 2; i++) {
            mvc.perform(post(tool + "/events").header("X-Career-Service", "integration-test-service-token")
                    .header("X-Career-Lease", lease).contentType("application/json").content(event))
                    .andExpect(status().isOk());
        }
        mvc.perform(get("/api/career/tasks/" + task + "/events").header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.length()").value(1))
                .andExpect(jsonPath("$.data[0].step").value("assemble_context"));
        mvc.perform(get("/api/career/tasks/" + task + "/events").header("Authorization", access(other)))
                .andExpect(status().isNotFound());
    }

    @Test
    void activeJobAndObjectivePracticeStayScopedToOwnerAndJob() throws Exception {
        String first = createWorkflowJob();
        String second = createWorkflowJob();
        String active = JOBS + "/active";
        String input = "{\"jobId\":\"" + first + "\"}";
        mvc.perform(put(active).header("Authorization", access(other)).contentType("application/json").content(input))
                .andExpect(status().isNotFound());
        mvc.perform(put(active).header("Authorization", access(owner)).contentType("application/json").content(input))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.jobId").value(first));
        mvc.perform(get(active).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.jobId").value(first));
        String attempt = """
                {"requestId":"%s","questionId":"%s","questionVersion":1,"answer":"A","jobId":"%s"}
                """.formatted(UUID.randomUUID(), HASHCODE, first);
        mvc.perform(post(ATTEMPTS).header("Authorization", access(other)).contentType("application/json").content(attempt))
                .andExpect(status().isNotFound());
        mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json").content(attempt))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.jobId").value(first));
        mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json")
                        .content(attempt.replace(first, second))).andExpect(status().isConflict());
        mvc.perform(get(ATTEMPTS).param("jobId", first).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.items.length()").value(1));
        mvc.perform(get(ATTEMPTS).param("jobId", second).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.items.length()").value(0));
        mvc.perform(delete(JOBS + "/" + first).header("Authorization", access(owner))).andExpect(status().isOk());
        mvc.perform(get(active).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.jobId").isEmpty());
        mvc.perform(get(ATTEMPTS).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.items.length()").value(1));
    }

    @Test
    void generatedQuestionsSupportAnUnseededRoleWithoutCrossingJobOrUser() throws Exception {
        String job = savedId(JOBS, """
                {"company":"山野观察","title":"湿地生态修复","description":"监测候鸟栖息地与水文条件",
                 "skills":"水质采样","sourceName":"企业官网","sourcedOn":"2026-11-12"}
                """);
        String otherJob = createWorkflowJob();
        String root = "/api/career/tasks";
        String input = """
                {"jobId":"%s","requestId":"%s"}
                """.formatted(job, UUID.randomUUID());
        mvc.perform(get("/api/career/recommendations").param("jobId", job).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.questions.length()").value(0))
                .andExpect(jsonPath("$.data.notes.length()").value(0));
        mvc.perform(post(root + "/training").header("Authorization", access(owner)).contentType("application/json")
                        .content(input)).andExpect(status().isConflict());
        String preparation = savedId(root + "/preparation", input);
        jdbc.update("UPDATE career_task SET status = 'SUCCEEDED', result_json = ? WHERE id = ?", """
                {"skills":["水质采样"],"openQuestions":[{"topic":"栖息地监测","prompt":"如何评估修复结果？",
                    "rubric":["设置基线","说明采样间隔"]}]}
                """, preparation);
        mvc.perform(get(root).param("kind", "PREPARATION").param("jobId", otherJob).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.items.length()").value(0));
        mvc.perform(get(root + "/" + preparation).header("Authorization", access(other))).andExpect(status().isNotFound());
        String answer = """
                {"jobId":"%s","requestId":"%s","questionId":"%s-0","questionVersion":1,"answer":"记录水质基线"}
                """.formatted(job, UUID.randomUUID(), preparation);
        mvc.perform(post(root + "/interview").header("Authorization", access(owner)).contentType("application/json")
                        .content(answer.replace(job, otherJob))).andExpect(status().isNotFound());
        String interview = savedId(root + "/interview", answer);
        mvc.perform(get(root + "/" + interview).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data.interview.prompt").value("如何评估修复结果？"));
        String training = """
                {"jobId":"%s","requestId":"%s","preparationId":"%s","preferredQuestion":"%s-0"}
                """.formatted(job, UUID.randomUUID(), preparation, preparation);
        mvc.perform(post(root + "/training").header("Authorization", access(owner)).contentType("application/json")
                .content(training.replace(preparation + "-0", otherJob + "-0"))).andExpect(status().isBadRequest());
        mvc.perform(post(root + "/training").header("Authorization", access(owner)).contentType("application/json")
                .content(training.replace(preparation + "-0", preparation + "-1"))).andExpect(status().isNotFound());
        String trainingId = savedId(root + "/training", training);
        mvc.perform(get(root + "/" + trainingId).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data.request.preferredQuestion").value(preparation + "-0"));
        String progress = root + "/" + trainingId + "/training-progress";
        mvc.perform(get(progress).header("Authorization", access(owner))).andExpect(status().isConflict());
        jdbc.update("UPDATE career_task SET status = 'SUCCEEDED', result_json = ? WHERE id = ?", """
                {"questions":[{"id":"%s-0","version":1,"kind":"OPEN"},{"id":"%s","version":1}]}
                """.formatted(preparation, HASHCODE), trainingId);
        mvc.perform(get(progress).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data").isEmpty());
        jdbc.update("UPDATE career_task SET status = 'SUCCEEDED' WHERE id = ?", interview);
        mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json")
                        .content("""
                                {"requestId":"%s","questionId":"%s","questionVersion":1,"answer":"A","jobId":"%s"}
                                """.formatted(UUID.randomUUID(), HASHCODE, otherJob))).andExpect(status().isOk());
        mvc.perform(get(progress).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data.length()").value(1)).andExpect(jsonPath("$.data[0].id").value(preparation + "-0"));
        for (int i = 0; i < 2; i++) {
            mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json")
                            .content("""
                                    {"requestId":"%s","questionId":"%s","questionVersion":1,"answer":"A","jobId":"%s"}
                                    """.formatted(UUID.randomUUID(), HASHCODE, job))).andExpect(status().isOk());
        }
        mvc.perform(get(progress).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data.length()").value(2)).andExpect(jsonPath("$.data[0].id").value(HASHCODE));
        mvc.perform(get(progress).header("Authorization", access(other))).andExpect(status().isNotFound());
    }

    @Test
    void trainingRequestIsDurableIdempotentAndOwnerScoped() throws Exception {
        String job = createWorkflowJob();
        createWorkflowFact(true);
        String request = UUID.randomUUID().toString();
        String input = """
                {"jobId":"%s","requestId":"%s","role":"backend"}
                """.formatted(job, request);
        String path = "/api/career/tasks/training";
        String task = savedId(path, input);
        assertEquals(task, savedId(path, input));
        mvc.perform(post(path).header("Authorization", access(owner)).contentType("application/json")
                        .content(input.replace("backend", "algorithm"))).andExpect(status().isConflict());
        mvc.perform(get("/api/career/tasks/" + task).header("Authorization", access(other)))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/career/tasks").param("kind", "TRAINING").header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.items.length()").value(1))
                .andExpect(jsonPath("$.data.items[0].status").value("QUEUED"))
                .andExpect(jsonPath("$.data.items[0].lease").doesNotExist())
                .andExpect(jsonPath("$.data.items[0].context").doesNotExist());
    }

    @Test
    void trainingCheckpointsSurviveNewLeaseAndRejectConflictingWrites() throws Exception {
        String job = createWorkflowJob();
        createWorkflowFact(true);
        String task = savedId("/api/career/tasks/training", """
                {"jobId":"%s","requestId":"%s","role":"backend"}
                """.formatted(job, UUID.randomUUID()));
        String tools = "/internal/career/tasks/" + task;
        String expired = UUID.randomUUID().toString();
        jdbc.update("""
                UPDATE career_task SET status = 'RUNNING', generation = 1, lease_token = ?,
                    lease_until = DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 120 SECOND) WHERE id = ?
                """, expired, task);
        String plan = """
                {"analysis":"分析","steps":["步骤"],"questions":[{"id":"%s","version":1}]}
                """.formatted(HASHCODE);
        mvc.perform(put(tools + "/plan").header("X-Career-Service", "integration-test-service-token")
                        .header("X-Career-Lease", expired).contentType("application/json").content(plan))
                .andExpect(status().isConflict());
        var catalog = mvc.perform(put(tools + "/questions").header("X-Career-Service", "integration-test-service-token")
                        .header("X-Career-Lease", expired)).andExpect(status().isOk())
                .andExpect(jsonPath("$[0].correctAnswer").doesNotExist()).andReturn().getResponse().getContentAsString();
        String lease = UUID.randomUUID().toString();
        jdbc.update("""
                UPDATE career_task SET generation = 2, lease_token = ?,
                    lease_until = DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 120 SECOND) WHERE id = ?
                """, lease, task);
        mvc.perform(put(tools + "/questions").header("X-Career-Service", "wrong-token")
                        .header("X-Career-Lease", lease)).andExpect(status().isUnauthorized());
        var resumedCatalog = mvc.perform(put(tools + "/questions").header("X-Career-Service", "integration-test-service-token")
                        .header("X-Career-Lease", lease)).andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        assertEquals(json.readTree(catalog), json.readTree(resumedCatalog));
        mvc.perform(put(tools + "/plan").header("X-Career-Service", "integration-test-service-token")
                        .header("X-Career-Lease", expired).contentType("application/json").content(plan))
                .andExpect(status().isConflict());
        mvc.perform(put(tools + "/plan").header("X-Career-Service", "integration-test-service-token")
                        .header("X-Career-Lease", lease).contentType("application/json").content(plan.replace("1}", "999}")))
                .andExpect(status().isBadRequest());
        mvc.perform(put(tools + "/plan").header("X-Career-Service", "integration-test-service-token")
                        .header("X-Career-Lease", lease).contentType("application/json").content(plan))
                .andExpect(status().isOk());
        mvc.perform(put(tools + "/plan").header("X-Career-Service", "integration-test-service-token")
                        .header("X-Career-Lease", lease).contentType("application/json").content(plan))
                .andExpect(status().isOk());
        mvc.perform(put(tools + "/plan").header("X-Career-Service", "integration-test-service-token")
                        .header("X-Career-Lease", lease).contentType("application/json").content(plan.replace("分析", "不同分析")))
                .andExpect(status().isConflict());
        mvc.perform(get("/api/career/tasks/" + task).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.status").value("RUNNING"))
                .andExpect(jsonPath("$.data.generation").value(2))
                .andExpect(jsonPath("$.data.trainingStep").value("SAVE_PLAN"))
                .andExpect(jsonPath("$.data.result").isEmpty());
        assertEquals(1, jdbc.queryForObject("""
                SELECT COUNT(*) FROM career_task WHERE id = ? AND training_catalog_at IS NOT NULL
                    AND training_draft_at IS NOT NULL AND JSON_LENGTH(training_draft_json, '$.questions') = 1
                """, Integer.class, task));
    }

    @Test
    void resumeSnapshotsConfirmedFactsAndApplicationsProtectMaterialsAndStages() throws Exception {
        String job = createWorkflowJob();
        String fact = createWorkflowFact(true);
        String unconfirmed = createWorkflowFact(false);
        String resumes = "/api/career/resumes";
        String applications = "/api/career/applications";
        String input = """
                {"jobId":"%s","requestId":"%s","experienceIds":["%s"]}
                """.formatted(job, UUID.randomUUID(), fact);
        mvc.perform(post(resumes).header("Authorization", access(owner)).contentType("application/json")
                        .content(input.replace(fact, unconfirmed))).andExpect(status().isBadRequest());
        String resume = savedId(resumes, input);
        assertEquals(resume, savedId(resumes, input));
        String replacement = savedId(resumes, input.replace(json.readTree(input).path("requestId").asText(), UUID.randomUUID().toString()));
        jdbc.update("UPDATE career_experience SET description = 'changed', confirmed = FALSE WHERE id = ?", fact);
        mvc.perform(get(resumes).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data[0].evidence[0].description").value("真实项目"));
        mvc.perform(get(resumes).header("Authorization", access(other)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.length()").value(0));

        String differentJob = createWorkflowJob();
        mvc.perform(post(applications).header("Authorization", access(owner)).contentType("application/json")
                        .content("""
                                {"jobId":"%s","resumeId":"%s"}
                                """.formatted(differentJob, resume))).andExpect(status().isBadRequest());
        String draft = """
                {"jobId":"%s","resumeId":"%s","answers":"可以实习三个月"}
                """.formatted(job, resume);
        String application = savedId(applications, draft);
        assertEquals(application, savedId(applications, draft));
        String stage = applications + "/" + application + "/stage";
        String change = """
                {"stage":"SUBMITTED","revision":1,"note":"官网已人工提交"}
                """;
        mvc.perform(post(stage).header("Authorization", access(other)).contentType("application/json").content(change))
                .andExpect(status().isNotFound());
        mvc.perform(post(stage).header("Authorization", access(owner)).contentType("application/json").content(change))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.revision").value(2));
        mvc.perform(post(stage).header("Authorization", access(owner)).contentType("application/json").content(change))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.revision").value(2));
        mvc.perform(put(applications + "/" + application).header("Authorization", access(owner))
                        .contentType("application/json").content("{\"revision\":1,\"answers\":\"stale\"}"))
                .andExpect(status().isConflict());
        mvc.perform(get(applications + "/" + application + "/events").header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.length()").value(2))
                .andExpect(jsonPath("$.data[0].note").value("官网已人工提交"))
                .andExpect(jsonPath("$.data[0].materials.resumeId").value(resume));
        mvc.perform(put(applications + "/" + application).header("Authorization", access(owner))
                .contentType("application/json").content("""
                        {"revision":2,"resumeId":"%s","answers":"可以实习四个月"}
                        """.formatted(replacement))).andExpect(status().isOk());
        mvc.perform(get(applications + "/" + application + "/events").header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.length()").value(3))
                .andExpect(jsonPath("$.data[0].eventType").value("MATERIALS_UPDATED"))
                .andExpect(jsonPath("$.data[0].materials.resumeId").value(replacement))
                .andExpect(jsonPath("$.data[1].materials.resumeId").value(resume))
                .andExpect(jsonPath("$.data[1].materials.answers").value("可以实习三个月"));
    }

    @Test
    void applicationWorkspaceKeepsLegacyNotesAndPrivateFilesInSubmissionHistory() throws Exception {
        String job = createWorkflowJob();
        String root = "/api/career/applications";
        String application = savedId(root, """
                {"jobId":"%s","answers":"原来的答案草稿"}
                """.formatted(job));
        String workspace = JOBS + "/" + job + "/application-workspace";
        mvc.perform(get(workspace).header("Authorization", access(owner))).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.application.answers").value("原来的答案草稿"));
        mvc.perform(get(workspace).header("Authorization", access(other))).andExpect(status().isNotFound());

        String fileId = UUID.randomUUID().toString();
        String itemId = UUID.randomUUID().toString();
        byte[] pdf = "%PDF-1.4\nfixture".getBytes(StandardCharsets.US_ASCII);
        String request = """
                {"requestId":"%s","revision":1,"answers":"原来的答案草稿","content":{
                  "form":{"name":"林同学","startDate":"2026-12-01","weeklyDays":4,"questions":[]},
                  "attachments":[{"id":"%s","kind":"FILE","label":"成绩单","required":true,"fileId":"%s"}]
                }}
                """.formatted(UUID.randomUUID(), itemId, fileId);
        var input = new MockMultipartFile("draft", "", "application/json", request.getBytes(StandardCharsets.UTF_8));
        var document = new MockMultipartFile(fileId, "Transcript.pdf", "application/pdf", pdf);
        for (int repeat = 0; repeat < 2; repeat++) {
            mvc.perform(multipart(HttpMethod.PUT, workspace).file(input).file(document).header("Authorization", access(owner)))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.data.application.revision").value(2))
                    .andExpect(jsonPath("$.data.workspace.files[0].name").value("Transcript.pdf"))
                    .andExpect(jsonPath("$.data.workspace.content.form.weeklyDays").value(4));
        }
        var altered = new MockMultipartFile(fileId, "Transcript.pdf", "application/pdf", "%PDF-1.4\nchanged".getBytes(StandardCharsets.US_ASCII));
        mvc.perform(multipart(HttpMethod.PUT, workspace).file(input).file(altered).header("Authorization", access(owner)))
                .andExpect(status().isConflict());
        String download = root + "/" + application + "/files/" + fileId;
        mvc.perform(get(download).header("Authorization", access(owner))).andExpect(status().isOk())
                .andExpect(header().exists("Content-Disposition")).andExpect(content().bytes(pdf));
        mvc.perform(get(download).header("Authorization", access(other))).andExpect(status().isNotFound());

        String stage = root + "/" + application + "/stage";
        String receipt = """
                {"stage":"SUBMITTED","revision":2,
                 "receipt":{"submittedAt":"2026-11-16T03:30:00Z","applicationNumber":"A-010"}}
                """;
        for (int repeat = 0; repeat < 2; repeat++) {
            mvc.perform(post(stage).header("Authorization", access(owner)).contentType("application/json").content(receipt))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.data.revision").value(3));
        }
        mvc.perform(get(workspace).header("Authorization", access(owner))).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.receipt.applicationNumber").value("A-010"));

        String revision = """
                {"requestId":"%s","revision":3,"answers":"新草稿","content":{"form":{"questions":[]},"attachments":[]}}
                """.formatted(UUID.randomUUID());
        mvc.perform(multipart(HttpMethod.PUT, workspace).file(new MockMultipartFile("draft", "", "application/json",
                        revision.getBytes(StandardCharsets.UTF_8))).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.workspace.files.length()").value(0));
        mvc.perform(get(download).header("Authorization", access(owner))).andExpect(status().isOk()).andExpect(content().bytes(pdf));
        mvc.perform(get(root + "/" + application + "/events").header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.length()").value(3))
                .andExpect(jsonPath("$.data[1].receipt.applicationNumber").value("A-010"))
                .andExpect(jsonPath("$.data[1].materials.answers").value("原来的答案草稿"))
                .andExpect(jsonPath("$.data[1].materials.workspace.files[0].id").value(fileId));
    }

    @Test
    void composedResumeKeepsItsLayoutAndFactsAndUsesOwnerAndJobScope() throws Exception {
        String profile = "/api/career/resume-profile";
        String versionPath = "/api/career/resumes/composed";
        String job = createWorkflowJob();
        var bytes = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(24, 32, BufferedImage.TYPE_INT_RGB), "png", bytes);
        String photo = "data:image/png;base64," + Base64.getEncoder().encodeToString(bytes.toByteArray());
        String input = """
                {"revision":0,"content":{"name":"林同学","phone":"","email":"","targetRole":"","skills":"Java",
                 "photo":"%s","showPhoto":false,"template":"modern","entries":[{"id":"%s","kind":"award",
                 "title":"学业奖学金","organization":"学校","role":"","startMonth":"2026-01","endMonth":"","description":""}]}}
                """.formatted(photo, UUID.randomUUID());
        mvc.perform(put(profile).header("Authorization", access(owner)).contentType("application/json")
                .content(input.replace(photo, "data:image/png;base64,AAAA"))).andExpect(status().isBadRequest());
        mvc.perform(put(profile).header("Authorization", access(owner)).contentType("application/json")
                .content(input)).andExpect(status().isOk()).andExpect(jsonPath("$.data.revision").value(1));
        mvc.perform(get(profile).header("Authorization", access(other))).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.revision").value(0)).andExpect(jsonPath("$.data.content.name").value(""));

        String request = """
                {"jobId":"%s","requestId":"%s","revision":1}
                """.formatted(job, UUID.randomUUID());
        String id = savedId(versionPath, request);
        assertEquals(id, savedId(versionPath, request));
        String general = savedId(versionPath, """
                {"requestId":"%s","revision":1}
                """.formatted(UUID.randomUUID()));
        mvc.perform(post("/api/career/applications").header("Authorization", access(owner)).contentType("application/json")
                .content("{\"jobId\":\"" + job + "\",\"resumeId\":\"" + general + "\"}")).andExpect(status().isBadRequest());
        String draft = savedId("/api/career/applications", "{\"jobId\":\"" + job + "\",\"resumeId\":\"" + id + "\"}");
        mvc.perform(get("/api/career/applications/" + draft + "/events").header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data[0].stage").value("DRAFT"));
        mvc.perform(put(profile).header("Authorization", access(owner)).contentType("application/json")
                .content(input.replace("林同学", "新姓名"))).andExpect(status().isConflict());
        mvc.perform(put(profile).header("Authorization", access(owner)).contentType("application/json")
                .content(input.replace("\"revision\":0", "\"revision\":1").replace("林同学", "新姓名")))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.revision").value(2));
        assertEquals(id, savedId(versionPath, request));
        String composition = "/api/career/resumes/" + id + "/composition";
        mvc.perform(get(composition).header("Authorization", access(owner))).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("林同学")).andExpect(jsonPath("$.data.template").value("modern"))
                .andExpect(jsonPath("$.data.targetRole").value("Java 开发"))
                .andExpect(jsonPath("$.data.entries[0].title").value("学业奖学金"))
                .andExpect(jsonPath("$.data.photo").isEmpty());
        mvc.perform(get(composition).header("Authorization", access(other))).andExpect(status().isNotFound());
    }

    @Test
    void resumeExperienceReachesTrainingOnlyAfterExplicitConfirmation() throws Exception {
        String profile = "/api/career/resume-profile";
        String entryId = UUID.randomUUID().toString();
        String content = """
                {"name":"","phone":"","email":"","targetRole":"","skills":"","photo":null,"showPhoto":true,
                 "template":"classic","entries":[{"id":"%s","kind":"project","title":"检索助手",
                 "organization":"","role":"后端开发","startMonth":"2026-01","endMonth":"","description":"实现原文回链",
                 "sourceNote":"项目记录"}]}
                """.formatted(entryId);
        mvc.perform(put(profile).header("Authorization", access(owner)).contentType("application/json")
                .content("{\"revision\":0,\"content\":" + content + "}")).andExpect(status().isOk());
        mvc.perform(get(EXPERIENCES).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data").isEmpty());

        String confirm = "{\"revision\":1,\"content\":" + content + ",\"confirmExperienceId\":\"" + entryId + "\"}";
        mvc.perform(put(profile).header("Authorization", access(owner)).contentType("application/json").content(confirm))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.revision").value(1));
        mvc.perform(put(profile).header("Authorization", access(owner)).contentType("application/json").content(confirm))
                .andExpect(status().isOk());
        mvc.perform(get(EXPERIENCES).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data.length()").value(1)).andExpect(jsonPath("$.data[0].id").value(entryId))
                .andExpect(jsonPath("$.data[0].confirmed").value(true))
                .andExpect(jsonPath("$.data[0].sourceNote").value("项目记录"));

        mvc.perform(put(profile).header("Authorization", access(other)).contentType("application/json")
                .content(confirm.replace("\"revision\":1", "\"revision\":0"))).andExpect(status().isNotFound());
        mvc.perform(get(profile).header("Authorization", access(other))).andExpect(jsonPath("$.data.revision").value(0));
        mvc.perform(put(profile).header("Authorization", access(owner)).contentType("application/json")
                .content("{\"revision\":1,\"content\":" + content.replace("实现原文回链", "简历专用表述") + "}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.revision").value(2));

        String task = savedId("/api/career/tasks/training", """
                {"jobId":"%s","role":"backend","requestId":"%s"}
                """.formatted(createWorkflowJob(), UUID.randomUUID()));
        var facts = json.readTree(jdbc.queryForObject("SELECT context_json FROM career_task WHERE id = ?",
                String.class, task)).path("experiences");
        assertEquals(entryId, facts.get(0).path("id").asText());
        assertEquals("担任角色：后端开发\n实现原文回链", facts.get(0).path("description").asText());
    }

    private String createWorkflowJob() throws Exception {
        return savedId(JOBS, """
                {"company":"测试公司","title":"Java 开发","description":"维护服务",
                 "sourceName":"企业官网","sourceUrl":"https://example.com/jobs","sourcedOn":"2026-11-06"}
                """);
    }

    private String createWorkflowFact(boolean confirmed) throws Exception {
        return savedId(EXPERIENCES, """
                {"type":"project","title":"课程项目","description":"真实项目","confirmed":%s}
                """.formatted(confirmed));
    }

    private String savedId(String path, String input) throws Exception {
        var response = mvc.perform(post(path).header("Authorization", access(owner)).contentType("application/json")
                        .content(input)).andExpect(status().is2xxSuccessful()).andReturn().getResponse();
        return json.readTree(response.getContentAsByteArray()).path("data").path("id").asText();
    }

    @Test
    void requiresSignedUnexpiredAccessTokenWithUuidSubject() throws Exception {
        Instant future = Instant.now().plusSeconds(600);
        mvc.perform(get("/api/career/health"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.components.db.status").value("UP"));
        mvc.perform(get(PROFILE)).andExpect(status().isUnauthorized());
        for (String invalid : new String[]{
                sign(owner, "refresh", future, TEST_SECRET),
                sign(owner, "access", Instant.now().minusSeconds(30), TEST_SECRET),
                sign(owner, "access", null, TEST_SECRET),
                sign("not-a-user-uuid", "access", future, TEST_SECRET),
                sign(owner, "access", future, "different-signing-key-at-least-32-bytes")
        }) {
            mvc.perform(get(PROFILE).header("Authorization", invalid)).andExpect(status().isUnauthorized());
        }
        mvc.perform(get(PROFILE).header("Authorization", access(owner))).andExpect(status().isOk());
    }

    @Test
    void profileKeepsOwnerAndUpdatesExistingV1Row() throws Exception {
        mvc.perform(get(PROFILE).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data").isEmpty());
        jdbc.update("INSERT INTO career_profile (user_id) VALUES (?)", owner);
        String input = """
                {"targetRole":"Java 后端","graduationMonth":"2027-06","preferences":"上海","user_id":"%s"}
                """.formatted(other);
        mvc.perform(put(PROFILE).header("Authorization", access(owner)).contentType("application/json").content(input))
                .andExpect(status().isOk());
        mvc.perform(get(PROFILE).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data.targetRole").value("Java 后端"))
                .andExpect(jsonPath("$.data.graduationMonth").value("2027-06"))
                .andExpect(jsonPath("$.data.preferences").value("上海"));
        mvc.perform(get(PROFILE).header("Authorization", access(other)).param("user_id", owner))
                .andExpect(jsonPath("$.data").isEmpty());
        mvc.perform(put(PROFILE).header("Authorization", access(owner)).contentType("application/json")
                        .content("{\"targetRole\":\"算法工程师\"}"))
                .andExpect(status().isOk());
        mvc.perform(get(PROFILE).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data.targetRole").value("算法工程师"))
                .andExpect(jsonPath("$.data.graduationMonth").isEmpty());
    }

    @Test
    void experiencesPersistConfirmationAndAreIsolated() throws Exception {
        String input = """
                {"type":"research","title":"课题","organization":"实验室","startMonth":"2025-06",
                 "endMonth":"2026-01","description":"复现实验结果","sourceNote":"实验日志","confirmed":true}
                """;
        mvc.perform(post(EXPERIENCES).header("Authorization", access(owner)).contentType("application/json")
                        .content(input.replace("2026-01", "2024-01")))
                .andExpect(status().isBadRequest());
        String id = assertOwnerCrud(EXPERIENCES, input, input.replace("true", "false"));
        mvc.perform(get(EXPERIENCES).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data[0].id").value(id))
                .andExpect(jsonPath("$.data[0].confirmed").value(false))
                .andExpect(jsonPath("$.data[0].sourceNote").value("实验日志"));
        assertDelete(EXPERIENCES, id);
    }

    @Test
    void jobsPersistJdAndProvenanceAndAreIsolated() throws Exception {
        String input = """
                {"company":"示例公司","title":"算法实习","location":"上海","description":"负责模型评估",
                 "sourceName":"校招官网","sourceUrl":"https://example.com/careers","sourcedOn":"2026-11-06"}
                """;
        mvc.perform(post(JOBS).header("Authorization", access(owner)).contentType("application/json")
                        .content(input.replace("https://example.com/careers", "javascript:alert(1)")))
                .andExpect(status().isBadRequest());
        String id = assertOwnerCrud(JOBS, input, input.replace("算法实习", "算法工程师"));
        mvc.perform(get(JOBS).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data[0].id").value(id))
                .andExpect(jsonPath("$.data[0].company").value("示例公司"))
                .andExpect(jsonPath("$.data[0].title").value("算法工程师"))
                .andExpect(jsonPath("$.data[0].description").value("负责模型评估"))
                .andExpect(jsonPath("$.data[0].sourceName").value("校招官网"))
                .andExpect(jsonPath("$.data[0].sourceUrl").value("https://example.com/careers"))
                .andExpect(jsonPath("$.data[0].sourcedOn").value("2026-11-06"));
        assertDelete(JOBS, id);
    }

    @Test
    void exposesSourcedCatalogWithoutAnswerKeys() throws Exception {
        mvc.perform(get(QUESTIONS)).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/career/interview-notes").header("Authorization", access(owner)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].sourceUrl").isNotEmpty())
                .andExpect(jsonPath("$.data[0].publishedOn").value("2022-05-18"))
                .andExpect(jsonPath("$.data[0].sourcedOn").isNotEmpty());
        mvc.perform(get(QUESTIONS).header("Authorization", access(owner)).param("role", "algorithm"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.length()").value(2))
                .andExpect(jsonPath("$.data[0].role").value("algorithm"))
                .andExpect(jsonPath("$.data[1].role").value("algorithm"))
                .andExpect(jsonPath("$.data[0].sourceUrl").isNotEmpty())
                .andExpect(jsonPath("$.data[0].correctAnswer").doesNotExist());
        mvc.perform(get(QUESTIONS + "/" + HASHCODE).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.options.length()").value(4))
                .andExpect(jsonPath("$.data.correctAnswer").doesNotExist())
                .andExpect(jsonPath("$.data.explanation").doesNotExist());
    }

    @Test
    void gradesAndPersistsWrongQuestionsAcrossRetriesAndUsers() throws Exception {
        String request = UUID.randomUUID().toString();
        String wrong = answer(request, HASHCODE, 1, "A");
        mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json")
                        .content(answer(request, HASHCODE, 1, "X")))
                .andExpect(status().isBadRequest());
        mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json")
                        .content(answer(request, HASHCODE, 99, "A")))
                .andExpect(status().isNotFound());

        var start = new CountDownLatch(1);
        Callable<String> submit = () -> {
            start.await();
            return mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json").content(wrong))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.correct").value(false))
                    .andExpect(jsonPath("$.data.correctAnswer").value("B"))
                    .andExpect(jsonPath("$.data.questionVersion").value(1))
                    .andExpect(jsonPath("$.data.gradingVersion").value(1))
                    .andReturn().getResponse().getContentAsString();
        };
        try (var pool = Executors.newFixedThreadPool(2)) {
            var first = pool.submit(submit);
            var second = pool.submit(submit);
            start.countDown();
            assertEquals(first.get(10, TimeUnit.SECONDS), second.get(10, TimeUnit.SECONDS));
        }

        mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json")
                        .content(answer(request, HASHCODE, 1, "B")))
                .andExpect(status().isConflict());
        mvc.perform(get(ATTEMPTS).header("Authorization", access(owner)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.items.length()").value(1));
        mvc.perform(get(WRONG).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data[0].questionId").value(HASHCODE))
                .andExpect(jsonPath("$.data[0].wrongCount").value(1))
                .andExpect(jsonPath("$.data[0].reviewed").value(false));
        mvc.perform(get(ATTEMPTS).header("Authorization", access(other)).param("user_id", owner))
                .andExpect(jsonPath("$.data.items").isEmpty());
        mvc.perform(get(WRONG).header("Authorization", access(other)))
                .andExpect(jsonPath("$.data").isEmpty());

        mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json")
                        .content(answer(UUID.randomUUID().toString(), HASHCODE, 1, "B")))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.correct").value(true));
        mvc.perform(get(WRONG).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data[0].wrongCount").value(1))
                .andExpect(jsonPath("$.data[0].reviewed").value(true));
        mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json")
                        .content(answer(UUID.randomUUID().toString(), HASHCODE, 1, "D")))
                .andExpect(status().isOk());
        mvc.perform(get(WRONG).header("Authorization", access(owner)))
                .andExpect(jsonPath("$.data[0].wrongCount").value(2))
                .andExpect(jsonPath("$.data[0].reviewed").value(false));
    }

    @Test
    void historyReadsOriginalQuestionAndGradingRuleAfterNewVersion() throws Exception {
        String questionId = "test-" + UUID.randomUUID();
        String insert = """
                INSERT INTO career_question_version
                    (id, version, grading_version, role, topic, prompt, option_a, option_b, option_c, option_d,
                     correct_answer, explanation, source_name, source_url, sourced_on)
                SELECT ?, ?, ?, role, topic, ?, option_a, option_b, option_c, option_d,
                       ?, explanation, source_name, source_url, sourced_on
                FROM career_question_version WHERE id = ? AND version = 1
                """;
        try {
            jdbc.update(insert, questionId, 1, 1, "原题干", "B", HASHCODE);
            mvc.perform(post(ATTEMPTS).header("Authorization", access(owner)).contentType("application/json")
                            .content(answer(UUID.randomUUID().toString(), questionId, 1, "B")))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.data.correct").value(true));
            jdbc.update(insert, questionId, 2, 3, "新题干", "A", HASHCODE);
            mvc.perform(get(QUESTIONS + "/" + questionId).header("Authorization", access(owner)))
                    .andExpect(jsonPath("$.data.version").value(2))
                    .andExpect(jsonPath("$.data.prompt").value("新题干"));
            mvc.perform(get(ATTEMPTS).header("Authorization", access(owner)))
                    .andExpect(jsonPath("$.data.items[0].questionVersion").value(1))
                    .andExpect(jsonPath("$.data.items[0].gradingVersion").value(1))
                    .andExpect(jsonPath("$.data.items[0].prompt").value("原题干"))
                    .andExpect(jsonPath("$.data.items[0].correctAnswer").value("B"));
        } finally {
            jdbc.update("""
                DELETE e FROM career_application_event e JOIN career_application a ON a.id = e.application_id
                WHERE a.user_id IN (?, ?)
                """, owner, other);
        jdbc.update("DELETE FROM career_application WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_resume_version WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_task WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_practice_attempt WHERE user_id = ? AND question_id = ?", owner, questionId);
            jdbc.update("DELETE FROM career_question_version WHERE id = ?", questionId);
        }
    }

    private String answer(String requestId, String questionId, int version, String choice) {
        return """
                {"requestId":"%s","questionId":"%s","questionVersion":%d,"answer":"%s","correct":true,"user_id":"%s"}
                """.formatted(requestId, questionId, version, choice, other);
    }

    private String assertOwnerCrud(String path, String input, String update) throws Exception {
        String own = access(owner);
        String foreign = access(other);
        String response = mvc.perform(post(path).header("Authorization", own)
                        .contentType("application/json").content(input))
                .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        String id = json.readTree(response).get("data").get("id").asText();
        String itemPath = path + "/" + id;
        mvc.perform(get(path).header("Authorization", foreign).param("user_id", owner))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data").isEmpty());
        mvc.perform(get(itemPath).header("Authorization", foreign)).andExpect(status().isNotFound());
        mvc.perform(put(itemPath).header("Authorization", foreign).contentType("application/json").content(update))
                .andExpect(status().isNotFound());
        mvc.perform(delete(itemPath).header("Authorization", foreign)).andExpect(status().isNotFound());
        mvc.perform(get(itemPath).header("Authorization", own)).andExpect(status().isOk());
        mvc.perform(put(itemPath).header("Authorization", own).contentType("application/json").content(update))
                .andExpect(status().isOk());
        return id;
    }

    private void assertDelete(String path, String id) throws Exception {
        String itemPath = path + "/" + id;
        mvc.perform(delete(itemPath).header("Authorization", access(owner))).andExpect(status().isOk());
        mvc.perform(get(itemPath).header("Authorization", access(owner))).andExpect(status().isNotFound());
        mvc.perform(get(path).header("Authorization", access(owner))).andExpect(jsonPath("$.data").isEmpty());
    }

    private String access(String userId) throws JOSEException {
        return sign(userId, "access", Instant.now().plusSeconds(600), TEST_SECRET);
    }

    private String sign(String sub, String type, Instant expiry, String secret) throws JOSEException {
        var claims = new JWTClaimsSet.Builder().subject(sub).claim("type", type)
                .issueTime(Date.from(Instant.now()));
        if (expiry != null) {
            claims.expirationTime(Date.from(expiry));
        }
        var token = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256), claims.build());
        token.sign(new MACSigner(secret));
        return "Bearer " + token.serialize();
    }
}
