import re
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db_helpers import (_connect as connect, _export_csv as export_csv,
                        COLUMNS, STATUSES, save_job_row, get_jd as get_jd_text)

STATIC_DIR = Path(__file__).parent / "static"

# Profile keywords for the transparent keyword-overlap score (heuristic, not ML).
PROFILE_KEYWORDS = [
    "python", "java", "fastapi", "spring boot", "docker", "kubernetes", "aws",
    "machine learning", "ml", "llm", "rag", "pytorch", "hugging face",
    "fine-tuning", "lora", "embeddings", "ci/cd", "backend", "microservices",
    "sql", "groq", "gemini", "openai", "agent", "transformers", "vector",
    "faiss", "chromadb", "kafka", "evaluation", "prompt", "distributed",
]
SCORE_TARGET = 8


def profile_keywords() -> list[str]:
    """Score against your real skills from profile.json; fall back to the list above."""
    p = Path(__file__).parent / "profile.json"
    if p.exists():
        skills = json.loads(p.read_text(encoding="utf-8")).get("current_skills", [])
        if skills:
            return [s.lower() for s in skills]
    return PROFILE_KEYWORDS


def score(job: dict, full_jd: str = "") -> tuple[int, list[str]]:
    text = full_jd or job.get("description", "")          # prefer full JD, fall back to snippet
    blob = " ".join([str(job.get("title", "")), str(job.get("company", "")), text]).lower()
    hits = [kw for kw in profile_keywords()
            if re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", blob)]
    pct = min(100, round(100 * len(hits) / SCORE_TARGET))
    return pct, hits


def job_to_dict(row: sqlite3.Row, full_jd: str = "") -> dict:
    d = dict(row)
    s, hits = score(d, full_jd)
    d["match_score"] = s
    d["matched_keywords"] = hits
    return d


app = FastAPI(title="JobAgent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class JobUpdate(BaseModel):
    status: str | None = None
    note: str | None = None


class NewJob(BaseModel):
    title: str
    company: str
    url: str = ""
    location: str = ""
    posted: str = ""
    note: str = ""


@app.get("/api/jobs")
def list_jobs():
    conn = connect()
    try:
        rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM jobs ORDER BY saved_at DESC").fetchall()
        jds = dict(conn.execute("SELECT id, description FROM jd").fetchall())
    finally:
        conn.close()
    return [job_to_dict(r, jds.get(r["id"], "")) for r in rows]


@app.patch("/api/jobs/{job_id}")
def update_job(job_id: str, upd: JobUpdate):
    if upd.status is not None and upd.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "job not found")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if upd.status is not None:
            conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (upd.status, now, job_id))
        if upd.note is not None:
            conn.execute("UPDATE jobs SET note=?, updated_at=? WHERE id=?", (upd.note, now, job_id))
        conn.commit()
        export_csv(conn)
        row = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    return job_to_dict(row)


@app.post("/api/jobs")
def add_job(job: NewJob):
    r = save_job_row(job.title, job.company, job.url, job.location, note=job.note, source="manual")
    if r["status"] == "already_saved":
        raise HTTPException(409, "Looks like that job is already tracked.")
    conn = connect()
    try:
        row = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM jobs WHERE id=?", (r["id"],)).fetchone()
    finally:
        conn.close()
    return job_to_dict(row)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    conn = connect()
    try:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.execute("DELETE FROM jd WHERE id=?", (job_id,))
        conn.commit()
        export_csv(conn)
    finally:
        conn.close()
    return {"deleted": job_id}


@app.get("/api/jobs/{job_id}/jd")
def get_jd(job_id: str):
    return {"description": get_jd_text(job_id)}


@app.get("/api/jobs/{job_id}/optimise")
def optimise_prompt(job_id: str):
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "job not found")
    j = dict(row)
    full_jd = get_jd_text(job_id) or j.get("description") or ""
    prompt = (
        f"Tailor my CV for this role. Keep it strictly honest — only use experience "
        f"from my real CV, never invent skills or metrics.\n\n"
        f"ROLE: {j['title']} at {j['company']} ({j['location']})\n"
        f"LINK: {j['url']}\n\n"
        f"JOB DESCRIPTION:\n{full_jd}\n\n"
        f"Rewrite my summary to target this role, reorder my bullets so the most "
        f"relevant true experience leads, and flag any keyword the JD wants that my "
        f"CV genuinely doesn't support so I can decide whether to address it."
    )
    return {"prompt": prompt}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")