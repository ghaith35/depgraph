import logging
import time
from typing import Optional

from .job import Job

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 600  # 10 minutes


class StreamJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, job_id: str) -> Job:
        job = Job(job_id=job_id)
        self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def remove(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)

    def evict_expired(self) -> None:
        now = time.monotonic()
        expired = [
            jid for jid, j in list(self._jobs.items())
            if now - j.created_at > JOB_TTL_SECONDS
        ]
        for jid in expired:
            logger.info("Evicting expired job %s", jid)
            self._jobs.pop(jid, None)


stream_jobs = StreamJobManager()
