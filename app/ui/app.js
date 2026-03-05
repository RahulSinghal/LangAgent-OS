const API_PREFIX = "/api/v1";

function el(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing element: ${id}`);
  return node;
}

function getShell() {
  const node = document.querySelector(".shell");
  if (!node) throw new Error("Missing .shell root");
  return node;
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function addMessage(role, text, isoTime) {
  const wrap = el("messages");

  const msgWrap = document.createElement("div");
  msgWrap.className = `msgWrap ${role}`;

  // Role + time meta row
  const meta = document.createElement("div");
  meta.className = "msgMeta";
  const roleLabel = document.createElement("span");
  roleLabel.className = "msgRole";
  roleLabel.textContent = role === "user" ? "You" : role === "error" ? "Error" : "Agent";
  meta.appendChild(roleLabel);
  if (isoTime) {
    const t = document.createElement("span");
    t.className = "msgTime";
    t.textContent = fmtTime(isoTime);
    meta.appendChild(t);
  }
  msgWrap.appendChild(meta);

  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  msgWrap.appendChild(div);

  wrap.appendChild(msgWrap);
  wrap.scrollTop = wrap.scrollHeight;
}

function showDashboardError(err) {
  const msg = String(err?.message || err || "Unknown error");
  const box = el("dashboardTable");
  box.innerHTML = `<div class="msg error" style="max-width:100%">${escapeHtml(msg)}</div>`;
}

// ── Status pill / badge helpers ────────────────────────────────────────────

function pillClass(state) {
  if (!state) return "";
  const s = String(state).toLowerCase();
  if (s === "running" || s === "started")                                return "pill-running";
  if (s === "waiting_approval" || s === "paused" || s === "pending")    return "pill-waiting";
  if (s === "completed" || s === "done" || s === "finished")            return "pill-done";
  if (s === "error" || s === "failed")                                  return "pill-error";
  return "";
}

function statusBadgeClass(state) {
  const s = String(state || "").toLowerCase();
  if (s === "running" || s === "started")                             return "status-running";
  if (s === "waiting_approval" || s === "paused" || s === "pending")  return "status-waiting";
  if (s === "completed" || s === "done" || s === "finished")          return "status-done";
  if (s === "error" || s === "failed")                                return "status-error";
  return "";
}

function showVisibleError(err) {
  try {
    const isDashboardVisible = !el("dashboardView").classList.contains("hidden");
    if (isDashboardVisible) {
      showDashboardError(err);
      return;
    }
  } catch {
    // ignore
  }
  addMessage("error", String(err?.message || err || "Unknown error"));
}

function clearMessages() {
  el("messages").innerHTML = "";
}

function uiRoleFromMessageRole(role) {
  if (role === "user") return "user";
  if (role === "assistant") return "system";
  if (role === "system") return "system";
  return "system";
}

async function api(path, opts = {}) {
  const res = await fetch(`${API_PREFIX}${path}`, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data?.detail || res.statusText || "Request failed";
    throw new Error(`${res.status} ${detail}`);
  }
  return data;
}

async function apiMultipart(path, formData) {
  const res = await fetch(`${API_PREFIX}${path}`, { method: "POST", body: formData });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data?.detail || res.statusText || "Upload failed";
    throw new Error(`${res.status} ${detail}`);
  }
  return data;
}

async function refreshModeBadge() {
  try {
    const s = await api(`/system/status`, { method: "GET" });
    const mode = s?.agent_mode || "—";
    const provider = (s?.llm_provider || "").toLowerCase();
    const model = s?.llm_model || "";
    const validity = s?.llm_key_validity || "unknown";
    const reason = s?.reason || "";

    const label =
      mode === "real"
        ? `Mode: Real (${provider || "llm"})`
        : `Mode: Mock`;
    const detail =
      mode === "real"
        ? `provider=${provider} model=${model} key=${validity}`
        : `reason=${reason || "n/a"}`;

    const mb = el("modeBadge");
    mb.textContent = label;
    mb.title = detail;
    mb.className = `badge ${mode === "real" ? "status-done" : ""}`;
  } catch {
    // ignore
  }
}

function setMeta({ runId, status, node, phase, approvalId, projectType }) {
  const s = getState();
  const projectName = s.projectName || "—";
  el("projectLabel").textContent = projectName;
  const badge = el("runStatus");
  badge.textContent = status || "idle";
  badge.className = "statusBadge " + statusBadgeClass(status);
  el("runIdLabel").textContent = `run: ${runId ?? "—"}`;
  el("nodeLabel").textContent  = `node: ${node ?? "—"}`;
  el("phaseLabel").textContent = `phase: ${phase ?? "—"}`;
  el("approvalLabel").textContent = `approval: ${approvalId ?? "—"}`;
  el("projectTypeLabel").textContent = `type: ${projectType ?? "—"}`;
}

function getState() {
  window.__state = window.__state || {
    projectId: null,
    projectName: null,
    sessionId: null,
    runId: null,
  };
  return window.__state;
}

function getIds() {
  const s = getState();
  return { projectId: s.projectId, sessionId: s.sessionId, runId: s.runId };
}

function setRunId(runId) {
  getState().runId = runId;
}

function setProjectId(projectId) {
  getState().projectId = projectId;
}

function setProjectName(projectName) {
  getState().projectName = projectName;
}

function setSessionId(sessionId) {
  getState().sessionId = sessionId;
}

function showDashboard() {
  el("dashboardView").classList.remove("hidden");
  el("chatView").classList.add("hidden");
  el("sidePanel").classList.add("hidden");
}

function showChat() {
  el("dashboardView").classList.add("hidden");
  el("chatView").classList.remove("hidden");
  el("sidePanel").classList.remove("hidden");
}

function fmtMoney(x) {
  const v = Number(x || 0);
  return `$${v.toFixed(4)}`;
}

function fmtHours(x) {
  const v = Number(x || 0);
  if (v < 0.01) return "<0.01h";
  return `${v.toFixed(2)}h`;
}

function fmtWhen(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60)           return "just now";
  if (sec < 3600)         return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400)        return `${Math.floor(sec / 3600)}h ago`;
  if (sec < 86400 * 7)    return `${Math.floor(sec / 86400)}d ago`;
  if (sec < 86400 * 30)   return `${Math.floor(sec / 604800)}w ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function openArtifactInNewTab(artifactId, title) {
  const content = await api(`/artifacts/${artifactId}/content`, { method: "GET" });
  const w = window.open("", "_blank");
  if (!w) return;
  w.document.title = title || `Artifact ${artifactId}`;
  w.document.body.innerHTML = `<pre style="white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;">${escapeHtml(
    content?.content || ""
  )}</pre>`;
}

async function loadProjectFromDashboard(row) {
  setProjectId(Number(row.project_id));
  setProjectName(row.name || `Project ${row.project_id}`);
  setSessionId(null);
  setRunId(row.latest_run_id || null);
  clearMessages();
  showChat();
  await loadHistory();
  if (row.latest_run_id) {
    await refreshContext();
  } else {
    setMeta({ runId: null, status: "idle", node: null, phase: null, approvalId: null });
    el("nextQuestion").textContent = "—";
    el("pendingApprovals").textContent = "—";
    el("artifacts").textContent = "—";
  }
  loadEvalReport(Number(row.project_id)).catch(() => {});
}

async function refreshDashboard() {
  const box = el("dashboardTable");
  try {
    const data = await api(`/projects/dashboard`, { method: "GET" });
    const rows = data?.projects || [];
    if (!rows.length) {
      box.innerHTML = `
        <div style="text-align:center;padding:48px 16px;color:var(--muted)">
          <div style="font-size:32px;margin-bottom:12px;opacity:0.3">&#x25A6;</div>
          <div style="font-weight:700;margin-bottom:6px;color:var(--text)">No projects yet</div>
          <div style="font-size:13px">Click <strong>+ New project</strong> to get started.</div>
        </div>`;
      return;
    }

    const table = document.createElement("table");
    table.className = "table";
    table.innerHTML = `
      <thead>
        <tr>
          <th>Project</th>
          <th>Type</th>
          <th>State</th>
          <th>Artifacts</th>
          <th>Approvals</th>
          <th>Eval cov.</th>
          <th>Tokens</th>
          <th>Cost</th>
          <th>Runtime</th>
          <th>Last activity</th>
        </tr>
      </thead>
      <tbody></tbody>`;

    const tbody = table.querySelector("tbody");
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.title = "Click to open project";
      const artifacts = r.artifacts || {};

      const shownArtifactKeys = ["brd", "prd", "sow", "user_guide", "server_details_client", "server_details_infra", "input_document", "github_repo"]
        .filter((k) => artifacts[k])
        .slice(0, 5);

      const artifactHtml = shownArtifactKeys.length
        ? shownArtifactKeys.map((k) => {
            const a = artifacts[k];
            const label = k === "user_guide" ? "guide" : k;
            return `<button class="linkBtn" data-artifact="${a.id}" data-title="${k} v${a.version}">${label}</button>`;
          }).join(" · ")
        : '<span class="subtle">—</span>';

      const covPct = r.eval_coverage_pct;
      const covHtml = covPct == null
        ? '<span class="subtle">—</span>'
        : `<span class="evalCovBadge ${covPct >= 80 ? "evalOk" : covPct >= 40 ? "evalWarn" : "evalBad"}">${covPct}%</span>`;

      const stateLabel = r.current_state || "idle";
      const pcls = pillClass(r.run_status || r.current_state);
      const pending = Number(r.pending_approvals || 0);
      const ptype = r.project_type || "generic";
      const ptypeLabel = { rag_pipeline: "RAG", web_app: "Web", crm: "CRM", voice_chatbot: "Voice", generic: "—" }[ptype] || ptype;

      tr.innerHTML = `
        <td><strong>${escapeHtml(r.name)}</strong></td>
        <td><span class="mono" style="font-size:11px">${escapeHtml(ptypeLabel)}</span></td>
        <td><span class="pill ${pcls}">${escapeHtml(stateLabel)}</span></td>
        <td class="mono" style="font-size:12px">${artifactHtml}</td>
        <td><span class="pill ${pending > 0 ? "pill-waiting" : ""}">${pending} pending</span></td>
        <td>${covHtml}</td>
        <td class="mono">${Number(r.tokens_spent || 0).toLocaleString()}</td>
        <td class="mono">${fmtMoney(r.cost_usd || 0)}</td>
        <td class="mono">${fmtHours(r.system_hours || 0)}</td>
        <td class="mono">${fmtWhen(r.last_activity_at)}</td>`;

      // Entire row click loads the project
      tr.addEventListener("click", async (e) => {
        // Don't trigger on artifact link-btn clicks
        if (e.target.closest("[data-artifact]")) return;
        try {
          await loadProjectFromDashboard(r);
        } catch (err) {
          showVisibleError(err);
        }
      });

      tbody.appendChild(tr);
    }

    box.innerHTML = "";
    box.appendChild(table);

    box.querySelectorAll("[data-artifact]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = Number(btn.getAttribute("data-artifact"));
        const title = btn.getAttribute("data-title") || `Artifact ${id}`;
        try {
          await openArtifactInNewTab(id, title);
        } catch (err) {
          showVisibleError(err);
        }
      });
    });
  } catch (e) {
    showDashboardError(e);
  }
}

