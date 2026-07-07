# Codeglass — AI Code Review Platform

Reviews pasted code or uploaded files the way a senior engineer would leave comments: bugs, security issues, and improvement suggestions, ranked by severity — combining local static analysis with an optional LLM pass.

**Live Code:** https://codeglass.onrender.com/

## Setup

```bash
cd backend

pip install -r requirements.txt

python app.py
```

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
