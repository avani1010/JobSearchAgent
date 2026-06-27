import sys
import re
import html
import logging

import httpx
from db_helpers import save_job_row, _stash_jd, _connect

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("watch-greenhouse")

GREENHOUSE_BOARDS = {
    "stripe": "Stripe",
    "intercom": "Intercom",
    "hubspot": "HubSpot",
    "mongodb": "MongoDB",
    "squarespace": "Squarespace",
    "snowflake": "Snowflake",
    "okta": "Okta",
    "twilio": "Twilio",
    "coinbase": "Coinbase",
    "gitlab": "GitLab",
    "fivetran": "Fivetran",
    "vanta": "Vanta",
    "tines": "Tines",
    "wayflyer": "Wayflyer",
    "flipdish": "Flipdish",
    "keelvar": "Keelvar",
}

# --- filters: coarse on purpose. Claude does the real judging on review. ------
LOCATION_TERMS = ["dublin", "ireland", "remote - emea", "remote, eu"]
KEYWORDS = ["engineer", "machine learning", " ml ", "ai ", "backend", "python",
            "data", "software", "llm", "genai", "developer", "platform", "artificial intelligence"]


def matches(title: str, location: str) -> bool:
    loc = (location or "").lower()
    if not any(t in loc for t in LOCATION_TERMS):
        return False
    t = " " + (title or "").lower() + " "
    return any(k in t for k in KEYWORDS)


def clean(text: str, limit: int = 100_000) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit]


def fetch_board(token: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    r = httpx.get(url, timeout=30.0)
    r.raise_for_status()
    return r.json().get("jobs", [])


def run(fetch=fetch_board) -> int:
    """Scan all boards; save new matching roles. `fetch` is injectable for testing."""
    conn = _connect()
    new = scanned = matched = 0
    try:
        for token, name in GREENHOUSE_BOARDS.items():
            try:
                jobs = fetch(token)
            except Exception as e:
                log.warning("board %r failed (bad token or network?): %s", token, e)
                continue
            for j in jobs:
                scanned += 1
                title = j.get("title", "")
                loc = (j.get("location") or {}).get("name", "")
                if not matches(title, loc):
                    continue
                matched += 1
                jid = f"gh-{token}-{j.get('id')}"
                full = clean(j.get("content", ""))
                snippet = full[:300] + ("…" if len(full) > 300 else "")
                r = save_job_row(title, name, j.get("absolute_url",""), loc,
                                 job_id=jid, posted=j.get("updated_at",""), description=snippet, source="greenhouse_scheduled")
                if r["status"] == "saved":
                    _stash_jd(jid, full)
                    new += 1
                    log.info("NEW  %s @ %s  (%s)", title, name, loc)
        conn.commit()
    finally:
        conn.close()
    log.info("scan complete: %d boards, %d postings, %d matched filters, %d NEW saved",
             len(GREENHOUSE_BOARDS), scanned, matched, new)
    return new


if __name__ == "__main__":
    run()