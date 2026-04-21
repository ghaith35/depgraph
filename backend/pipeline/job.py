import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class Job:
    job_id: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    status: str = "queued"  # queued | running | done | error
    created_at: float = field(default_factory=time.monotonic)
