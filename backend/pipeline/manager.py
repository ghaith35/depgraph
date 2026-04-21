import logging
import shutil
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
        job = self._jobs.pop(job_id, None)
        if job:
            _cleanup_job_fs(job)

    def evict_expired(self) -> None:
        now = time.monotonic()
        expired = [
            jid for jid, j in list(self._jobs.items())
            if now - j.created_at > JOB_TTL_SECONDS
        ]
        for jid in expired:
            logger.info("Evicting expired job %s", jid)
            job = self._jobs.pop(jid, None)
            if job:
                _cleanup_job_fs(job)


def _cleanup_job_fs(job: Job) -> None:
    if job.repo_dir:
        job_dir = job.repo_dir.parent  # /tmp/jobs/{job_id}/
        try:
            shutil.rmtree(job_dir, ignore_errors=True)
            logger.debug("Cleaned FS for job %s", job.job_id)
        except Exception:
            pass


stream_jobs = StreamJobManager()
