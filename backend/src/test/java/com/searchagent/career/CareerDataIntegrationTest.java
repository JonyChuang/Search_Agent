package com.searchagent.career;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.Date;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

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
        jdbc.update("DELETE FROM career_task WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_practice_attempt WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_experience WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_job WHERE user_id IN (?, ?)", owner, other);
        jdbc.update("DELETE FROM career_profile WHERE user_id IN (?, ?)", owner, other);
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
                .andExpect(jsonPath("$.data[0].note").value("官网已人工提交"));
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
