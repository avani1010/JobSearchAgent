# Job Search Agent

A local tool that helps me find and track jobs. It searches live job postings,
lets Claude reason about which ones actually fit my profile, and keeps everything
in a small database with a web dashboard to manage applications.

It does **not** apply to jobs for me. It finds them, helps me judge them, and
tracks where each one is in my pipeline. I still hit "apply" myself.

## How it works

There are a few separate pieces that all share one SQLite database
(`~/.jobagent/jobagent.db`):

- **`server.py`** : an MCP server. It exposes tools (search jobs, fetch a job
  description, read my profile, save a job) that Claude Desktop can call. Claude
  is what decides which tools to use and reasons about which jobs are a good fit.
- **`ui.py` + `static/`** : a FastAPI web dashboard to view and manage saved jobs:
  change a job's status, add notes, copy the job description, delete junk. It
  reads and writes the same database the agent uses.
- **`watch_greenhouse.py`** : a script that checks a list of companies' Greenhouse
  career pages and saves new matching roles. Meant to run on a schedule.
- **`db_helpers.py`** : shared database code (schema, connection, save logic) so
  the three pieces above stay in sync.

The basic idea: the scripts do the boring, mechanical part (fetching and storing
jobs). Claude does the judgment part (is this role actually worth my time). I do
the deciding and the applying.

## job sources

- **JobSpy** (Indeed) : good Ireland coverage, no API key, reliable enough.
- **Greenhouse ATS feeds** : public, keyless JSON straight from companies that use
  Greenhouse. Cleaner and more accurate than any aggregator, but only covers
  companies on that platform.

## Setup

Needs Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync          # install dependencies
```

Create a `profile.json` with your details (skills, target roles, years of
experience, location). The agent reads this to judge job fit, and the dashboard
uses the skills list to compute a rough keyword-match score.

```json
{
  "summary": "Backend engineer moving into ML/AI.",
  "years_experience": 3,
  "current_skills": ["Python", "FastAPI", "Docker", "Machine Learning", "RAG"],
  "target_roles": ["AI/ML Engineer", "Backend Engineer"],
  "location": "Dublin, Ireland"
}
```

## Running it

**The dashboard:**

```bash
uv run uvicorn ui:app --reload --port 8000
```

Then open http://localhost:8000.

**The MCP server** (so Claude Desktop can use the tools): add it to Claude
Desktop's config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "jobagent": {
      "command": "/absolute/path/to/uv",
      "args": ["--directory", "/absolute/path/to/this/project", "run", "server.py"]
    }
  }
}
```

Restart Claude Desktop. Then you can ask it things like "search for ML engineer
roles in Dublin and tell me which ones I actually qualify for," and it'll use the
tools to search, read the descriptions, check them against your profile, and save
the good ones.

**The scheduled watcher** (optional): edit the company list at the top of
`watch_greenhouse.py`, then run it on a schedule. On macOS I use a launchd job
twice a day; on Linux, cron works:

```bash
# cron, twice a day
0 9,18 * * * cd /path/to/project && /path/to/uv run python watch_greenhouse.py >> ~/.jobagent/watch.log 2>&1
```

Run it once by hand first to make sure it works:

```bash
uv run python watch_greenhouse.py
```

## The dashboard

Jobs move through a pipeline using the status field:

- **Shortlist** : saved, not yet acted on
- **Scheduled** : found automatically by the watcher, waiting for review
- **In Review** : jobs I'm bundling up to apply to together
- **Applications** : applied / interview / offer / rejected

Each job has buttons to open the listing, copy the full description, copy a
CV-tailoring prompt to paste into Claude, and delete it. Status and note changes
save straight to the database and a CSV mirror.

## Notes / limitations

- It only runs while my machine is on (no always-on server).
- The Greenhouse watcher only covers companies that use Greenhouse, and you have
  to find their board tokens yourself.
- The match score is just keyword overlap, not real understanding. The actual
  fit judgment is Claude reading the full job description, not that number.
- This is a personal project, not production software.

## Files

```
server.py            MCP server (tools Claude calls)
ui.py                FastAPI dashboard backend
static/              dashboard frontend (html, css, js)
watch_greenhouse.py  scheduled job watcher
db_helpers.py        shared database code
profile.json         your details (create this)
```