function showAttachmentChip(filename) {
  const chip = el("attachmentChip");
  chip.classList.remove("hidden");
  chip.innerHTML = "";

  const span = document.createElement("span");
  span.textContent = `Attached: ${filename}`;
  const btn = document.createElement("button");
  btn.textContent = "×";
  btn.title = "Remove attachment";
  btn.addEventListener("click", () => {
    chip.classList.add("hidden");
    el("documentText").value = "";
  });

  chip.appendChild(span);
  chip.appendChild(btn);
}

async function refreshContext() {
  const { runId } = getIds();
  if (!runId) return;

  const run = await api(`/runs/${runId}`, { method: "GET" });
  const sotWrap = await api(`/runs/${runId}/sot`, { method: "GET" });
  const { projectId } = getIds();

  let approvals = [];
  try {
    approvals = await api(`/runs/${runId}/approvals`, { method: "GET" });
  } catch {
    approvals = [];
  }
  const approvalId = approvals?.[0]?.id ?? null;

  const phase = sotWrap?.sot?.current_phase ?? null;
  const unanswered = (sotWrap?.unanswered_questions || []);
  const nextQ = unanswered.length ? unanswered[unanswered.length - 1] : null;

  const sot = sotWrap?.sot || {};
  const projectType = sot.project_type ?? null;

  setMeta({
    runId,
    status: run?.status,
    node: run?.current_node,
    phase,
    approvalId,
    projectType,
  });

  // QA audit flags (from QAAuditorAgent) are prefixed with [PRD QA] or [SOW QA].
  // Display them in a separate card so they don't drown out discovery questions.
  const qaFlags = unanswered.filter(q => /^\[(PRD|SOW) QA\]/.test(q));
  const discoveryQs = unanswered.filter(q => !/^\[(PRD|SOW) QA\]/.test(q));
  const nextDiscoveryQ = discoveryQs.length ? discoveryQs[discoveryQs.length - 1] : null;

  el("nextQuestion").textContent = nextDiscoveryQ || "—";
  const nqCard = document.getElementById("cardNextQuestion");
  if (nqCard) {
    nqCard.classList.toggle("card-warn", !!nextDiscoveryQ);
  }

  // QA Audit flags card (only shown when flags exist)
  const qaCard = document.getElementById("cardQaAudit");
  const qaBody = document.getElementById("qaAuditBody");
  if (qaCard && qaBody) {
    if (!qaFlags.length) {
      qaCard.classList.add("hidden");
    } else {
      qaCard.classList.remove("hidden");
      qaCard.classList.toggle("card-warn", true);
      qaBody.innerHTML = "";
      for (const flag of qaFlags) {
        const d = document.createElement("div");
        d.className = "qaFlag";
        d.textContent = flag.replace(/^\[(PRD|SOW) QA\]\s*/, "");
        qaBody.appendChild(d);
      }
    }
  }

  // Workflow stepper (phases + substates)
  if (projectId) {
    try {
      const g = await api(`/projects/${projectId}/state_graph`, { method: "GET" });
      window.__lastGraph = g;
      renderWorkflowStepper(g);
    } catch {
      // ignore
    }
  }

  // Pending approvals list (UI)
  const pendingBox = el("pendingApprovals");
  const approvalCard = document.getElementById("cardApproval");
  if (!approvals.length) {
    pendingBox.textContent = "—";
    approvalCard?.classList.remove("card-active");
  } else {
    pendingBox.innerHTML = "";
    for (const a of approvals) {
      const btn = document.createElement("button");
      btn.className = "btn secondary pendingBtn";
      btn.textContent = `#${a.id} · ${a.type} · ${a.status}`;
      btn.addEventListener("click", () => {
        pendingBox.querySelectorAll(".pendingBtn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        window.__selectedApprovalId = a.id;
      });
      pendingBox.appendChild(btn);
    }
    window.__selectedApprovalId = approvals[0].id;
    pendingBox.querySelector(".pendingBtn")?.classList.add("active");
    approvalCard?.classList.add("card-active");
  }

  const artifactsProjectId = run?.project_id;

  // Refresh eval report silently
  if (artifactsProjectId) {
    loadEvalReport(artifactsProjectId).catch(() => {});
  }

  if (artifactsProjectId) {
    const artifactList = await api(`/projects/${artifactsProjectId}/artifacts`, { method: "GET" });
    const artifacts = artifactList?.artifacts || [];
    const box = el("artifacts");
    const artifactCard = document.getElementById("cardArtifacts");
    if (!artifacts.length) {
      box.textContent = "—";
      artifactCard?.classList.remove("card-ok");
    } else {
      box.innerHTML = "";
      for (const a of artifacts.slice(0, 6)) {
        const btn = document.createElement("button");
        btn.className = "artifactBtn";
        btn.textContent = `${a.type}  v${a.version}`;
        btn.addEventListener("click", async () => {
          try {
            const content = await api(`/artifacts/${a.id}/content`, { method: "GET" });
            addMessage("system", `[${a.type} v${a.version}]\n\n${content?.content || ""}`, new Date().toISOString());
          } catch (err) {
            addMessage("error", String(err.message || err), new Date().toISOString());
          }
        });
        box.appendChild(btn);
      }
      artifactCard?.classList.add("card-ok");
    }
  }

  // Readiness checklist card
  renderReadinessChecklist(sot);

  // Architecture spec card
  renderArchitectureCard(sot);

  // Code review card
  renderCodeReviewCard(sot);

  // GitHub publish card (only in readiness / completed phases)
  if (artifactsProjectId) {
    refreshGithubCard(artifactsProjectId, phase).catch(() => {});
  }
}

function renderReadinessChecklist(sot) {
  const card = document.getElementById("cardReadiness");
  const body = document.getElementById("readinessBody");
  if (!card || !body) return;

  const checklist = sot.readiness_checklist || [];
  const phase = sot.current_phase || "";

  // Only show during readiness phase or when checklist exists
  if (!checklist.length && phase !== "readiness") {
    card.classList.add("hidden");
    return;
  }

  card.classList.remove("hidden");
  body.innerHTML = "";

  if (!checklist.length) {
    body.textContent = "Generating checklist…";
    return;
  }

  const byCategory = {};
  for (const item of checklist) {
    const cat = item.category || "general";
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(item);
  }

  for (const [cat, items] of Object.entries(byCategory)) {
    const catDiv = document.createElement("div");
    catDiv.className = "readinessCategory";

    const catLabel = document.createElement("div");
    catLabel.className = "readinessCatLabel";
    catLabel.textContent = cat.replace(/_/g, " ").toUpperCase();
    catDiv.appendChild(catLabel);

    for (const item of items) {
      const row = document.createElement("div");
      row.className = `readinessItem readiness-${item.status || "pending"}`;
      const icon = item.status === "done" ? "✓" : item.status === "n/a" ? "—" : "○";
      row.innerHTML = `<span class="readinessIcon">${icon}</span><span class="readinessText">${escapeHtml(item.item)}</span><span class="readinessOwner">${escapeHtml(item.owner || "")}</span>`;
      catDiv.appendChild(row);
    }
    body.appendChild(catDiv);
  }

  // Summary badge
  const done = checklist.filter(i => i.status === "done").length;
  const total = checklist.length;
  const cardTitle = card.querySelector(".cardTitle");
  if (cardTitle) {
    const existing = cardTitle.querySelector(".readinessBadge");
    if (existing) existing.remove();
    const badge = document.createElement("span");
    badge.className = "readinessBadge " + (done === total ? "evalOk" : done > 0 ? "evalWarn" : "evalBad");
    badge.textContent = `${done}/${total}`;
    cardTitle.appendChild(badge);
  }
}

function renderArchitectureCard(sot) {
  const card = document.getElementById("cardArchitecture");
  const body = document.getElementById("architectureBody");
  if (!card || !body) return;

  const arch = sot.architecture_spec;
  const phase = sot.current_phase || "";
  if (!arch || !["coding", "milestone", "readiness", "completed"].includes(phase)) {
    card.classList.add("hidden");
    return;
  }

  card.classList.remove("hidden");
  body.innerHTML = "";

  const style = document.createElement("div");
  style.className = "archStyle";
  style.innerHTML = `<strong>Style:</strong> ${escapeHtml(arch.style || "layered")}`;
  body.appendChild(style);

  if (arch.file_tree && arch.file_tree.length) {
    const treeLabel = document.createElement("div");
    treeLabel.className = "archSectionLabel";
    treeLabel.textContent = `File tree (${arch.file_tree.length} files)`;
    body.appendChild(treeLabel);

    const treeList = document.createElement("div");
    treeList.className = "archFileTree mono";
    treeList.textContent = arch.file_tree.slice(0, 20).join("\n") + (arch.file_tree.length > 20 ? "\n…" : "");
    body.appendChild(treeList);
  }

  if (arch.api_contracts && arch.api_contracts.length) {
    const apiLabel = document.createElement("div");
    apiLabel.className = "archSectionLabel";
    apiLabel.textContent = `API contracts (${arch.api_contracts.length})`;
    body.appendChild(apiLabel);
    for (const c of arch.api_contracts.slice(0, 5)) {
      const row = document.createElement("div");
      row.className = "archApiRow mono";
      row.textContent = `${c.method || "GET"} ${c.path || "/"}`;
      body.appendChild(row);
    }
  }
}

function renderCodeReviewCard(sot) {
  const card = document.getElementById("cardCodeReview");
  const body = document.getElementById("codeReviewBody");
  if (!card || !body) return;

  const plan = sot.coding_plan || [];
  const idx = sot.current_milestone_index ?? 0;
  const milestone = plan[idx];
  const feedback = milestone?.review_feedback;
  const phase = sot.current_phase || "";

  if (!feedback || !["milestone", "readiness", "completed"].includes(phase)) {
    card.classList.add("hidden");
    return;
  }

  card.classList.remove("hidden");
  const isBlock = feedback.includes("**Severity**: block");
  const isWarn = feedback.includes("**Severity**: warn");
  card.classList.toggle("card-warn", isBlock || isWarn);

  body.innerHTML = "";
  const lines = feedback.split("\n");
  for (const line of lines) {
    const div = document.createElement("div");
    div.className = line.startsWith("[CRITICAL]") ? "reviewCritical" : line.startsWith("[WARN]") ? "reviewWarn" : "reviewInfo";
    div.textContent = line;
    body.appendChild(div);
  }
}

async function refreshGithubCard(projectId, phase) {
  const card = document.getElementById("cardGithub");
  const linkDiv = document.getElementById("githubLink");
  if (!card || !linkDiv) return;

  // Only show in readiness or completed phases
  if (phase !== "readiness" && phase !== "completed") {
    card.classList.add("hidden");
    return;
  }

  try {
    const status = await api(`/projects/${projectId}/publish/github`, { method: "GET" });
    if (!status.enabled) {
      card.classList.add("hidden");
      return;
    }
    card.classList.remove("hidden");
    if (status.repo_url) {
      linkDiv.classList.remove("hidden");
      linkDiv.innerHTML = `<a href="${escapeHtml(status.repo_url)}" target="_blank" class="githubLink">${escapeHtml(status.repo_url)}</a>`;
    } else {
      linkDiv.classList.add("hidden");
    }
  } catch {
    card.classList.add("hidden");
  }
}

function renderWorkflowStepper(graph) {
  const box = el("workflowStepper");
  const phases = graph?.phases || [];
  const details = graph?.details || {};
  const sot = details?.sot || {};
  const approvals = details?.approvals || {};
  const pendingTotal = Number(approvals?.pending_total || 0);
  const unanswered = Number(sot?.unanswered_questions || 0);

  box.innerHTML = "";
  for (const p of phases) {
    const div = document.createElement("div");
    div.className = `step ${p.status || ""}`.trim();

    const label = document.createElement("span");
    label.textContent = p.id;
    div.appendChild(label);

    // Substate badges on the current phase (and discovery)
    if (p.id === "discovery" && unanswered > 0) {
      const b = document.createElement("span");
      b.className = "badgeMini";
      b.textContent = `${unanswered} questions`;
      div.appendChild(b);
    }
    if (p.status === "current" && pendingTotal > 0) {
      const b = document.createElement("span");
      b.className = "badgeMini";
      b.textContent = `${pendingTotal} approvals`;
      div.appendChild(b);
    }

    box.appendChild(div);
  }

  renderWorkflowDiagram(graph);
}

// Node → phase mapping for gate detection
const _GATE_PHASE_MAP = {
  market_eval_gate:  "market_eval",
  prd_gate:          "prd",
  commercials_gate:  "commercials",
  sow_gate:          "sow",
  coding_plan_gate:  "coding",
  milestone_gate:    "milestone",
  readiness_gate:    "readiness",
};

// Phases with their display labels and whether they have a gate
const _PHASE_CONFIG = [
  { id: "init",        label: "INIT",       hasGate: false },
  { id: "discovery",   label: "DISCOVERY",  hasGate: false },
  { id: "market_eval", label: "MKT EVAL",   hasGate: true  },
  { id: "prd",         label: "PRD",        hasGate: true  },
  { id: "commercials", label: "COMMERCIALS", hasGate: true  },
  { id: "sow",         label: "SOW",        hasGate: true  },
  { id: "user_guide",  label: "USER GUIDE", hasGate: false },
  { id: "coding",      label: "CODING",     hasGate: true  },
  { id: "milestone",   label: "MILESTONE",  hasGate: true  },
  { id: "readiness",   label: "READINESS",  hasGate: true  },
  { id: "completed",   label: "DONE",       hasGate: false },
];

function renderWorkflowDiagram(graph) {
  const container = document.getElementById("workflowDiagram");
  if (!container || container.classList.contains("hidden")) return;

  const phases = graph?.phases || [];
  const details = graph?.details || {};
  const currentNode = details?.run?.current_node || "";
  const rejectionFeedback = details?.sot?.rejection_feedback || null;
  const unanswered = Number(details?.sot?.unanswered_questions || 0);
  const pendingTotal = Number(details?.approvals?.pending_total || 0);

  // Status lookup by phase id
  const statusMap = {};
  for (const p of phases) statusMap[p.id] = p.status || "pending";

  // Which phase's gate is currently the active node?
  const activeGatePhase = _GATE_PHASE_MAP[currentNode] || null;

  const N = _PHASE_CONFIG.length;
  const W = 900;
  // Height depends on whether any phase has gates
  const hasGates = _PHASE_CONFIG.some(p => p.hasGate);
  const H = hasGates ? 130 : 80;
  const phaseY = 40;
  const gateY = 90;
  const labelY = H - 8;
  const nodeR = 14;
  const gateHalf = 9;

  // Evenly spaced x positions
  const xs = _PHASE_CONFIG.map((_, i) => Math.round(32 + i * ((W - 64) / (N - 1))));

  // Color helpers
  const COL_PASS_FILL   = "rgba(34,197,94,0.18)";
  const COL_PASS_STROKE = "rgba(34,197,94,0.70)";
  const COL_PASS_TEXT   = "rgba(34,197,94,0.90)";
  const COL_CUR_FILL    = "rgba(124,92,255,0.25)";
  const COL_CUR_STROKE  = "rgba(124,92,255,0.90)";
  const COL_CUR_TEXT    = "rgba(255,255,255,0.95)";
  const COL_PEND_FILL   = "rgba(15,23,48,0.50)";
  const COL_PEND_STROKE = "rgba(255,255,255,0.18)";
  const COL_PEND_TEXT   = "rgba(170,180,226,0.45)";

  function nodeColors(st, isCurMain) {
    if (isCurMain) return [COL_CUR_FILL, COL_CUR_STROKE, COL_CUR_TEXT];
    if (st === "passed") return [COL_PASS_FILL, COL_PASS_STROKE, COL_PASS_TEXT];
    if (st === "current") return [COL_PASS_FILL, COL_PASS_STROKE, COL_PASS_TEXT]; // at gate, phase done
    return [COL_PEND_FILL, COL_PEND_STROKE, COL_PEND_TEXT];
  }

  let s = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block">`;

  // Arrowhead markers
  s += `<defs>
    <marker id="wf-arr-p" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
      <path d="M0,0 L0,6 L6,3z" fill="rgba(34,197,94,0.55)"/></marker>
    <marker id="wf-arr-c" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
      <path d="M0,0 L0,6 L6,3z" fill="rgba(124,92,255,0.75)"/></marker>
    <marker id="wf-arr-n" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
      <path d="M0,0 L0,6 L6,3z" fill="rgba(170,180,226,0.30)"/></marker>
    <marker id="wf-arr-r" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
      <path d="M0,0 L0,6 L6,3z" fill="rgba(239,68,68,0.65)"/></marker>
  </defs>`;

  // Horizontal arrows between phase nodes
  for (let i = 0; i < N - 1; i++) {
    const x1 = xs[i] + nodeR + 2;
    const x2 = xs[i + 1] - nodeR - 4;
    const st = statusMap[_PHASE_CONFIG[i].id];
    const nst = statusMap[_PHASE_CONFIG[i + 1].id];
    let markerId, stroke;
    if ((st === "passed" || st === "current") && nst === "current") {
      markerId = "wf-arr-c"; stroke = "rgba(124,92,255,0.45)";
    } else if (st === "passed" && nst === "passed") {
      markerId = "wf-arr-p"; stroke = "rgba(34,197,94,0.40)";
    } else {
      markerId = "wf-arr-n"; stroke = "rgba(170,180,226,0.18)";
    }
    s += `<line x1="${x1}" y1="${phaseY}" x2="${x2}" y2="${phaseY}" stroke="${stroke}" stroke-width="1.5" marker-end="url(#${markerId})"/>`;
  }

  // Vertical dashed lines from phase node down to gate diamond
  for (let i = 0; i < N; i++) {
    const p = _PHASE_CONFIG[i];
    if (!p.hasGate) continue;
    const st = statusMap[p.id];
    const gateActive = activeGatePhase === p.id;
    const stroke = gateActive
      ? "rgba(124,92,255,0.55)"
      : (st === "passed" || st === "current") ? "rgba(34,197,94,0.28)" : "rgba(170,180,226,0.12)";
    s += `<line x1="${xs[i]}" y1="${phaseY + nodeR + 1}" x2="${xs[i]}" y2="${gateY - gateHalf - 1}" stroke="${stroke}" stroke-width="1" stroke-dasharray="3,2"/>`;
  }

  // Gate diamonds
  for (let i = 0; i < N; i++) {
    const p = _PHASE_CONFIG[i];
    if (!p.hasGate) continue;
    const x = xs[i];
    const y = gateY;
    const g = gateHalf;
    const st = statusMap[p.id];
    const gateActive = activeGatePhase === p.id;
    let fill, stroke, textFill;
    if (gateActive) {
      fill = "rgba(124,92,255,0.28)"; stroke = "rgba(124,92,255,0.90)"; textFill = "rgba(255,255,255,0.90)";
    } else if (st === "passed" || (st === "current" && !gateActive)) {
      fill = "rgba(34,197,94,0.15)"; stroke = "rgba(34,197,94,0.55)"; textFill = "rgba(34,197,94,0.85)";
    } else {
      fill = "rgba(15,23,48,0.50)"; stroke = "rgba(255,255,255,0.14)"; textFill = "rgba(170,180,226,0.35)";
    }
    const pts = `${x},${y - g} ${x + g},${y} ${x},${y + g} ${x - g},${y}`;
    const cls = gateActive ? "wf-gate-pulse" : "";
    s += `<polygon points="${pts}" fill="${fill}" stroke="${stroke}" stroke-width="1.5" class="${cls}"/>`;
    s += `<text x="${x}" y="${y + 3}" text-anchor="middle" font-size="8" fill="${textFill}">✓</text>`;
  }

  // Rejection loop arc (from gate back to phase node, red dashed)
  if (rejectionFeedback && activeGatePhase) {
    const idx = _PHASE_CONFIG.findIndex(p => p.id === activeGatePhase);
    if (idx >= 0) {
      const gx = xs[idx];
      const cx = gx + 28;
      const cy = gateY + 20;
      s += `<path d="M ${gx + gateHalf} ${gateY} Q ${cx} ${cy} ${gx} ${phaseY + nodeR}" fill="none" stroke="rgba(239,68,68,0.55)" stroke-width="1.5" stroke-dasharray="4,2" marker-end="url(#wf-arr-r)"/>`;
      s += `<text x="${cx + 4}" y="${cy + 10}" font-size="9" fill="rgba(239,68,68,0.70)" font-family="monospace">rejected</text>`;
    }
  }

  // Phase circles
  for (let i = 0; i < N; i++) {
    const p = _PHASE_CONFIG[i];
    const x = xs[i];
    const st = statusMap[p.id] || "pending";
    // Main node is active when phase is "current" AND we're not sitting in its gate
    const isCurMain = st === "current" && activeGatePhase !== p.id;
    const [fill, stroke, textFill] = nodeColors(st, isCurMain);
    const cls = isCurMain ? "wf-node-pulse" : "";
    const sw = isCurMain ? "2" : "1.5";

    s += `<circle cx="${x}" cy="${phaseY}" r="${nodeR}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" class="${cls}"/>`;

    // Inner icon
    if (st === "passed" || (st === "current" && activeGatePhase === p.id)) {
      s += `<text x="${x}" y="${phaseY + 4}" text-anchor="middle" font-size="11" fill="${textFill}">✓</text>`;
    } else if (isCurMain) {
      s += `<circle cx="${x}" cy="${phaseY}" r="4" fill="rgba(124,92,255,0.9)" class="wf-dot-pulse"/>`;
    } else {
      s += `<circle cx="${x}" cy="${phaseY}" r="3" fill="${textFill}"/>`;
    }

    // Discovery unanswered Q badge
    if (p.id === "discovery" && unanswered > 0 && st === "current") {
      s += `<circle cx="${x + nodeR - 2}" cy="${phaseY - nodeR + 2}" r="7" fill="rgba(239,68,68,0.85)" stroke="rgba(15,23,48,0.9)" stroke-width="1"/>`;
      s += `<text x="${x + nodeR - 2}" y="${phaseY - nodeR + 6}" text-anchor="middle" font-size="8" fill="white" font-weight="700">${unanswered}</text>`;
    }

    // Pending approvals badge on gate
    if (p.hasGate && activeGatePhase === p.id && pendingTotal > 0) {
      s += `<circle cx="${xs[i] + gateHalf + 2}" cy="${gateY - gateHalf - 2}" r="7" fill="rgba(239,68,68,0.85)" stroke="rgba(15,23,48,0.9)" stroke-width="1"/>`;
      s += `<text x="${xs[i] + gateHalf + 2}" y="${gateY - gateHalf + 2}" text-anchor="middle" font-size="8" fill="white" font-weight="700">${pendingTotal}</text>`;
    }

    // Phase label
    s += `<text x="${x}" y="${labelY}" text-anchor="middle" font-size="9" font-family="monospace" fill="${textFill}" font-weight="${(st === "current") ? "700" : "400"}">${p.label}</text>`;
  }

  s += "</svg>";
  container.innerHTML = s;
}

// ── Eval Coverage ─────────────────────────────────────────────────────────────

async function loadEvalReport(projectId) {
  const badge = document.getElementById("evalSummaryBadge");
  const body  = document.getElementById("evalCoverageBody");
  if (!badge || !body) return;

  badge.textContent = "…";
  body.textContent  = "";

  let report;
  try {
    report = await api(`/projects/${projectId}/eval-report`, { method: "GET" });
  } catch {
    badge.textContent = "—";
    body.textContent  = "No eval data yet.";
    return;
  }

  const s = report.summary || {};
  const pct = s.coverage_pct ?? 0;
  badge.textContent = `${s.covered_features ?? 0}/${s.total_features ?? 0} (${pct}%)`;
  const coverageClass = pct >= 80 ? "evalOk" : pct >= 40 ? "evalWarn" : "evalBad";
  badge.className = "evalSummaryBadge " + coverageClass;

  // Progress bar
  const progressWrap = document.getElementById("evalProgressWrap");
  const progressFill = document.getElementById("evalProgressFill");
  if (progressWrap && progressFill && (s.total_features ?? 0) > 0) {
    progressWrap.classList.remove("hidden");
    // Small delay so the CSS transition fires
    requestAnimationFrame(() => { progressFill.style.width = `${Math.min(pct, 100)}%`; });
  }

  // Card state
  const evalCard = document.getElementById("cardEval");
  if (evalCard) {
    evalCard.classList.remove("card-ok", "card-warn", "card-active");
    if (pct >= 80)      evalCard.classList.add("card-ok");
    else if (pct >= 40) evalCard.classList.add("card-warn");
    else                evalCard.classList.add("card-active");
  }

  body.innerHTML = "";

  // Type breakdown row
  const breakdown = s.type_breakdown || {};
  const breakdownTypes = Object.keys(breakdown);
  if (breakdownTypes.length) {
    const bRow = document.createElement("div");
    bRow.className = "evalTypeBreakdown";
    bRow.innerHTML = breakdownTypes.map(et =>
      `<span class="evalTag evalTag-${et}">${et}: ${breakdown[et].covered}</span>`
    ).join(" ");
    body.appendChild(bRow);
  }

  const milestones = report.milestones || [];
  const ungrouped  = report.ungrouped_features || [];

  if (!milestones.length && !ungrouped.length) {
    body.textContent = "No milestones or features found.";
    return;
  }

  for (const ms of milestones) {
    const section = _evalMilestoneEl(ms);
    body.appendChild(section);
  }

  if (ungrouped.length) {
    const section = _evalMilestoneEl({
      milestone_id: "ungrouped",
      name: "Ungrouped Features",
      status: "—",
      features: ungrouped,
      coverage: {
        total:   ungrouped.length,
        covered: ungrouped.filter(f => f.covered).length,
        pct:     ungrouped.length
          ? Math.round(ungrouped.filter(f => f.covered).length / ungrouped.length * 100)
          : 0,
      },
    });
    body.appendChild(section);
  }
}

function _evalMilestoneEl(ms) {
  const cov = ms.coverage || {};
  const pct = cov.pct ?? 0;

  const section = document.createElement("div");
  section.className = "evalMilestone";

  // Header row — click to collapse/expand
  const header = document.createElement("div");
  header.className = "evalMsHeader";
  header.innerHTML = `
    <span class="evalMsName">${escapeHtml(ms.name)}</span>
    <span class="evalMsCov ${pct >= 80 ? "evalOk" : pct >= 40 ? "evalWarn" : "evalBad"}">${cov.covered ?? 0}/${cov.total ?? 0}</span>
    <span class="evalChevron">▾</span>
  `;

  const list = document.createElement("div");
  list.className = "evalFeatureList";

  // Show expected evals if defined
  const expectedEvals = ms.expected_evals || [];
  if (expectedEvals.length) {
    const expRow = document.createElement("div");
    expRow.className = "evalExpected";
    expRow.innerHTML = `<span class="evalExpectedLabel">Expected:</span> ${
      expectedEvals.map(e => `<span class="evalTag evalTag-${e.split(":")[0].trim()}">${escapeHtml(e)}</span>`).join(" ")
    }`;
    list.appendChild(expRow);
  }

  const features = ms.features || [];
  if (!features.length) {
    const empty = document.createElement("div");
    empty.className = "evalFeatureRow subtle";
    empty.textContent = "No features linked.";
    list.appendChild(empty);
  }

  for (const feat of features) {
    const row = document.createElement("div");
    row.className = "evalFeatureRow " + (feat.covered ? "evalFeatCovered" : "evalFeatMissing");

    const mark = feat.covered ? "✓" : "✗";
    const evalTags = (feat.evals || [])
      .map(e => {
        const statusCls = e.last_run_status === "pass" ? "evalStatusPass"
                        : e.last_run_status === "fail" ? "evalStatusFail"
                        : e.last_run_status === "skip" ? "evalStatusSkip" : "";
        const statusIcon = e.last_run_status === "pass" ? " ✓"
                         : e.last_run_status === "fail" ? " ✗"
                         : e.last_run_status === "skip" ? " ⊘" : "";
        return `<span class="evalTag evalTag-${e.eval_type || "manual"} ${statusCls}" title="${escapeHtml(e.test_id)}">${escapeHtml(e.eval_type || "?")}${statusIcon}</span>`;
      })
      .join("");

    const reqText = feat.text
      ? (feat.text.length > 50 ? feat.text.slice(0, 50) + "…" : feat.text)
      : feat.requirement_id;

    row.innerHTML = `
      <span class="evalMark">${mark}</span>
      <span class="evalFeatText" title="${escapeHtml(feat.text || "")}">${escapeHtml(reqText)}</span>
      <span class="evalTags">${evalTags || '<span class="evalNoEval">no eval</span>'}</span>
    `;
    list.appendChild(row);
  }

  // Toggle expand/collapse on header click
  let expanded = true;
  header.addEventListener("click", () => {
    expanded = !expanded;
    list.style.display = expanded ? "" : "none";
    header.querySelector(".evalChevron").textContent = expanded ? "▾" : "▸";
  });

  section.appendChild(header);
  section.appendChild(list);
  return section;
}

async function ensureProject() {
  const { projectId } = getIds();
  if (!projectId) throw new Error("Select a project first (or create one).");
  return projectId;
}

async function newSession() {
  const projectId = await ensureProject();
  const sess = await api(`/projects/${projectId}/sessions`, {
    method: "POST",
    body: JSON.stringify({ channel: "ui" }),
  });
  setSessionId(sess.id);
  return sess.id;
}

async function sendMessage() {
  const text = el("userMessage").value.trim();
  const docText = el("documentText").value.trim();
  if (!text && !docText) return;

  addMessage("user", text || "(sent document only)", new Date().toISOString());
  el("userMessage").value = "";
  autoResizeTextarea(el("userMessage"));

  const { runId, sessionId } = getIds();
  const projectId = await ensureProject();

  // If no session specified, create one automatically (keeps things tidy)
  let useSessionId = sessionId;
  if (!useSessionId) {
    useSessionId = await newSession();
  }

  if (!runId) {
    const run = await api(`/runs/start`, {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        session_id: useSessionId,
        user_message: text || null,
        document_content: docText || null,
        document_filename: docText ? (window.__attachedFilename || null) : null,
      }),
    });
    setRunId(run.id);
    if (run.session_id) setSessionId(run.session_id);
  } else {
    const updated = await api(`/runs/${runId}/resume`, {
      method: "POST",
      body: JSON.stringify({ user_message: text || null }),
    });
    if (updated.session_id) setSessionId(updated.session_id);
  }

  // Document is one-shot: clear after sending
  if (docText) {
    el("documentText").value = "";
    el("attachmentChip").classList.add("hidden");
    window.__attachedFilename = null;
  }

  await loadHistory();
  await refreshContext();
}

