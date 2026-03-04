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

function nowIso() {
  return new Date().toISOString();
}

function addMessage(role, text) {
  const wrap = el("messages");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
}

function showDashboardError(err) {
  const msg = String(err?.message || err || "Unknown error");
  const box = el("dashboardTable");
  box.innerHTML = `<div class="msg error">${escapeHtml(msg)}</div>`;
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

    el("modeBadge").textContent = label;
    el("modeBadge").title = detail;
  } catch {
    // ignore
  }
}

function setMeta({ runId, status, node, phase, approvalId }) {
  const s = getState();
  const projectName = s.projectName || "—";
  el("projectLabel").textContent = `project: ${projectName}`;
  el("runStatus").textContent = status || "—";
  el("runIdLabel").textContent = `run: ${runId ?? "—"}`;
  el("nodeLabel").textContent = `node: ${node ?? "—"}`;
  el("phaseLabel").textContent = `phase: ${phase ?? "—"}`;
  el("approvalLabel").textContent = `approval: ${approvalId ?? "—"}`;
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
  return d.toLocaleString();
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
}

async function refreshDashboard() {
  const box = el("dashboardTable");
  try {
    const data = await api(`/projects/dashboard`, { method: "GET" });
    const rows = data?.projects || [];
    if (!rows.length) {
      box.textContent = "No projects yet. Click “Create project” to start.";
      return;
    }

    const table = document.createElement("table");
    table.className = "table";
    table.innerHTML = `
    <thead>
      <tr>
        <th>Project</th>
        <th>State</th>
        <th>Artifacts</th>
        <th>Approvals</th>
        <th>Tokens</th>
        <th>Cost</th>
        <th>System hours</th>
        <th>Last activity</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody></tbody>
  `;

    const tbody = table.querySelector("tbody");
    for (const r of rows) {
      const tr = document.createElement("tr");
      const artifacts = r.artifacts || {};

      const shownArtifactKeys = [
        "brd",
        "prd",
        "sow",
        "server_details_client",
        "server_details_infra",
        "input_document",
      ]
        .filter((k) => artifacts[k])
        .slice(0, 4);

      const artifactHtml = shownArtifactKeys.length
        ? shownArtifactKeys
            .map((k) => {
              const a = artifacts[k];
              return `<button class="linkBtn" data-artifact="${a.id}" data-title="${k} v${a.version}">${k}</button>`;
            })
            .join(" · ")
        : "—";

      tr.innerHTML = `
      <td><div><strong>${escapeHtml(r.name)}</strong></div></td>
      <td><span class="pill">${escapeHtml(r.current_state || "—")}</span></td>
      <td class="mono">${artifactHtml}</td>
      <td><span class="pill">${Number(r.pending_approvals || 0)} pending</span></td>
      <td class="mono">${Number(r.tokens_spent || 0)}</td>
      <td class="mono">${fmtMoney(r.cost_usd || 0)}</td>
      <td class="mono">${fmtHours(r.system_hours || 0)}</td>
      <td class="mono">${fmtWhen(r.last_activity_at)}</td>
      <td class="actions"><button class="btn secondary" data-load="${r.project_id}">Load</button></td>
    `;
      tbody.appendChild(tr);
    }

    box.innerHTML = "";
    box.appendChild(table);

    box.querySelectorAll("[data-load]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const pid = Number(btn.getAttribute("data-load"));
        const row = rows.find((x) => Number(x.project_id) === pid);
        if (!row) return;
        try {
          await loadProjectFromDashboard(row);
        } catch (e) {
          showVisibleError(e);
        }
      });
    });

    box.querySelectorAll("[data-artifact]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.getAttribute("data-artifact"));
        const title = btn.getAttribute("data-title") || `Artifact ${id}`;
        try {
          await openArtifactInNewTab(id, title);
        } catch (e) {
          showVisibleError(e);
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

  setMeta({
    runId,
    status: run?.status,
    node: run?.current_node,
    phase,
    approvalId,
  });

  el("nextQuestion").textContent = nextQ || "—";

  // Workflow stepper (phases + substates)
  if (projectId) {
    try {
      const g = await api(`/projects/${projectId}/state_graph`, { method: "GET" });
      renderWorkflowStepper(g);
    } catch {
      // ignore
    }
  }

  // Pending approvals list (UI)
  const pendingBox = el("pendingApprovals");
  if (!approvals.length) {
    pendingBox.textContent = "—";
  } else {
    pendingBox.innerHTML = "";
    for (const a of approvals) {
      const btn = document.createElement("button");
      btn.className = "btn secondary";
      btn.style.width = "100%";
      btn.style.marginBottom = "8px";
      btn.textContent = `#${a.id} • ${a.type} • ${a.status}`;
      btn.addEventListener("click", () => {
        window.__selectedApprovalId = a.id;
      });
      pendingBox.appendChild(btn);
    }
    window.__selectedApprovalId = approvals[0].id;
  }

  const artifactsProjectId = run?.project_id;
  if (artifactsProjectId) {
    const artifactList = await api(`/projects/${artifactsProjectId}/artifacts`, { method: "GET" });
    const artifacts = artifactList?.artifacts || [];
    const box = el("artifacts");
    if (!artifacts.length) {
      box.textContent = "—";
    } else {
      box.innerHTML = "";
      for (const a of artifacts.slice(0, 6)) {
        const row = document.createElement("div");
        row.className = "mono";
        row.style.marginBottom = "8px";

        const btn = document.createElement("button");
        btn.className = "btn secondary";
        btn.style.width = "100%";
        btn.textContent = `${a.type} v${a.version}`;
        btn.addEventListener("click", async () => {
          const content = await api(`/artifacts/${a.id}/content`, { method: "GET" });
          addMessage("system", `Artifact ${a.type} v${a.version}\n\n${content?.content || ""}`);
        });

        row.appendChild(btn);
        box.appendChild(row);
      }
    }
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

  addMessage("user", text || "(sent document only)");
  el("userMessage").value = "";

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
    addMessage(uiRoleFromMessageRole(m.role), m.content || "");
  }
  if (data?.latest_session_id) setSessionId(data.latest_session_id);
}

async function createProjectFlow() {
  const name = window.prompt("Project name?");
  if (!name || !name.trim()) return;
  const created = await api(`/projects`, {
    method: "POST",
    body: JSON.stringify({ name: name.trim() }),
  });
  await refreshDashboard();
  await loadProjectFromDashboard({
    project_id: created.id,
    name: created.name,
    latest_run_id: null,
  });
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

  el("btnNewProject").addEventListener("click", async () => {
    try {
      await createProjectFlow();
    } catch (e) {
      showVisibleError(e);
    }
  });

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

