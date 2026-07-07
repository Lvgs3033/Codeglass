// If this page is served by Flask (e.g. http://localhost:5000), API calls are same-origin.
// If it's served by something else (e.g. VS Code Live Server on :5500), point at the Flask backend explicitly.
const API_BASE = location.port === "5000" || location.port === "" ? "" : "http://127.0.0.1:5000";

const codeInput = document.getElementById("codeInput");
const lineGutter = document.getElementById("lineGutter");
const languageSelect = document.getElementById("languageSelect");
const analyzeBtn = document.getElementById("analyzeBtn");
const uploadBtn = document.getElementById("uploadBtn");
const fileInput = document.getElementById("fileInput");
const useLlmToggle = document.getElementById("useLlmToggle");
const errorMsg = document.getElementById("errorMsg");

const emptyState = document.getElementById("emptyState");
const resultsBody = document.getElementById("resultsBody");
const scoreNumber = document.getElementById("scoreNumber");
const gaugeFill = document.getElementById("gaugeFill");
const severityCounts = document.getElementById("severityCounts");
const findingsList = document.getElementById("findingsList");
const tabNav = document.getElementById("tabNav");
const aiPanel = document.getElementById("aiPanel");
const aiSummary = document.getElementById("aiSummary");
const aiGroups = document.getElementById("aiGroups");
const llmStatus = document.getElementById("llmStatus");
const clearBtn = document.getElementById("clearBtn");
const downloadPdfBtn = document.getElementById("downloadPdfBtn");

let lastFindings = [];
let lastAi = null;
let lastData = null;
let activeTab = "all";
let hasRunReview = false; // tracks whether output currently on screen belongs to the input currently in the editor

/* ---------------- line gutter sync ---------------- */
function updateGutter() {
  const lines = codeInput.value.split("\n").length;
  let out = "";
  for (let i = 1; i <= lines; i++) out += i + "\n";
  lineGutter.textContent = out;
}
codeInput.addEventListener("input", () => {
  updateGutter();
  if (hasRunReview) resetOutput(); // new input makes the previous review stale
});
codeInput.addEventListener("scroll", () => {
  lineGutter.scrollTop = codeInput.scrollTop;
});
updateGutter();

/* ---------------- clear button ---------------- */
clearBtn.addEventListener("click", clearAll);

function clearAll() {
  codeInput.value = "";
  fileInput.value = "";
  errorMsg.hidden = true;
  updateGutter();
  resetOutput();
  codeInput.focus();
}

function resetOutput() {
  hasRunReview = false;
  lastFindings = [];
  lastAi = null;
  lastData = null;
  activeTab = "all";
  tabNav.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === "all"));
  resultsBody.hidden = true;
  emptyState.hidden = false;
  gaugeFill.style.strokeDashoffset = 327;
  scoreNumber.textContent = "--";
  severityCounts.innerHTML = "";
  findingsList.innerHTML = "";
  aiSummary.innerHTML = "";
  aiGroups.innerHTML = "";
}

/* ---------------- file upload ---------------- */
uploadBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    codeInput.value = e.target.result;
    updateGutter();
    if (hasRunReview) resetOutput();
    const ext = file.name.split(".").pop().toLowerCase();
    const extMap = { py: "python", js: "javascript", ts: "typescript", jsx: "javascript", tsx: "typescript", java: "java", go: "go" };
    if (extMap[ext]) languageSelect.value = extMap[ext];
  };
  reader.readAsText(file);
});

/* ---------------- health check ---------------- */
async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    const data = await res.json();
    llmStatus.innerHTML = data.llm_enabled
      ? `<span class="dot dot-ok"></span> ai review enabled`
      : `<span class="dot dot-info"></span> static analysis only`;
  } catch {
    llmStatus.innerHTML = `<span class="dot dot-critical"></span> backend unreachable`;
  }
}
checkHealth();

/* ---------------- run review ---------------- */
analyzeBtn.addEventListener("click", runReview);

