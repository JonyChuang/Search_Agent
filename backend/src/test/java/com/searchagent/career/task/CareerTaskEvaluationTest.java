package com.searchagent.career.task;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.IntStream;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

@SpringBootTest(properties = {
        "spring.datasource.url=${CAREER_TEST_MYSQL_URL}",
        "spring.datasource.username=${CAREER_TEST_MYSQL_USER}",
        "spring.datasource.password=${CAREER_TEST_MYSQL_PASSWORD:}",
        "career.auth.jwt-secret=test-only-signing-secret-at-least-32-bytes",
        "career.agent.dispatch-enabled=false"
})
@EnabledIfEnvironmentVariable(named = "CAREER_TASK_EVAL", matches = "true")
class CareerTaskEvaluationTest {
    @Autowired CareerTaskStore store;
    @Autowired JdbcTemplate db;
    @Autowired ObjectMapper json;

    private record Submission(String user, String job, UUID request, String id) {}

    @Test
    void queuedWorkload() throws Exception {
        int workloads = 0;
        int tasks = 0;
        for (int workers : List.of(4, 8)) {
            try (var pool = Executors.newFixedThreadPool(workers)) {
                for (int users : List.of(2, 3, 4)) {
                    for (int jobs : List.of(2, 3)) {
                        for (int repetition = 0; repetition < 3; repetition++) {
                            tasks += runWorkload(pool, workers, users, jobs);
                            workloads++;
                        }
                    }
                }
            }
        }
        System.out.printf("CAREER_QUEUE_EVAL workloads=%d distinct_claims=%d replays=%d%n", workloads, tasks, tasks);
    }

    private int runWorkload(ExecutorService pool, int workers, int userCount, int jobCount) throws Exception {
        var users = IntStream.range(0, userCount).mapToObj(ignored -> UUID.randomUUID().toString()).toList();
        try {
            var submissions = new ArrayList<Submission>();
            var nextByJob = new HashMap<String, List<String>>();
            for (String user : users) {
                for (int jobIndex = 0; jobIndex < jobCount; jobIndex++) {
                    String job = UUID.randomUUID().toString();
                    var ids = new ArrayList<String>();
                    for (int ordinal = 0; ordinal < 2; ordinal++) {
                        var request = UUID.randomUUID();
                        var row = insert(user, job, request);
                        submissions.add(new Submission(user, job, request, row.id()));
                        ids.add(row.id());
                    }
                    nextByJob.put(job, ids);
                }
            }

            List<Callable<String>> replays = submissions.stream().<Callable<String>>map(submission ->
                    () -> insert(submission.user(), submission.job(), submission.request()).id()).toList();
            var results = pool.invokeAll(replays, 30, TimeUnit.SECONDS);
            for (int index = 0; index < results.size(); index++) {
                assertEquals(submissions.get(index).id(), results.get(index).get());
            }

            var claimedIds = new HashSet<String>();
            List<Callable<Optional<CareerTaskStore.Row>>> claimers = IntStream.range(0, workers)
                    .<Callable<Optional<CareerTaskStore.Row>>>mapToObj(ignored -> store::claim).toList();
            while (claimedIds.size() < submissions.size()) {
                var batch = new ArrayList<CareerTaskStore.Row>();
                for (var future : pool.invokeAll(claimers, 30, TimeUnit.SECONDS)) {
                    future.get().ifPresent(batch::add);
                }
                assertFalse(batch.isEmpty());
                assertTrue(batch.size() <= 4);
                var jobsInBatch = new HashSet<String>();
                var perUser = new HashMap<String, Integer>();
                for (var row : batch) {
                    assertTrue(jobsInBatch.add(row.jobId()), "A job was claimed twice in the same batch");
                    assertTrue(perUser.merge(row.user(), 1, Integer::sum) <= 2);
                    assertEquals(nextByJob.get(row.jobId()).removeFirst(), row.id());
                    assertTrue(claimedIds.add(row.id()));
                }
                for (var row : batch) assertTrue(store.finish(row, json.createObjectNode(), null));
            }
            assertTrue(store.claim().isEmpty());
            return claimedIds.size();
        } finally {
            for (String user : users) db.update("DELETE FROM career_task WHERE user_id = ?", user);
        }
    }

    @Test
    void expiredLeaseWorkload() {
        for (int stage : List.of(0, 1, 2)) {
            for (int repetition = 0; repetition < 8; repetition++) verifyTakeover(stage);
        }
        System.out.println("CAREER_LEASE_EVAL cases=24 successful_takeovers=24 stale_completions_rejected=24");
    }

    private void verifyTakeover(int stage) {
        String user = UUID.randomUUID().toString();
        try {
            var queued = insert(user, UUID.randomUUID().toString(), UUID.randomUUID());
            var old = store.claim().orElseThrow();
            assertEquals(queued.id(), old.id());
            var catalog = json.createArrayNode().addObject().put("id", "example");
            var draft = json.createObjectNode().put("analysis", "example");
            if (stage >= 1) assertTrue(store.checkpointCatalog(old, json.createArrayNode().add(catalog)).isPresent());
            if (stage == 2) assertTrue(store.checkpointDraft(old, draft).isPresent());
            assertEquals(1, db.update("UPDATE career_task SET lease_until = CURRENT_TIMESTAMP(6) - INTERVAL 1 SECOND "
                    + "WHERE id = ?", old.id()));

            var current = store.claim().orElseThrow();
            assertEquals(old.id(), current.id());
            assertEquals(old.generation() + 1, current.generation());
            assertNotEquals(old.lease(), current.lease());
            assertEquals(stage >= 1, current.trainingCatalog() != null);
            assertEquals(stage == 2 ? draft : null, current.trainingDraft());
            assertFalse(store.finish(old, json.createObjectNode().put("stale", true), null));
            assertTrue(store.finish(current, draft, null));
            assertEquals(draft, store.owned(user, UUID.fromString(current.id())).orElseThrow().result());
        } finally {
            db.update("DELETE FROM career_task WHERE user_id = ?", user);
        }
    }

    private CareerTaskStore.Row insert(String user, String job, UUID request) {
        return store.insert(user, request, "TRAINING", job, json.createObjectNode(), json.createObjectNode());
    }
}
