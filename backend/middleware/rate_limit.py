import time
from collections import defaultdict, deque


class InMemoryRateLimiter:
    """Sliding-window rate limiter: max_per_hour requests per IP per hour."""

    def __init__(self, max_per_hour: int = 5) -> None:
        self.max = max_per_hour
        self._buckets: dict[str, deque] = defaultdict(deque)

    def allow(self, ip: str) -> tuple[bool, int]:
        now = time.time()
        bucket = self._buckets[ip]
        while bucket and bucket[0] < now - 3600:
            bucket.popleft()
        if len(bucket) >= self.max:
            retry_after = int(bucket[0] + 3600 - now) + 1
            return False, retry_after
        bucket.append(now)
        return True, 0

    def cleanup_stale(self) -> None:
        cutoff = time.time() - 3600
        stale = [ip for ip, b in self._buckets.items() if not b or b[-1] < cutoff]
        for ip in stale:
            del self._buckets[ip]


rate_limiter = InMemoryRateLimiter(max_per_hour=5)
