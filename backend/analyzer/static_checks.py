"""
Static analysis engine.

Runs language-aware checks against a code snippet:
- Python: AST-based bug checks + bandit (security) + pylint (bugs/quality) when available
- JS/TS, Java, Go, generic: regex-based heuristics for bugs, security issues, secrets
Every finding is normalized to:
    {
        "line": int | None,
        "severity": "critical" | "high" | "medium" | "low" | "info",
        "category": "bug" | "security" | "style" | "suggestion",
        "message": str,
        "tool": str
    }
"""
import ast
import json
import re
import subprocess
import sys
import tempfile
import os


# ---------------------------------------------------------------------------
# Generic, language-agnostic checks (secrets, TODOs, long lines, etc.)
# ---------------------------------------------------------------------------

SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[=:]\s*['\"][A-Za-z0-9\-_/+=]{8,}['\"]",
     "Possible hardcoded credential or secret"),
    (r"AKIA[0-9A-Z]{16}", "Possible AWS access key ID"),
    (r"-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----", "Embedded private key material"),
]

GENERIC_PATTERNS = [
    (r"\btodo\b|\bfixme\b", "low", "style", "Unresolved TODO/FIXME left in code"),
    (r"console\.log\(", "low", "style", "Leftover console.log / debug statement"),
    (r"\bprint\(", "info", "style", "Leftover print() statement (consider a logger)"),
    (r"\beval\(", "critical", "security", "Use of eval() can execute arbitrary code — major injection risk"),
    (r"\bexec\(", "high", "security", "Use of exec() can execute arbitrary code"),
    (r"innerHTML\s*=", "high", "security", "Direct innerHTML assignment can enable XSS if input is not sanitized"),
    (r"document\.write\(", "medium", "security", "document.write() is unsafe and can enable XSS"),
    (r"(?i)select\s+.*\s+from\s+.*(\+|%s|\{)", "high", "security",
     "SQL string built via concatenation/format — possible SQL injection, use parameterized queries"),
    (r"http://", "low", "security", "Insecure HTTP URL — prefer HTTPS"),
    (r"\bverify\s*=\s*False\b", "high", "security", "TLS certificate verification disabled"),
    (r"\bDEBUG\s*=\s*True\b", "medium", "security", "Debug mode enabled — should be off in production"),
]


def check_generic(code: str):
    findings = []
    lines = code.splitlines()
    for i, line in enumerate(lines, start=1):
        for pattern, msg in SECRET_PATTERNS:
            if re.search(pattern, line):
                findings.append({
                    "line": i, "severity": "critical", "category": "security",
                    "message": msg, "tool": "secret-scan"
                })
        for pattern, severity, category, msg in GENERIC_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "line": i, "severity": severity, "category": category,
                    "message": msg, "tool": "heuristic"
                })
        if len(line) > 120:
            findings.append({
                "line": i, "severity": "info", "category": "style",
                "message": f"Line exceeds 120 characters ({len(line)} chars)", "tool": "style"
            })
    return findings


# ---------------------------------------------------------------------------
# Python-specific: AST checks
# ---------------------------------------------------------------------------

class PythonAstChecker(ast.NodeVisitor):
    def __init__(self):
        self.findings = []

    def add(self, node, severity, category, message, tool="ast"):
        self.findings.append({
            "line": getattr(node, "lineno", None), "severity": severity,
            "category": category, "message": message, "tool": tool
        })

    def visit_ExceptHandler(self, node):
        if node.type is None:
            self.add(node, "medium", "bug", "Bare 'except:' catches every exception, including SystemExit/KeyboardInterrupt")
        elif isinstance(node.type, ast.Name) and node.type.id == "Exception" and not node.body:
            self.add(node, "low", "bug", "Exception is caught but silently ignored")
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        for default in node.args.defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.add(node, "medium", "bug",
                          f"Mutable default argument in function '{node.name}' — shared across calls, likely a bug")
        if len(node.body) > 60:
            self.add(node, "low", "suggestion",
                      f"Function '{node.name}' is very long ({len(node.body)} statements) — consider splitting it up")
        self.generic_visit(node)

    def visit_Compare(self, node):
        for op in node.ops:
            if isinstance(op, (ast.Is, ast.IsNot)):
                for side in (node.left, *node.comparators):
                    if isinstance(side, ast.Constant) and isinstance(side.value, (str, int, float)):
                        self.add(node, "low", "bug", "Use '==' to compare values, 'is' checks identity not equality")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
            self.add(node, "critical", "security", f"Use of {node.func.id}() allows arbitrary code execution")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format" and isinstance(node.func.value, ast.Str if hasattr(ast, "Str") else ast.Constant):
            pass
        self.generic_visit(node)

    def visit_Assert(self, node):
        self.add(node, "low", "suggestion", "assert statements are stripped when Python runs with -O, don't use for validation")
        self.generic_visit(node)


