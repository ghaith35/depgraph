import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.schemas import AnalysisResult


@dataclass
class Job:
    job_id: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    status: str = "queued"  # queued | running | done | error
    created_at: float = field(default_factory=time.monotonic)
    analysis_result: Optional["AnalysisResult"] = None
    repo_dir: Optional[Path] = None  # kept alive until eviction for /explain
