package com.searchagent.career;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.regex.Pattern;

import jakarta.servlet.DispatcherType;
import javax.crypto.spec.SecretKeySpec;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtClaimValidator;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.web.SecurityFilterChain;

@Configuration(proxyBeanMethods = false)
class CareerSecurity {
    private static final Pattern UUID_SUBJECT = Pattern.compile(
            "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");

    @Bean
    SecurityFilterChain security(HttpSecurity http) throws Exception {
        return http
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(requests -> requests
                        .dispatcherTypeMatchers(DispatcherType.ERROR).permitAll()
                        .requestMatchers(HttpMethod.GET, "/api/career/health").permitAll()
                        .requestMatchers(HttpMethod.PUT, "/internal/career/tasks/*/questions",
                                "/internal/career/tasks/*/plan").permitAll()
                        .requestMatchers("/api/career/**").authenticated()
                        .anyRequest().denyAll())
                .oauth2ResourceServer(oauth -> oauth.jwt(jwt -> {}))
                .build();
    }

    @Bean
    JwtDecoder cometJwtDecoder(
            @Value("${career.auth.jwt-secret}") String secret,
            @Value("${career.auth.jwt-algorithm}") String algorithm) {
        MacAlgorithm mac = MacAlgorithm.from(algorithm);
        int minimumBytes = switch (algorithm) {
            case "HS256" -> 32;
            case "HS384" -> 48;
            case "HS512" -> 64;
            default -> throw new IllegalArgumentException("JWT_ALGORITHM must be HS256, HS384 or HS512");
        };
        byte[] secretBytes = secret.getBytes(StandardCharsets.UTF_8);
        if (secret.isBlank() || secretBytes.length < minimumBytes) {
            throw new IllegalArgumentException("JWT_SECRET is too short for JWT_ALGORITHM");
        }
        var key = new SecretKeySpec(secretBytes, "HmacSHA" + algorithm.substring(2));
        var decoder = NimbusJwtDecoder.withSecretKey(key).macAlgorithm(mac).build();
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<Jwt>(
                new JwtTimestampValidator(Duration.ZERO),
                new JwtClaimValidator<>("exp", expiresAt -> expiresAt != null),
                new JwtClaimValidator<>("type", "access"::equals),
                new JwtClaimValidator<String>("sub", sub -> sub != null && UUID_SUBJECT.matcher(sub).matches())
        ));
        return decoder;
    }
}
