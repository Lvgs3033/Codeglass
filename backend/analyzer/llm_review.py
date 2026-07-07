"""
LLM-powered review layer using Google Gemini.

This is entirely OPTIONAL. If no GEMINI_API_KEY environment variable is set,
`get_llm_review()` returns None and the platform still works using static
analysis alone. No key is bundled or required to run the app.

To enable it:
    export GEMINI_API_KEY="your-key-here"
Get a free key at https://aistudio.google.com/app/apikey
"""
import os
import json
import re

MODEL_NAME = "gemini-2.5-flash"


def _client_ready():
    return bool(os.environ.get("GEMINI_API_KEY"))


def _build_prompt(code: str, language: str, static_findings: list) -> str:
    findings_summary = "\n".join(
        f"- L{f.get('line')} [{f['severity']}/{f['category']}] {f['message']}"
        for f in static_findings[:25]
    ) or "None found."

    return f"""You are a senior software engineer performing a pull request code review.

Language: {language or "unknown"}

Static analysis already found these issues:
{findings_summary}

Code under review:
```{language}
{code}
```

Respond with ONLY valid JSON (no markdown fences, no commentary) matching exactly this schema:
{{
  "summary": "2-3 sentence overall assessment",
  "bugs": [{{"line": <int or null>, "message": "<description>"}}],
  "security_issues": [{{"line": <int or null>, "message": "<description>"}}],
  "suggestions": [{{"line": <int or null>, "message": "<improvement suggestion>"}}],
  "overall_score": <int 0-100, code quality score>
}}

Do not repeat issues already listed by static analysis unless you can add meaningfully more detail.
Focus on logic errors, edge cases, readability, maintainability, and anything static analysis tools typically miss.
"""


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def get_llm_review(code: str, language: str, static_findings: list):
    """Returns a dict with the LLM review, or None if no API key is configured
    or the call fails for any reason (the platform degrades gracefully)."""
    if not _client_ready():
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel(MODEL_NAME)
        prompt = _build_prompt(code, language, static_findings)
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.2, "max_output_tokens": 1500},
        )
        parsed = _extract_json(response.text)
        if parsed is None:
            return {"summary": response.text[:800], "bugs": [], "security_issues": [], "suggestions": [], "overall_score": None}
        return parsed
    except Exception as e:
        return {"error": str(e)}
