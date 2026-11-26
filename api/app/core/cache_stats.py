"""Per-process cache counters for structured logs and fallback alerts."""

from collections import Counter, defaultdict

from app.core.logging import get_logger

logger = get_logger(__name__)
_window: dict[str, Counter] = defaultdict(Counter)


def record_cache(cache: str, outcome: str) -> None:
    counts = _window[cache]
    counts[outcome] += 1
    if sum(counts.values()) >= 50:
        log = logger.warning if counts["fallback"] >= 5 else logger.info
        log("Shared cache name=%s hits=%d misses=%d fallbacks=%d hit_rate=%.2f",
            cache, counts["hit"], counts["miss"], counts["fallback"], counts["hit"] / sum(counts.values()))
        counts.clear()
