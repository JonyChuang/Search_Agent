package com.searchagent.career.web;

import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

@RestControllerAdvice
class CareerErrors {
    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<CareerResponse<Void>> invalidFields(MethodArgumentNotValidException error) {
        var field = error.getBindingResult().getFieldError();
        String message = field == null ? "输入无效" : field.getDefaultMessage();
        return ResponseEntity.badRequest().body(new CareerResponse<>(400, message, null));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<CareerResponse<Void>> invalidBody() {
        return ResponseEntity.badRequest().body(new CareerResponse<>(400, "请求内容或字段格式无效", null));
    }

    @ExceptionHandler(ResponseStatusException.class)
    ResponseEntity<CareerResponse<Void>> statusError(ResponseStatusException error) {
        return ResponseEntity.status(error.getStatusCode())
                .body(new CareerResponse<>(error.getStatusCode().value(), error.getReason(), null));
    }
}
