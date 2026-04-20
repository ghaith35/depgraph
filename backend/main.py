import uuid
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="DepGraph API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your Vercel domain in prod
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"ok": True}


class SubmitRequest(BaseModel):
    url: str


@app.post("/jobs")
def submit_job(body: SubmitRequest):
    job_id = str(uuid.uuid4())
    logger.info("New job submitted | job_id=%s url=%s", job_id, body.url)
    return {"job_id": job_id}
