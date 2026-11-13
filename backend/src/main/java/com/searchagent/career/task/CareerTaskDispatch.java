package com.searchagent.career.task;

import java.net.http.HttpClient;
import java.net.URI;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.NullNode;
import jakarta.validation.Validator;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
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
                            row.trainingCatalog() == null ? NullNode.getInstance() : row.trainingCatalog(),
                            "agentContext", row.agentContext() == null ? NullNode.getInstance() : row.agentContext()))
                    .retrieve().body(JsonNode.class);
            if (!training) {
                Object evaluation = switch (row.kind()) {
                    case "PREPARATION" -> json.treeToValue(result, Preparation.class);
                    case "DISCOVERY" -> json.treeToValue(result, Discovery.class);
                    default -> json.treeToValue(result, Evaluation.class);
                };
                if (evaluation == null || !validator.validate(evaluation).isEmpty()) {
                    throw new IllegalArgumentException("Invalid evaluation");
                }
                if (evaluation instanceof Discovery discovery) {
                    result = json.valueToTree(Map.of("sources", discovery.sources().stream()
                            .filter(source -> webUrl(source.url())).toList(), "searchedAt", Instant.now()));
                } else {
                    result = json.valueToTree(evaluation);
                }
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
        if (error instanceof RestClientResponseException http) {
            return switch (http.getStatusCode().value()) {
                case 412 -> "请在模型配置中设置支持工具调用的默认对话模型，然后重试";
                case 424 -> "请先在模型配置中添加联网搜索，再重试";
                case 422 -> "模型未返回符合工具格式的结果。可以重试，或切换支持工具调用的模型。";
                case 409 -> "备考资料或技能不可用、已变更，请检查后重新创建任务。";
                case 413 -> "备考输入超出上下文预算，请减少参考资料或缩短输入后重新创建任务。";
                case 429 -> "模型服务暂时繁忙，请稍后重试。";
                default -> "Agent 执行失败，请稍后重试";
            };
        }
        return "Agent 执行失败，请稍后重试";
    }

    private record Evaluation(
            @NotBlank @Size(max = 6000) String feedback) {}

    private record Preparation(
            @NotNull @Size(min = 1, max = 8) List<@NotBlank @Size(max = 60) String> skills,
            @NotNull @Size(min = 1, max = 5) List<@NotNull @Valid OpenQuestion> openQuestions) {}

    private record OpenQuestion(
            @NotBlank @Size(max = 80) String topic, @NotBlank @Size(max = 1000) String prompt,
            @NotNull @Size(min = 1, max = 5) List<@NotBlank @Size(max = 500) String> rubric) {}

    private record Discovery(@NotNull @Size(max = 10) List<@NotNull @Valid Source> sources) {}

    private record Source(@NotBlank @Size(max = 240) String title, @NotBlank @Size(max = 2048) String url,
            @NotNull @Size(max = 750) String snippet) {}

    private static boolean webUrl(String value) {
        try {
            URI url = URI.create(value);
            return url.getHost() != null && url.getRawUserInfo() == null
                    && ("https".equalsIgnoreCase(url.getScheme()) || "http".equalsIgnoreCase(url.getScheme()));
        } catch (IllegalArgumentException error) {
            return false;
        }
    }
}