async function loadHistory() {
  const { projectId } = getIds();
  if (!projectId) throw new Error("Select a project first.");
  const data = await api(`/projects/${projectId}/messages`, { method: "GET" });
  const messages = data?.messages || [];
  clearMessages();
  for (const m of messages) {
    addMessage(uiRoleFromMessageRole(m.role), m.content || "", m.created_at || null);
  }
  if (data?.latest_session_id) setSessionId(data.latest_session_id);
}

// ── Create project modal ─────────────────────────────────────────────────────

function openCreateModal() {
  el("createModal").classList.remove("hidden");
  el("modalProjectName").value = "";
  setTimeout(() => el("modalProjectName").focus(), 50);
}

function closeCreateModal() {
  el("createModal").classList.add("hidden");
}

async function submitCreateModal() {
  const name = el("modalProjectName").value.trim();
  if (!name) {
    el("modalProjectName").focus();
    return;
  }
  const btn = el("btnModalCreate");
  btn.textContent = "Creating…";
  btn.disabled = true;
  try {
    const created = await api(`/projects`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    closeCreateModal();
    await refreshDashboard();
    await loadProjectFromDashboard({
      project_id: created.id,
      name: created.name,
      latest_run_id: null,
    });
  } catch (e) {
    showVisibleError(e);
  } finally {
    btn.textContent = "Create project";
    btn.disabled = false;
  }
}

// ── Textarea auto-resize ──────────────────────────────────────────────────────

function autoResizeTextarea(ta) {
  ta.style.height = "auto";
  ta.style.height = `${ta.scrollHeight}px`;
}

async function resolveApproval(decision) {
  const { runId } = getIds();
  if (!runId) throw new Error("No run id yet.");

  let approvalId = Number(window.__selectedApprovalId || 0) || null;
  if (!approvalId) throw new Error("Select a pending approval first.");

  const comments = el("approvalComments").value.trim() || null;
  await api(`/approvals/${approvalId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ decision, comments }),
  });
  addMessage("system", `Approval ${approvalId} resolved as ${decision}.`);
  await refreshContext();
}

async function attachFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  const { projectId, runId } = getIds();
  // Persist uploads as artifacts when we have a project
  if (projectId) {
    fd.append("project_id", String(projectId));
    if (runId) fd.append("run_id", String(runId));
  }
  const result = projectId
    ? await apiMultipart(`/documents/extract_and_save`, fd)
    : await apiMultipart(`/documents/extract`, fd);
  const text = result?.text || "";

  window.__attachedFilename = result?.filename || file.name;
  showAttachmentChip(window.__attachedFilename);

  if (!text.trim()) {
    addMessage(
      "system",
      `Attached "${window.__attachedFilename}". No text extracted (type=${result?.content_type || "unknown"}).`
    );
  } else {
    el("documentText").value = text;
    const meta = result?.artifact_id ? ` Saved as artifact #${result.artifact_id}.` : "";
    addMessage("system", `Extracted ${text.length} chars from "${window.__attachedFilename}".${meta}`);
  }
}

function setup() {
  // Restore side panel state
  try {
    const collapsed = localStorage.getItem("agentos.sideCollapsed") === "1";
    if (collapsed) getShell().classList.add("side-collapsed");
    el("btnToggleSide").textContent = collapsed ? "Show panel" : "Hide panel";
  } catch {
    // ignore
  }

  // Restore workflow diagram state
  try {
    const wfOpen = localStorage.getItem("agentos.workflowOpen") === "1";
    if (wfOpen) {
      el("workflowDiagram").classList.remove("hidden");
      el("btnToggleWorkflow").classList.add("active");
    }
  } catch {
    // ignore
  }

  // Start on dashboard
  showDashboard();

  el("btnToggleSide").addEventListener("click", () => {
    const shell = getShell();
    const collapsed = shell.classList.toggle("side-collapsed");
    el("btnToggleSide").textContent = collapsed ? "Show panel" : "Hide panel";
    try {
      localStorage.setItem("agentos.sideCollapsed", collapsed ? "1" : "0");
    } catch {
      // ignore
    }
  });

  el("btnToggleWorkflow").addEventListener("click", () => {
    const diagram = el("workflowDiagram");
    const btn = el("btnToggleWorkflow");
    const isOpen = diagram.classList.toggle("hidden");
    // classList.toggle returns true when class was ADDED (now hidden)
    const nowVisible = !isOpen;
    btn.classList.toggle("active", nowVisible);
    try {
      localStorage.setItem("agentos.workflowOpen", nowVisible ? "1" : "0");
    } catch {
      // ignore
    }
    // If just opened, render immediately with latest graph data
    if (nowVisible && window.__lastGraph) {
      renderWorkflowDiagram(window.__lastGraph);
    }
  });

  // Clear UI for a clean start (history loads on project selection)
  clearMessages();

  el("btnOpenDashboard").addEventListener("click", async () => {
    showDashboard();
    try {
      await refreshDashboard();
    } catch (e) {
      showVisibleError(e);
    }
  });

  el("btnBackToDashboard").addEventListener("click", async () => {
    showDashboard();
    try {
      await refreshDashboard();
    } catch {
      // ignore
    }
  });

  el("btnRefreshDashboard").addEventListener("click", async () => {
    try {
      await refreshDashboard();
    } catch (e) {
      showVisibleError(e);
    }
  });

  // ── Modal ──────────────────────────────────────────────────────────────────
  el("btnNewProject").addEventListener("click", () => openCreateModal());
  el("btnModalClose").addEventListener("click", () => closeCreateModal());
  el("btnModalCancel").addEventListener("click", () => closeCreateModal());
  el("btnModalCreate").addEventListener("click", async () => {
    try { await submitCreateModal(); } catch (e) { showVisibleError(e); }
  });
  el("modalProjectName").addEventListener("keydown", async (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); try { await submitCreateModal(); } catch (e) { showVisibleError(e); } }
    if (ev.key === "Escape") closeCreateModal();
  });
  el("createModal").addEventListener("click", (ev) => {
    if (ev.target === el("createModal")) closeCreateModal();
  });

  // ── GitHub publish button ──────────────────────────────────────────────────
  const btnPublish = document.getElementById("btnPublishGithub");
  if (btnPublish) {
    btnPublish.addEventListener("click", async () => {
      const { projectId } = getIds();
      if (!projectId) { showVisibleError("Select a project first."); return; }
      btnPublish.textContent = "Publishing…";
      btnPublish.disabled = true;
      try {
        const res = await api(`/projects/${projectId}/publish/github`, { method: "POST" });
        const linkDiv = document.getElementById("githubLink");
        if (linkDiv && res.repo_url) {
          linkDiv.classList.remove("hidden");
          linkDiv.innerHTML = `<a href="${escapeHtml(res.repo_url)}" target="_blank" class="githubLink">${escapeHtml(res.repo_url)}</a>`;
        }
        addMessage("system", `Published ${res.files_pushed} file(s) to GitHub: ${res.repo_url}`, new Date().toISOString());
        if (res.errors?.length) {
          addMessage("system", `Warnings: ${res.errors.join("; ")}`, new Date().toISOString());
        }
      } catch (e) {
        showVisibleError(e);
      } finally {
        btnPublish.textContent = "Publish to GitHub";
        btnPublish.disabled = false;
      }
    });
  }

  // ── Document card toggle ───────────────────────────────────────────────────
  const btnToggleDoc = document.getElementById("btnToggleDocument");
  const docBody = document.getElementById("documentBody");
  const docChevron = btnToggleDoc?.querySelector(".cardChevron");
  if (btnToggleDoc && docBody) {
    btnToggleDoc.addEventListener("click", () => {
      const isHidden = docBody.classList.toggle("hidden");
      btnToggleDoc.setAttribute("aria-expanded", String(!isHidden));
      if (docChevron) docChevron.textContent = isHidden ? "\u25B8" : "\u25BE";
    });
    btnToggleDoc.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); btnToggleDoc.click(); }
    });
  }

  // ── Textarea auto-resize ───────────────────────────────────────────────────
  const ta = el("userMessage");
  ta.addEventListener("input", () => autoResizeTextarea(ta));

  el("btnSend").addEventListener("click", async () => {
    try {
      await sendMessage();
    } catch (e) {
      addMessage("error", String(e.message || e));
    }
  });

  el("userMessage").addEventListener("keydown", async (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      try {
        await sendMessage();
      } catch (e) {
        addMessage("error", String(e.message || e));
      }
    }
  });

  el("btnRefresh").addEventListener("click", async () => {
    try {
      await refreshContext();
    } catch (e) {
      addMessage("error", String(e.message || e));
    }
  });

  el("btnLoadHistory").addEventListener("click", async () => {
    try {
      await loadHistory();
    } catch (e) {
      addMessage("error", String(e.message || e));
    }
  });

  el("btnUseQuestion").addEventListener("click", () => {
    const q = el("nextQuestion").textContent;
    if (q && q !== "—") {
      el("userMessage").value = q;
      el("userMessage").focus();
    }
  });

  el("btnApprove").addEventListener("click", async () => {
    try {
      await resolveApproval("approved");
    } catch (e) {
      addMessage("error", String(e.message || e));
    }
  });

  el("btnReject").addEventListener("click", async () => {
    try {
      await resolveApproval("rejected");
    } catch (e) {
      addMessage("error", String(e.message || e));
    }
  });

  el("btnAttach").addEventListener("click", () => el("fileInput").click());
  el("fileInput").addEventListener("change", async (ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    try {
      await attachFile(file);
    } catch (e) {
      addMessage("error", String(e.message || e));
    } finally {
      // allow re-selecting same file
      ev.target.value = "";
    }
  });

  refreshDashboard().catch(() => {});
  refreshModeBadge().catch(() => {});
}

setup();

