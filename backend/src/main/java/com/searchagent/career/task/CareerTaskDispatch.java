package com.searchagent.career.task;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.NullNode;
import jakarta.validation.Validator;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

@Configuration(proxyBeanMethods = false)
@EnableScheduling
@ConditionalOnProperty(name = "career.agent.dispatch-enabled", havingValue = "true", matchIfMissing = true)
class CareerTaskDispatch {
    private static final Logger log = LoggerFactory.getLogger(CareerTaskDispatch.class);
    private final CareerTaskStore store;
    private final RestClient client;
    private final String token;
    private final ObjectMapper json;
    private final Validator validator;

    CareerTaskDispatch(CareerTaskStore store, RestClient.Builder builder, ObjectMapper json, Validator validator,
            @Value("${career.agent.base-url}") String baseUrl, @Value("${career.agent.internal-token}") String token) {
        var factory = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                        .connectTimeout(Duration.ofSeconds(3)).build());
        factory.setReadTimeout(Duration.ofSeconds(100));
        this.store = store;
        this.client = builder.baseUrl(baseUrl).requestFactory(factory).build();
        this.token = token;
        this.json = json;
        this.validator = validator;
    }

    @Scheduled(fixedDelay = 1000)
    void dispatch() {
        store.claim().ifPresent(this::run);
    }

    @Scheduled(fixedDelay = 1000, initialDelay = 500)
    void dispatchSecond() {
        dispatch();
    }

    private void run(CareerTaskStore.Row row) {
        if (row.trainingDraft() != null) {
            store.finish(row, row.trainingDraft(), null);
            return;
        }
        if (token.isBlank()) {
            store.finish(row, null, "Agent 内部服务未配置");
            return;
        }
        JsonNode result = null;
        String errorMessage = null;
        boolean training = "TRAINING".equals(row.kind());
        try {
            result = client.post().uri("/internal/v1/tasks")
                    .headers(headers -> headers.setBearerAuth(token))
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("id", row.id(), "lease", row.lease(), "userId", row.user(),
                            "kind", row.kind(), "context", row.context(), "trainingCatalog",
                            row.trainingCatalog() == null ? NullNode.getInstance() : row.trainingCatalog()))
                    .retrieve().body(JsonNode.class);
            if (!training) {
                var evaluation = json.treeToValue(result, Evaluation.class);
                if (evaluation == null || !validator.validate(evaluation).isEmpty()) {
                    throw new IllegalArgumentException("Invalid evaluation");
                }
                result = json.valueToTree(evaluation);
            }
        } catch (Exception error) {
            log.warn("Career task {} generation {} failed ({})", row.id(), row.generation(),
                    error instanceof RestClientResponseException http ? http.getStatusCode() : error.getClass().getSimpleName());
            result = null;
            errorMessage = failure(error);
        }
        if (training) {
            // The draft may have committed even if the Agent response was lost.
            result = store.active(UUID.fromString(row.id()), UUID.fromString(row.lease()))
                    .map(CareerTaskStore.Row::trainingDraft).orElse(null);
            if (result != null) {
                errorMessage = null;
            } else if (errorMessage == null) {
                errorMessage = "Agent 未生成训练计划";
            }
        }
        store.finish(row, result, errorMessage);
    }

    private static String failure(Exception error) {
        if (error instanceof RestClientResponseException http && http.getStatusCode().value() == 412) {
            return "请在模型配置中设置支持工具调用的默认对话模型，然后重试";
        }
        return "Agent 执行失败，请稍后重试";
    }

    private record Evaluation(
            @NotBlank @Size(max = 6000) String feedback) {}
}
