from datetime import datetime, timezone
import hashlib
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from jobspy import scrape_jobs
import json


from db_helpers import _export_csv, CSV_PATH, _connect, _stash_jd
import logging, sys
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,                      # stderr, NOT stdout
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("jobagent")

mcp = FastMCP("JobSearchAgent")
load_dotenv()

@mcp.tool()
def ping(name: str) -> str:
    return f"jobagent server is alive. Hello, {name}."

def _val(record, key, default=""):
    """Read a DataFrame cell safely. pandas fills blanks with NaN/NaT
    (floats, not None), so str() them and treat as empty."""
    v = record.get(key, default)
    if v is None:
        return default
    s = str(v)
    return default if s in ("nan", "NaT", "None") else s


@mcp.tool()
def get_profile() -> dict:
    """Return the user's career profile: skills, years of experience, target
    roles, location, and constraints. Call this BEFORE judging search results so
    you can decide which jobs are relevant and which the user meets the minimum
    criteria for. Present jobs that fit the target roles and where the user meets
    the stated requirements; set aside or flag ones that don't."""
    p = Path(__file__).parent / "profile.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"error": "profile.json not found"}


@mcp.tool()
def search_jobs(keywords: str, location: str = "Dublin, Ireland",
                max_results: int = 20, hours_old: int | None = None,
                sites: list[str] | None = None) -> list[dict]:
    """Search live job postings by keyword and location via JobSpy
    (scrapes Indeed by default — best Ireland coverage, most reliable source).
    Use this first, before scoring or saving jobs, whenever the user wants to
    find roles. Returns jobs with title, company, location, description,
    and the application URL.

    Args:
        keywords: search terms, e.g. "machine learning engineer" or "backend python"
        location: city/region, e.g. "Dublin, Ireland"
        max_results: how many jobs to fetch (1-50), defaults to 20
        hours_old: only return jobs posted within this many hours (optional)
        sites: boards to scrape; defaults to ["indeed"]. Avoid "linkedin" — it
               rate-limits hard and needs proxies.
    """
    sites = sites or ["indeed", "linkedin", "glassdoor", "google"]
    max_results = max(1, min(max_results, 50))
    log.info("search_jobs: keywords=%r location=%r sites=%s", keywords, location, sites)
    try:
        df = scrape_jobs(
            site_name=sites,
            search_term=keywords,
            location=location,
            results_wanted=max_results,
            hours_old=hours_old,
            country_indeed="Ireland",
            description_format="markdown",
            verbose=0,
        )
    except Exception as e:
        log.exception("scrape_jobs failed with exception: %s", e)
        return [{"error": f"JobSpy scrape failed: {e}. The board may be temporarily blocking — try again shortly."}]

    if df is None or df.empty:
        return [{"message": f"No jobs found for '{keywords}' in {location}."}]
    log.info("search_jobs: got %d rows", 0 if df is None else len(df))


    jobs = []
    for r in df.to_dict(orient="records"):
        loc = _val(r, "location")
        if not loc:  # some versions split location into city/state/country
            parts = [_val(r, "city"), _val(r, "state"), _val(r, "country")]
            loc = ", ".join(p for p in parts if p)
        desc = _val(r, "description")
        _stash_jd(_val(r, "id") or _val(r, "job_url"), desc)
        jobs.append({
            "id": _val(r, "id") or _val(r, "job_url"),
            "title": _val(r, "title", "N/A"),
            "company": _val(r, "company", "N/A"),
            "location": loc or "N/A",
            "url": _val(r, "job_url"),
            "created": _val(r, "date_posted"),
            "description": desc[:300] + ("…" if len(desc) > 300 else ""),
        })
    return jobs[:max_results]

from db_helpers import (_export_csv, CSV_PATH, _connect, _stash_jd,
                        save_job_row, get_jd as _get_jd)

@mcp.tool()
def save_job(title: str, company: str, url: str, location: str = "",
             job_id: str = "", posted: str = "", description: str = "", note: str = "") -> dict:
    """...keep your docstring..."""
    r = save_job_row(title, company, url, location, job_id, posted, description, note, source="tool")
    if r["status"] == "already_saved":
        return {"status": "already_saved", "id": r["id"],
                "message": f"'{title}' at {company} is already tracked (status: {r['existing_status']})."}
    return {"status": "saved", "id": r["id"],
            "message": f"Saved '{title}' at {company}. Tracker CSV: {CSV_PATH}"}

@mcp.tool()
def get_jd(job_id: str) -> dict:
    """...keep your docstring..."""
    desc = _get_jd(job_id)
    return {"job_id": job_id, "description": desc} if desc else \
        {"job_id": job_id, "description": "", "note": "No JD stored."}

if __name__ == "__main__":
    mcp.run(transport="stdio")
    # means this server talks over stdin/stdout : the local mode where Claude Desktop launches it as a subprocess.