def check_python_ast(code: str):
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [{
            "line": e.lineno, "severity": "critical", "category": "bug",
            "message": f"SyntaxError: {e.msg}", "tool": "ast"
        }]
    checker = PythonAstChecker()
    checker.visit(tree)
    return checker.findings


def _tool_available(name: str) -> bool:
    from shutil import which
    return which(name) is not None


def run_bandit(filepath: str):
    findings = []
    if not _tool_available("bandit"):
        return findings
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "bandit", "-f", "json", "-q", filepath],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(proc.stdout or "{}")
        for r in data.get("results", []):
            sev = r.get("issue_severity", "MEDIUM").lower()
            findings.append({
                "line": r.get("line_number"),
                "severity": {"low": "low", "medium": "medium", "high": "high"}.get(sev, "medium"),
                "category": "security",
                "message": f"{r.get('test_name')}: {r.get('issue_text')}",
                "tool": "bandit"
            })
    except Exception:
        pass
    return findings


def run_pylint(filepath: str):
    findings = []
    if not _tool_available("pylint"):
        return findings
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pylint", "--output-format=json", "--disable=all",
             "--enable=E,W,C0301,W0611,W0612", filepath],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(proc.stdout or "[]")
        sev_map = {"error": "high", "warning": "medium", "convention": "low", "refactor": "low"}
        for r in data:
            findings.append({
                "line": r.get("line"),
                "severity": sev_map.get(r.get("type"), "low"),
                "category": "bug" if r.get("type") in ("error", "warning") else "style",
                "message": f"[{r.get('symbol')}] {r.get('message')}",
                "tool": "pylint"
            })
    except Exception:
        pass
    return findings


def analyze_python(code: str):
    findings = check_python_ast(code) + check_generic(code)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        findings += run_bandit(path)
        findings += run_pylint(path)
    finally:
        os.unlink(path)
    return findings


# ---------------------------------------------------------------------------
# JS / TS specific heuristics
# ---------------------------------------------------------------------------

JS_PATTERNS = [
    (r"\bvar\s+\w+", "low", "style", "Use 'let' or 'const' instead of 'var'"),
    (r"==(?!=)", "low", "bug", "Loose equality '==' used — prefer strict '===' to avoid type coercion bugs"),
    (r"\.then\(.*\.then\(.*\.then\(", "low", "suggestion", "Deeply chained .then() — consider async/await for readability"),
    (r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}", "medium", "bug", "Empty catch block silently swallows errors"),
]


def analyze_js(code: str):
    findings = check_generic(code)
    lines = code.splitlines()
    for i, line in enumerate(lines, start=1):
        for pattern, severity, category, msg in JS_PATTERNS:
            if re.search(pattern, line):
                findings.append({"line": i, "severity": severity, "category": category, "message": msg, "tool": "heuristic"})
    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_static_analysis(code: str, language: str):
    language = (language or "").lower()
    if language in ("python", "py"):
        findings = analyze_python(code)
    elif language in ("javascript", "js", "typescript", "ts", "jsx", "tsx"):
        findings = analyze_js(code)
    else:
        findings = check_generic(code)

    # de-duplicate identical findings
    seen = set()
    unique = []
    for f in findings:
        key = (f.get("line"), f.get("message"))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    unique.sort(key=lambda f: (severity_rank.get(f["severity"], 5), f.get("line") or 0))
    return unique
