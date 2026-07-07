# Codeglass — AI Code Review Platform

Reviews pasted code or uploaded files the way a senior engineer would leave PR
comments: bugs, security issues, and improvement suggestions, ranked by
severity — combining local static analysis with an optional LLM pass.

## How it works

- **Static analysis (always on, no API key needed)**
  - Python: custom AST checks (bare `except`, mutable default args, `is` vs
    `==`, long functions, `eval`/`exec`) plus `bandit` (security) and
    `pylint` (bugs/quality) if installed.
  - JavaScript/TypeScript: heuristics for `var`, loose `==`, empty `catch`,
    `innerHTML`/`document.write` XSS risk, etc.
  - Any language: secret/credential scanning, hardcoded HTTP URLs, disabled
    TLS verification, long lines, leftover `TODO`/`console.log`.
- **AI review (optional)** — sends the code + static findings to Google
  Gemini for a higher-level review (logic issues, edge cases,
  maintainability). Completely optional; the app works fully without it.

No API key is bundled with this project. If you want the AI layer, get a
free Gemini key and set it as an environment variable — never hardcode it
in source.

## Setup

```bash
cd backend
pip install -r requirements.txt

# Optional — only if you want the AI review layer:
export GEMINI_API_KEY="your-key-here"   # https://aistudio.google.com/app/apikey

python app.py
```

Then open **http://localhost:5000** — the Flask app serves the frontend
directly, so there's nothing else to run.

If `bandit` or `pylint` aren't installed, Python analysis still runs (AST
checks only); the app degrades gracefully rather than erroring.

## Project structure

```
backend/
  app.py                  Flask API + serves the frontend
  analyzer/
    static_checks.py      AST checks, bandit/pylint wrappers, regex heuristics
    llm_review.py          Optional Gemini integration
  requirements.txt
frontend/
  index.html
  style.css
  script.js
```

## API

`POST /api/analyze`
```json
{ "code": "...", "language": "python", "use_llm": true }
```
Returns static findings, severity counts, a 0-100 score, and (if enabled)
the AI review, each finding normalized to:
```json
{ "line": 12, "severity": "high", "category": "security", "message": "...", "tool": "bandit" }
```

## Deploying

The app is one Flask process serving both the API and the frontend, so
deployment means "run this one process somewhere," not "deploy a frontend and
a backend separately."

**Before deploying, anywhere:**
- Set `GEMINI_API_KEY` as an environment variable on the host if you want AI
  review live — never commit it to the repo.
- The app already runs with `FLASK_DEBUG=0` by default (safe for production).
- `bandit`/`pylint` run as subprocesses, so pick a host that allows that —
  avoid strict serverless-function platforms (e.g. Vercel/Netlify functions).
  Regular app-hosting platforms (below) all handle this fine.

### Option A — Render / Railway (easiest, free tier available)
Both auto-detect the included `Procfile`:
```
web: gunicorn --chdir backend app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60
```
1. Push this project to a GitHub repo.
2. On Render: New → Web Service → connect the repo → it reads the Procfile
   automatically. On Railway: New Project → Deploy from GitHub repo.
3. Add `GEMINI_API_KEY` under the service's environment variables (optional).
4. Deploy. You'll get a URL like `https://your-app.onrender.com`.

### Option B — Docker (Fly.io, DigitalOcean App Platform, AWS, or any VPS)
A `Dockerfile` is included and already verified to build and serve correctly:
```bash
docker build -t codeglass .
docker run -p 8080:8080 -e GEMINI_API_KEY="your-key" codeglass
```
Push the image to Fly.io / DigitalOcean / ECR / your registry of choice, or
run it directly on a VPS with `docker run` behind a reverse proxy (nginx/Caddy)
for HTTPS.

### Option C — Plain VPS, no Docker
```bash
git clone <your-repo> && cd code-review-platform/backend
pip install -r requirements.txt
export GEMINI_API_KEY="your-key"   # optional
gunicorn app:app --bind 0.0.0.0:8000 --workers 2 --timeout 60
```
Put nginx or Caddy in front for HTTPS and a domain name, and run gunicorn
under `systemd` (or `pm2`/`supervisor`) so it restarts on crash/reboot.

### Notes
- The frontend auto-detects whether it's same-origin with the API (normal
  deployment) or on a different port (e.g. local Live Server on `:5500`), so
  no code changes are needed between local dev and production.
- The dev server (`python app.py`) is fine for local testing but not for
  production traffic — use gunicorn (all options above already do).

## Notes on the "real PR" version

This build reviews pasted/uploaded code rather than live GitHub pull
requests, since wiring up real PR ingestion needs a GitHub token and repo
access that only you can provide. To point it at real PRs: fetch the diff
via the GitHub API (`GET /repos/{owner}/{repo}/pulls/{pr}/files`) in
`app.py` and feed each changed file's content into the same
`run_static_analysis` / `get_llm_review` pipeline already built here.
