package com.searchagent.career.integration;

import java.net.http.HttpClient;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

@Component("agentHealthIndicator")
class AgentHealthIndicator implements HealthIndicator {
    private final RestClient client;
    private final String token;

    AgentHealthIndicator(
            RestClient.Builder clientBuilder,
            @Value("${career.agent.base-url}") String baseUrl,
            @Value("${career.agent.internal-token}") String token) {
        var factory = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build());
        factory.setReadTimeout(Duration.ofSeconds(3));
        this.client = clientBuilder.baseUrl(baseUrl).requestFactory(factory).build();
        this.token = token;
    }

    @Override
    public Health health() {
        if (token.isBlank()) {
            return Health.down().build();
        }
        try {
            var response = client.get()
                    .uri("/internal/v1/health")
                    .headers(headers -> headers.setBearerAuth(token))
                    .retrieve()
                    .toEntity(AgentHealth.class);
            if (response.getStatusCode().value() == 200 && response.getBody() != null
                    && "UP".equals(response.getBody().status())) {
                return Health.up().build();
            }
        } catch (RestClientException exception) {
            return Health.down().build();
        }
        return Health.down().build();
    }

    private record AgentHealth(String status) {}
}
