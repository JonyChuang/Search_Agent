package com.searchagent.career.practice;

import java.util.List;
import java.util.UUID;

import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/career/content-review")
class ContentReviewController {
    private final PublicLearningContent content;
    private final PublicContentFeeds feeds;

    ContentReviewController(PublicLearningContent content, PublicContentFeeds feeds) {
        this.content = content;
        this.feeds = feeds;
    }

    @GetMapping("/access")
    CareerResponse<Boolean> access(@CareerUser String user) {
        return CareerResponse.ok(content.canReview(user));
    }

    @GetMapping
    CareerResponse<Page> list(@CareerUser String user, @RequestParam(defaultValue = "DRAFT") String status,
            @RequestParam(defaultValue = "1") int page) {
        var rows = content.list(user, status, page);
        return CareerResponse.ok(new Page(rows.stream().limit(20).toList(), rows.size() > 20));
    }

    @PostMapping
    CareerResponse<PublicLearningContent.Draft> submit(@CareerUser String user, @RequestBody @Valid Create input) {
        return CareerResponse.ok(content.create(user, input.kind(), input.content()));
    }

    @PutMapping("/{id}")
    CareerResponse<PublicLearningContent.Draft> edit(@CareerUser String user, @PathVariable UUID id, @RequestBody @Valid Edit input) {
        return CareerResponse.ok(content.update(user, id, input.revision(), input.content()));
    }

    @PostMapping("/{id}/publish")
    CareerResponse<PublicLearningContent.Draft> publish(@CareerUser String user, @PathVariable UUID id, @RequestBody @Valid Revision input) {
        return CareerResponse.ok(content.publish(user, id, input.revision()));
    }

    @PostMapping("/{id}/dismiss")
    CareerResponse<PublicLearningContent.Draft> dismiss(@CareerUser String user, @PathVariable UUID id, @RequestBody @Valid Revision input) {
        return CareerResponse.ok(content.dismiss(user, id, input.revision()));
    }

    @GetMapping("/feeds")
    CareerResponse<Integer> sources(@CareerUser String user) {
        content.authorize(user);
        return CareerResponse.ok(feeds.count());
    }

    @PostMapping("/feeds/refresh")
    CareerResponse<PublicContentFeeds.Result> refresh(@CareerUser String user) {
        content.authorize(user);
        return CareerResponse.ok(feeds.refresh());
    }

    record Create(@NotNull PublicLearningContent.Kind kind, @NotNull @Valid PublicLearningContent.Content content) {}
    record Edit(@Positive int revision, @NotNull @Valid PublicLearningContent.Content content) {}
    record Revision(@Positive int revision) {}
    record Page(List<PublicLearningContent.Draft> items, boolean hasMore) {}
}

