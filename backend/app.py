import os
import sys
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))
from analyzer.static_checks import run_static_analysis
from analyzer.llm_review import get_llm_review, _client_ready

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)

MAX_CODE_SIZE = 200_000  # ~200 KB guardrail


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "llm_enabled": _client_ready()})


@app.route("/api/analyze", methods=["POST"])
def analyze():
    payload = request.get_json(silent=True) or {}
    code = payload.get("code", "")
    language = payload.get("language", "python")
    use_llm = bool(payload.get("use_llm", True))

    if not code or not code.strip():
        return jsonify({"error": "No code provided."}), 400
    if len(code) > MAX_CODE_SIZE:
        return jsonify({"error": f"Code too large — limit is {MAX_CODE_SIZE} characters."}), 413

    try:
        static_findings = run_static_analysis(code, language)
    except Exception as e:
        return jsonify({"error": f"Static analysis failed: {e}"}), 500

    llm_result = None
    if use_llm:
        llm_result = get_llm_review(code, language, static_findings)

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in static_findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1

    score = 100
    score -= counts["critical"] * 20
    score -= counts["high"] * 10
    score -= counts["medium"] * 5
    score -= counts["low"] * 2
    score = max(0, min(100, score))

    return jsonify({
        "language": language,
        "static_findings": static_findings,
        "counts": counts,
        "score": score,
        "llm_review": llm_result,
        "llm_enabled": _client_ready(),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"AI Code Review Platform running on http://localhost:{port}")
    print(f"Gemini LLM review: {'ENABLED' if _client_ready() else 'DISABLED (set GEMINI_API_KEY to enable)'}")
    app.run(host="0.0.0.0", port=port, debug=debug)
