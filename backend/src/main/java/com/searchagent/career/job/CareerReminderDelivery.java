package com.searchagent.career.job;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

@Component
class CareerReminderDelivery {
    private final JdbcClient db;
    private final RestClient client;
    private final String token;

    CareerReminderDelivery(JdbcClient db, RestClient.Builder builder, @Value("${career.agent.base-url}") String baseUrl,
            @Value("${career.agent.internal-token}") String token) {
        this.db = db;
        this.token = token;
        var factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(3)).build());
        factory.setReadTimeout(Duration.ofSeconds(25));
        this.client = builder.baseUrl(baseUrl).requestFactory(factory).build();
    }

    @Scheduled(fixedDelay = 30000)
    void due() {
        db.sql("""
                UPDATE career_reminder SET delivery_state = 'UNKNOWN'
                WHERE delivery_state = 'SENDING' AND delivery_started_at < CURRENT_TIMESTAMP - INTERVAL 2 MINUTE
                """).update();
        if (token.isBlank()) return;
        db.sql("""
                SELECT id, user_id, type, revision FROM career_reminder
                WHERE status = 'PENDING' AND delivery_state = 'READY' AND due_at <= CURRENT_TIMESTAMP(6)
                ORDER BY due_at ASC LIMIT 10
                """).query(Delivery.class).list().forEach(this::deliver);
    }

    private void deliver(Delivery reminder) {
        int claimed = db.sql("""
                UPDATE career_reminder SET delivery_state = 'SENDING', delivery_started_at = CURRENT_TIMESTAMP(6)
                WHERE id = ? AND revision = ? AND delivery_state = 'READY' AND status = 'PENDING'
                    AND due_at <= CURRENT_TIMESTAMP(6)
                """).params(reminder.id(), reminder.revision()).update();
        if (claimed != 1) return;
        String state;
        try {
            var response = client.post().uri("/internal/v1/reminder-notifications")
                    .headers(headers -> headers.setBearerAuth(token))
                    .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                    .body(Map.of("user_id", reminder.userId(), "type", reminder.type()))
                    .retrieve().body(JsonNode.class);
            state = response == null || !response.path("delivered").isIntegralNumber() ? "UNKNOWN"
                    : response.path("delivered").asInt() > 0 ? "SENT" : "UNDELIVERED";
        } catch (RestClientException failure) {
            state = "UNKNOWN";
        }
        db.sql("UPDATE career_reminder SET delivery_state = ? WHERE id = ? AND delivery_state = 'SENDING'")
                .params(state, reminder.id()).update();
    }

    record Delivery(String id, String userId, String type, int revision) {}
}
