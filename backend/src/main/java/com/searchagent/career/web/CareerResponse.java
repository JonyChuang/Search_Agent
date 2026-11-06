package com.searchagent.career.web;

public record CareerResponse<T>(int code, String message, T data) {
    public static <T> CareerResponse<T> ok(T data) {
        return new CareerResponse<>(0, "OK", data);
    }
}
