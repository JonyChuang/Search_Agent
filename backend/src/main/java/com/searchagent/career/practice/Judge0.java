package com.searchagent.career.practice;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
class Judge0 {
    private static final String SQL = """
            import base64, json, sqlite3, sys
            query = base64.b64decode('%s').decode('utf-8')
            conn = sqlite3.connect(':memory:')
            conn.executescript(sys.stdin.read())
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE}
            functions = {'count', 'sum', 'min', 'max', 'avg', 'coalesce', 'lower', 'upper', 'length', 'round', 'abs'}
            def authorize(action, name, detail, db, caller):
                if action in allowed or (action == sqlite3.SQLITE_FUNCTION and (detail or "").lower() in functions):
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            conn.set_authorizer(authorize)
            cursor = conn.execute(query)
            rows = cursor.fetchmany(512)
            if len(rows) == 512:
                sys.exit(2)
            print(json.dumps(rows, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
            """;
    private final RestClient api;
    private final int python;
    private final ObjectMapper json;

    Judge0(ObjectMapper json, @Value("${career.judge.base-url:}") String url, @Value("${career.judge.token:}") String token,
            @Value("${career.judge.python-id:71}") int python) {
        this.python = python;
        this.json = json;
        if (url.isBlank()) {
            api = null;
            return;
        }
        URI address = URI.create(url.strip());
        if (address.getHost() == null || !Set.of("http", "https").contains(address.getScheme())
                || address.getUserInfo() != null || address.getQuery() != null || address.getFragment() != null) {
            throw new IllegalArgumentException("Invalid Judge0 base URL");
        }
        var http = java.net.http.HttpClient.newBuilder().version(java.net.http.HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(2)).build();
        var requests = new JdkClientHttpRequestFactory(http);
        requests.setReadTimeout(Duration.ofSeconds(4));
        var builder = RestClient.builder().baseUrl(url.strip()).requestFactory(requests);
        if (!token.isBlank()) builder.defaultHeader("X-Auth-Token", token);
        api = builder.build();
    }

    boolean configured() { return api != null; }

    String submit(String kind, String candidate, JsonNode fixture) throws JsonProcessingException {
        JsonNode config = api.get().uri("/config_info").retrieve().body(JsonNode.class);
        if (config == null || !config.path("enable_network").isBoolean() || config.path("enable_network").asBoolean()
                || !config.path("allow_enable_network").isBoolean() || config.path("allow_enable_network").asBoolean()) {
            throw new IllegalStateException("Judge0 must disallow networking");
        }
        String code = "SQL".equals(kind) ? SQL.formatted(encode(candidate)) : candidate;
        byte[] submission = json.writeValueAsBytes(Map.of(
                "language_id", python, "source_code", encode(code), "stdin", encode(fixture.path("stdin").asText()),
                "expected_output", encode(fixture.path("expected").asText()), "cpu_time_limit", 2,
                "wall_time_limit", 5, "memory_limit", 65536, "max_file_size", 128,
                "max_processes_and_or_threads", 8, "enable_network", false));
        var response = api.post().uri("/submissions?base64_encoded=true&wait=false")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON).contentLength(submission.length)
                .body(submission).retrieve().body(JsonNode.class);
        String token = response == null ? "" : response.path("token").asText();
        if (!token.matches("[A-Za-z0-9-]{1,128}")) throw new IllegalStateException("Invalid sandbox ticket");
        return token;
    }

    String status(String token) {
        var result = api.get().uri("/submissions/{token}?fields=status&base64_encoded=true", token)
                .retrieve().body(JsonNode.class);
        int status = result == null ? 0 : result.path("status").path("id").asInt();
        return switch (status) {
            case 1, 2 -> "RUNNING";
            case 3 -> "ACCEPTED";
            case 4 -> "WRONG_ANSWER";
            case 5 -> "TIME_LIMIT";
            case 6 -> "COMPILE_ERROR";
            case 7, 8, 9, 10, 11, 12 -> "RUNTIME_ERROR";
            default -> "SYSTEM_ERROR";
        };
    }

    private static String encode(String value) {
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }
}

