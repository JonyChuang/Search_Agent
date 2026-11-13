package com.searchagent.career.task;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
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
@EnabledIfEnvironmentVariable(named = "CAREER_TEST_MYSQL_URL", matches = "jdbc:mysql:.+")
class CareerTaskSchedulingTest {
    @Autowired CareerTaskStore store;
    @Autowired JdbcTemplate db;
    @Autowired ObjectMapper json;
    private final String user = UUID.randomUUID().toString();
    private final String other = UUID.randomUUID().toString();

    @AfterEach
    void clean() {
        db.update("DELETE FROM career_task WHERE user_id IN (?, ?)", user, other);
    }

    @Test
    void concurrentClaimsKeepJobOrderAndAllowAnotherScope() throws Exception {
        String design = UUID.randomUUID().toString();
        String ecology = UUID.randomUUID().toString();
        var first = enqueue(user, design);
        var second = enqueue(user, design);
        var parallel = enqueue(user, ecology);
        var waiting = enqueue(user, UUID.randomUUID().toString());
        var foreign = enqueue(other, UUID.randomUUID().toString());
        var gate = new CountDownLatch(1);
        Callable<String> claim = () -> {
            assertTrue(gate.await(5, TimeUnit.SECONDS));
            return store.claim().orElseThrow().id();
        };
        try (var pool = Executors.newFixedThreadPool(3)) {
            var futures = List.of(pool.submit(claim), pool.submit(claim), pool.submit(claim));
            gate.countDown();
            var claims = new java.util.HashSet<String>();
            for (var future : futures) claims.add(future.get(10, TimeUnit.SECONDS));
            assertEquals(java.util.Set.of(first.id(), parallel.id(), foreign.id()), claims);
        }
        assertTrue(store.claim().isEmpty());
        var running = store.owned(user, UUID.fromString(first.id())).orElseThrow();
        assertTrue(store.finish(running, json.createObjectNode(), null));
        assertEquals(second.id(), store.claim().orElseThrow().id());
        assertTrue(store.owned(user, UUID.fromString(waiting.id())).filter(row -> "QUEUED".equals(row.status())).isPresent());
    }

    private CareerTaskStore.Row enqueue(String owner, String job) {
        return store.insert(owner, UUID.randomUUID(), "PREPARATION", job,
                json.createObjectNode(), json.createObjectNode());
    }
}