async function runReview() {
  const code = codeInput.value;
  errorMsg.hidden = true;
  if (!code.trim()) {
    errorMsg.textContent = "Paste or upload some code first.";
    errorMsg.hidden = false;
    return;
  }

  resetOutput(); // previous output should never linger once a new run starts
  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "Reviewing…";

  try {
    const res = await fetch(`${API_BASE}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code,
        language: languageSelect.value,
        use_llm: useLlmToggle.checked,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Analysis failed.");

    lastFindings = data.static_findings || [];
    lastAi = data.llm_review;
    lastData = data;
    hasRunReview = true;
    renderResults(data);
  } catch (err) {
    errorMsg.textContent = err.message;
    errorMsg.hidden = false;
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "Run review";
  }
}

/* ---------------- rendering ---------------- */
function renderResults(data) {
  emptyState.hidden = true;
  resultsBody.hidden = false;

  const circumference = 327;
  const offset = circumference - (data.score / 100) * circumference;
  gaugeFill.style.strokeDashoffset = offset;
  gaugeFill.style.stroke = data.score >= 80 ? "#4FD68C" : data.score >= 50 ? "#E8B65A" : "#F16B6B";
  scoreNumber.textContent = data.score;

  const c = data.counts || {};
  severityCounts.innerHTML = ["critical", "high", "medium", "low", "info"]
    .filter((s) => c[s])
    .map((s) => `<span class="count-item"><span class="dot dot-${s}"></span><b>${c[s]}</b> ${s}</span>`)
    .join("") || `<span class="count-item">No issues found by static analysis 🎉</span>`;

  renderFindings();
  renderAi(data);
}

function renderFindings() {
  const filtered = activeTab === "all" || activeTab === "ai"
    ? lastFindings
    : lastFindings.filter((f) => f.category === activeTab);

  findingsList.hidden = activeTab === "ai";
  aiPanel.hidden = activeTab !== "ai";

  if (activeTab === "ai") return;

  if (filtered.length === 0) {
    findingsList.innerHTML = `<div class="no-findings">No ${activeTab === "all" ? "" : activeTab + " "}findings here.</div>`;
    return;
  }

  findingsList.innerHTML = filtered.map((f) => `
    <div class="finding">
      <div class="finding-line">${f.line ? "L" + f.line : "—"}</div>
      <div class="finding-body">
        <p class="finding-msg">${escapeHtml(f.message)}</p>
        <div class="finding-meta">
          <span class="badge badge-${f.severity}">${f.severity}</span>
          <span>${f.category}</span>
          <span>· ${f.tool}</span>
        </div>
      </div>
    </div>
  `).join("");
}

function renderAi(data) {
  if (!data.llm_enabled) {
    aiSummary.innerHTML = "";
    aiGroups.innerHTML = `<div class="ai-disabled">AI review is disabled — no GEMINI_API_KEY is set on the server.
      Static analysis results above are still fully functional. See the README to enable it.</div>`;
    return;
  }
  const ai = data.llm_review;
  if (!ai) {
    aiGroups.innerHTML = `<div class="ai-disabled">AI review was skipped for this run.</div>`;
    return;
  }
  if (ai.error) {
    aiGroups.innerHTML = `<div class="ai-disabled">AI review failed: ${escapeHtml(ai.error)}</div>`;
    return;
  }

  aiSummary.textContent = ai.summary || "";
  const groups = [
    ["Bugs", ai.bugs],
    ["Security issues", ai.security_issues],
    ["Suggestions", ai.suggestions],
  ];
  aiGroups.innerHTML = groups
    .filter(([, items]) => items && items.length)
    .map(([title, items]) => `
      <div class="ai-group">
        <h3>${title}</h3>
        <ul>${items.map((i) => `<li>${i.line ? `<b>L${i.line}:</b> ` : ""}${escapeHtml(i.message)}</li>`).join("")}</ul>
      </div>
    `).join("") || `<div class="ai-disabled">The AI reviewer had nothing additional to add.</div>`;
}

/* ---------------- tabs ---------------- */
tabNav.addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (!btn) return;
  tabNav.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  btn.classList.add("active");
  activeTab = btn.dataset.tab;
  renderFindings();
});

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

/* ---------------- PDF export ---------------- */
downloadPdfBtn.addEventListener("click", downloadPdf);

function downloadPdf() {
  if (!lastData) return;
  if (typeof window.jspdf === "undefined") {
    errorMsg.textContent = "PDF library failed to load — check your internet connection and try again.";
    errorMsg.hidden = false;
    return;
  }

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const marginX = 48;
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  let y = 56;

  function ensureSpace(lineHeight = 16) {
    if (y + lineHeight > pageHeight - 48) {
      doc.addPage();
      y = 56;
    }
  }

  function writeWrapped(text, x, fontSize, style = "normal", lineHeight = 14, color = [20, 20, 20]) {
    doc.setFont("helvetica", style);
    doc.setFontSize(fontSize);
    doc.setTextColor(...color);
    const maxWidth = pageWidth - x - marginX;
    const lines = doc.splitTextToSize(text, maxWidth);
    lines.forEach((line) => {
      ensureSpace(lineHeight);
      doc.text(line, x, y);
      y += lineHeight;
    });
  }

  const severityColor = {
    critical: [200, 40, 40],
    high: [204, 90, 60],
    medium: [180, 130, 20],
    low: [50, 100, 190],
    info: [110, 110, 110],
  };

  // Header
  writeWrapped("Codeglass — Code Review Report", marginX, 18, "bold", 22, [15, 15, 15]);
  writeWrapped(`Language: ${lastData.language || "unknown"}    Generated: ${new Date().toLocaleString()}`, marginX, 10, "normal", 16, [100, 100, 100]);
  y += 8;

  // Score
  writeWrapped(`Overall score: ${lastData.score}/100`, marginX, 14, "bold", 20);

  const c = lastData.counts || {};
  const countLine = ["critical", "high", "medium", "low", "info"]
    .filter((s) => c[s])
    .map((s) => `${c[s]} ${s}`)
    .join("   ·   ") || "No static findings";
  writeWrapped(countLine, marginX, 10, "normal", 18, [90, 90, 90]);
  y += 6;

  // Static findings
  writeWrapped("Static analysis findings", marginX, 13, "bold", 20);
  if (!lastFindings.length) {
    writeWrapped("No issues found.", marginX, 10, "normal", 16, [90, 90, 90]);
  } else {
    lastFindings.forEach((f) => {
      ensureSpace(30);
      const lineTag = f.line ? `L${f.line}` : "—";
      const color = severityColor[f.severity] || [60, 60, 60];
      writeWrapped(`${lineTag}  [${f.severity.toUpperCase()} · ${f.category} · ${f.tool}]`, marginX, 9, "bold", 12, color);
      writeWrapped(f.message, marginX + 14, 10, "normal", 14, [30, 30, 30]);
      y += 4;
    });
  }

  // AI review
  y += 6;
  writeWrapped("AI review", marginX, 13, "bold", 20);
  if (!lastData.llm_enabled) {
    writeWrapped("AI review disabled — no GEMINI_API_KEY configured on the server.", marginX, 10, "normal", 16, [90, 90, 90]);
  } else if (!lastAi) {
    writeWrapped("AI review was not requested for this run.", marginX, 10, "normal", 16, [90, 90, 90]);
  } else if (lastAi.error) {
    writeWrapped(`AI review failed: ${lastAi.error}`, marginX, 10, "normal", 16, [90, 90, 90]);
  } else {
    if (lastAi.summary) {
      writeWrapped(lastAi.summary, marginX, 10, "italic", 14, [40, 40, 40]);
      y += 4;
    }
    [["Bugs", lastAi.bugs], ["Security issues", lastAi.security_issues], ["Suggestions", lastAi.suggestions]]
      .filter(([, items]) => items && items.length)
      .forEach(([title, items]) => {
        ensureSpace(20);
        writeWrapped(title, marginX, 11, "bold", 16);
        items.forEach((item) => {
          const prefix = item.line ? `L${item.line}: ` : "";
          writeWrapped(`•  ${prefix}${item.message}`, marginX + 10, 10, "normal", 14, [30, 30, 30]);
        });
        y += 2;
      });
  }

  doc.save(`codeglass-review-${Date.now()}.pdf`);
}
