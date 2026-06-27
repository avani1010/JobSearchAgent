"""
db_helpers.py — single source of truth for JobAgent storage.

Imported by server.py (MCP tools), ui.py (dashboard), and watch_greenhouse.py
(scheduler). The schema, connection, JD stash, dedupe-save, and CSV export live
here and ONLY here, so the three components can never drift out of sync.
"""
import csv
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timezone

DB_DIR = Path.home() / ".jobagent"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "jobagent.db"
CSV_PATH = DB_DIR / "jobs.csv"

# jobs.description holds only the SHORT snippet; the full JD lives in the jd table.
COLUMNS = ["id", "title", "company", "location", "url", "posted",
           "status", "note", "saved_at", "updated_at", "description","source"]
CSV_COLUMNS = COLUMNS              # snippet is small; trim here if you want a leaner CSV
STATUSES = ["saved", "in_review", "applied", "interview", "offer", "rejected"]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)   # timeout: tolerate concurrent writers
    conn.row_factory = sqlite3.Row
    conn.execute(f"""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, url TEXT,
        posted TEXT, status TEXT DEFAULT 'saved', note TEXT DEFAULT '',
        saved_at TEXT, updated_at TEXT, description TEXT, source TEXT DEFAULT '')""")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "source" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN source TEXT DEFAULT ''")
    conn.execute("CREATE TABLE IF NOT EXISTS jd (id TEXT PRIMARY KEY, description TEXT)")
    return conn


def _export_csv(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        f"SELECT {', '.join(CSV_COLUMNS)} FROM jobs ORDER BY saved_at DESC"
    ).fetchall()
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: dict(r).get(k, "") for k in CSV_COLUMNS})


def _stash_jd(job_id: str, description: str) -> None:
    """Store the FULL job description, keyed by job id (called at search time)."""
    if not job_id:
        return
    conn = _connect()
    try:
        conn.execute("INSERT OR REPLACE INTO jd (id, description) VALUES (?, ?)",
                     (job_id, description or ""))
        conn.commit()
    finally:
        conn.close()


def get_jd(job_id: str) -> str:
    """Return the stored full JD for a job id, or '' if none."""
    conn = _connect()
    try:
        row = conn.execute("SELECT description FROM jd WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    return row["description"] if row and row["description"] else ""


def make_id(job_id: str = "", url: str = "", title: str = "", company: str = "") -> str:
    """Stable id: prefer the source id, else hash the url (or title|company)."""
    return job_id or "h-" + hashlib.sha1(
        (url or f"{title}|{company}").encode("utf-8")).hexdigest()[:16]


def save_job_row(title: str, company: str, url: str = "", location: str = "",
                 job_id: str = "", posted: str = "", description: str = "",
                 note: str = "", status: str = "saved",source="") -> dict:
    """Insert a job if new (dedupe on id), refresh the CSV, return a result dict.
    Shared by the MCP save_job tool, the UI add-job endpoint, and the scheduler."""
    jid = make_id(job_id, url, title, company)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _connect()
    try:
        existing = conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
        if existing:
            return {"status": "already_saved", "id": jid, "existing_status": existing["status"]}
        conn.execute(
            f"INSERT INTO jobs ({', '.join(COLUMNS)}) VALUES ({', '.join(['?']*len(COLUMNS))})",
            (jid, title, company, location, url, posted, status, note, now, now, description,source),
        )
        conn.commit()
        _export_csv(conn)
    finally:
        conn.close()
    return {"status": "saved", "id": jid}