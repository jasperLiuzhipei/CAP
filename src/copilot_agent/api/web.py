from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


def build_web_router() -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    @router.get("/app", response_class=HTMLResponse, include_in_schema=False)
    def web_console() -> HTMLResponse:
        return HTMLResponse(WEB_CONSOLE_HTML)

    return router


WEB_CONSOLE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Copilot Agent Console</title>
  <style>
    :root {
      --ink: #17211b;
      --muted: #66736b;
      --paper: #fbf6e8;
      --card: rgba(255, 252, 242, 0.88);
      --line: rgba(23, 33, 27, 0.14);
      --accent: #d85b32;
      --accent-2: #1f7a68;
      --good: #228052;
      --warn: #a76a12;
      --bad: #b33636;
      --shadow: 0 24px 70px rgba(34, 41, 35, 0.16);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Aptos", "SF Pro Display", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 12% 14%, rgba(216, 91, 50, 0.22), transparent 28rem),
        radial-gradient(circle at 82% 18%, rgba(31, 122, 104, 0.20), transparent 30rem),
        linear-gradient(135deg, #fbf6e8 0%, #eef3df 58%, #dfead8 100%);
    }

    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 42px 0 64px;
    }

    .hero {
      display: grid;
      gap: 18px;
      margin-bottom: 24px;
    }

    .eyebrow {
      display: inline-flex;
      width: fit-content;
      gap: 8px;
      align-items: center;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.46);
      color: var(--muted);
      font-size: 13px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    h1 {
      max-width: 820px;
      margin: 0;
      font-family: "Georgia", "Times New Roman", serif;
      font-size: clamp(38px, 7vw, 82px);
      line-height: 0.92;
      letter-spacing: -0.06em;
    }

    .hero p {
      max-width: 760px;
      margin: 0;
      color: var(--muted);
      font-size: 18px;
      line-height: 1.55;
    }

    .grid {
      display: grid;
      grid-template-columns: 0.9fr 1.1fr;
      gap: 18px;
      align-items: start;
    }

    .card {
      border: 1px solid var(--line);
      border-radius: 28px;
      background: var(--card);
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
      overflow: hidden;
    }

    .card header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 22px 22px 16px;
      border-bottom: 1px solid var(--line);
    }

    .card h2 {
      margin: 0;
      font-size: 18px;
      letter-spacing: -0.02em;
    }

    .card header span {
      color: var(--muted);
      font-size: 13px;
    }

    .card-body {
      padding: 20px 22px 22px;
    }

    label {
      display: grid;
      gap: 7px;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }

    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 13px;
      background: rgba(255, 255, 255, 0.62);
      color: var(--ink);
      font: inherit;
      outline: none;
    }

    textarea {
      min-height: 116px;
      resize: vertical;
    }

    input:focus, textarea:focus, select:focus {
      border-color: rgba(31, 122, 104, 0.55);
      box-shadow: 0 0 0 4px rgba(31, 122, 104, 0.12);
    }

    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 10px;
    }

    button {
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      background: var(--ink);
      color: var(--paper);
      font-weight: 800;
      cursor: pointer;
      transition: transform 160ms ease, opacity 160ms ease;
    }

    button.secondary {
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.58);
      color: var(--ink);
    }

    button:hover { transform: translateY(-1px); }
    button:disabled { cursor: not-allowed; opacity: 0.54; transform: none; }

    .status-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin-bottom: 18px;
    }

    .metric {
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.44);
    }

    .metric strong {
      display: block;
      margin-bottom: 4px;
      font-size: 22px;
    }

    .metric span {
      color: var(--muted);
      font-size: 12px;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(31, 122, 104, 0.12);
      color: var(--accent-2);
      font-size: 12px;
      font-weight: 800;
    }

    .pill.failed { background: rgba(179, 54, 54, 0.12); color: var(--bad); }
    .pill.queued { background: rgba(167, 106, 18, 0.12); color: var(--warn); }
    .pill.running { background: rgba(31, 122, 104, 0.12); color: var(--accent-2); }
    .pill.succeeded { background: rgba(34, 128, 82, 0.12); color: var(--good); }

    .timeline {
      display: grid;
      gap: 10px;
      max-height: 420px;
      overflow: auto;
      padding-right: 4px;
    }

    .event {
      display: grid;
      grid-template-columns: 16px 1fr;
      gap: 10px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.48);
    }

    .dot {
      width: 10px;
      height: 10px;
      margin-top: 5px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 5px rgba(216, 91, 50, 0.13);
    }

    .event strong {
      display: block;
      margin-bottom: 4px;
      font-size: 14px;
    }

    .event code, pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: #314237;
      font-size: 12px;
    }

    pre {
      margin: 0;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(23, 33, 27, 0.06);
      max-height: 280px;
      overflow: auto;
    }

    .stack {
      display: grid;
      gap: 18px;
    }

    .muted {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }

    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    @media (max-width: 900px) {
      .grid, .row, .split, .status-grid { grid-template-columns: 1fr; }
      main { padding-top: 26px; }
    }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <span class="eyebrow">Copilot control plane</span>
      <h1>Run agentic coding tasks without leaving the browser.</h1>
      <p>
        Create a project, dispatch a run, watch the worker timeline, and inspect artifacts.
        The agent runtime still flows through the OpenAI Agents SDK sandbox path.
      </p>
    </section>

    <section class="grid">
      <div class="stack">
        <article class="card">
          <header>
            <div>
              <h2>Runtime</h2>
              <span>Worker and sandbox defaults</span>
            </div>
            <span id="runtime-pill" class="pill queued">loading</span>
          </header>
          <div class="card-body">
            <div class="status-grid">
              <div class="metric"><strong id="worker-running">-</strong><span>worker</span></div>
              <div class="metric">
                <strong id="worker-processed">-</strong><span>processed</span>
              </div>
              <div class="metric"><strong id="worker-failed">-</strong><span>failed</span></div>
            </div>
            <pre id="runtime-output">Loading runtime config...</pre>
            <div class="actions">
              <button id="start-worker">Start worker</button>
              <button id="stop-worker" class="secondary">Stop worker</button>
              <button id="refresh" class="secondary">Refresh</button>
            </div>
          </div>
        </article>

        <article class="card">
          <header>
            <div>
              <h2>Create Project</h2>
              <span>Register a workspace repository</span>
            </div>
          </header>
          <div class="card-body">
            <label>Project name
              <input id="project-name" value="Sample Repo" />
            </label>
            <label>Repository path
              <input
                id="repo-path"
                value="/Users/jasperliuzp/my_python_project/copilot_agent/examples/sample_repo"
              />
            </label>
            <label>Memory path
              <input
                id="memory-path"
                value="/Users/jasperliuzp/my_python_project/copilot_agent/examples/sample_repo/.copilot/memory.md"
              />
            </label>
            <label>Default provider
              <select id="default-provider">
                <option value="deepseek">deepseek</option>
                <option value="openai">openai</option>
                <option value="dashscope">dashscope</option>
                <option value="ark">ark</option>
                <option value="custom">custom</option>
              </select>
            </label>
            <div class="actions">
              <button id="create-project">Create project</button>
            </div>
          </div>
        </article>

        <article class="card">
          <header>
            <div>
              <h2>Create Run</h2>
              <span>Queue an AI coding task</span>
            </div>
          </header>
          <div class="card-body">
            <label>Project
              <select id="project-select"></select>
            </label>
            <label>Task
              <textarea id="task">Inspect the sample repo and run tests.
Do not modify code unless tests fail.</textarea>
            </label>
            <div class="row">
              <label>Sandbox backend
                <select id="sandbox-backend"></select>
              </label>
              <label>Provider override
                <input id="provider-override" placeholder="optional" />
              </label>
            </div>
            <div class="actions">
              <button id="create-run">Create run</button>
              <button id="follow-run" class="secondary">Follow selected run</button>
            </div>
          </div>
        </article>
      </div>

      <div class="stack">
        <article class="card">
          <header>
            <div>
              <h2>Runs</h2>
              <span>Latest project activity</span>
            </div>
            <span id="selected-run-pill" class="pill queued">no run selected</span>
          </header>
          <div class="card-body">
            <label>Select run
              <select id="run-select"></select>
            </label>
            <div id="run-summary" class="muted">Create or select a run to inspect it.</div>
          </div>
        </article>

        <article class="card">
          <header>
            <div>
              <h2>Timeline</h2>
              <span>RunEvent stream</span>
            </div>
          </header>
          <div class="card-body">
            <div id="timeline" class="timeline"></div>
          </div>
        </article>

        <article class="card">
          <header>
            <div>
              <h2>Artifacts</h2>
              <span>Report, diff, and verification logs</span>
            </div>
          </header>
          <div class="card-body">
            <div class="split">
              <pre id="artifacts-output">No artifacts yet.</pre>
              <pre id="diff-output">No diff selected.</pre>
            </div>
          </div>
        </article>
      </div>
    </section>
  </main>

  <script>
    const api = "/api/v1";
    const state = { selectedRunId: null, eventSource: null };

    const $ = (id) => document.getElementById(id);

    async function request(path, options = {}) {
      const response = await fetch(`${api}${path}`, {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(`${response.status} ${response.statusText}: ${body}`);
      }
      return response.json();
    }

    function showError(error) {
      $("runtime-output").textContent = error.stack || String(error);
    }

    function renderJson(id, value) {
      $(id).textContent = JSON.stringify(value, null, 2);
    }

    async function refreshRuntime() {
      const [runtime, worker, backends] = await Promise.all([
        request("/runtime/config"),
        request("/worker/status"),
        request("/sandbox/backends"),
      ]);
      $("worker-running").textContent = worker.running ? "on" : "off";
      $("worker-processed").textContent = worker.processed_count;
      $("worker-failed").textContent = worker.failed_count;
      $("runtime-pill").textContent = worker.running ? "worker running" : "worker stopped";
      $("runtime-pill").className = `pill ${worker.running ? "succeeded" : "queued"}`;
      renderJson("runtime-output", { runtime, worker, sandbox_backends: backends });
      renderBackends(backends);
    }

    function renderBackends(backends) {
      const select = $("sandbox-backend");
      const selected = select.value || "unix_local";
      select.innerHTML = "";
      for (const backend of backends) {
        const option = document.createElement("option");
        option.value = backend.id;
        option.disabled = !backend.available;
        option.textContent = `${backend.id} - ${backend.status}`;
        select.appendChild(option);
      }
      select.value = selected;
    }

    async function refreshProjects() {
      const projects = await request("/projects");
      const select = $("project-select");
      const selected = select.value;
      select.innerHTML = "";
      for (const project of projects) {
        const option = document.createElement("option");
        option.value = project.id;
        option.textContent = `${project.name} (${project.default_model_provider || "env"})`;
        select.appendChild(option);
      }
      if (selected) select.value = selected;
      return projects;
    }

    async function refreshRuns() {
      const runs = await request("/runs");
      const select = $("run-select");
      const selected = state.selectedRunId || select.value;
      select.innerHTML = "";
      for (const run of runs) {
        const option = document.createElement("option");
        option.value = run.id;
        option.textContent = `${run.status} - ${run.task.slice(0, 72)}`;
        select.appendChild(option);
      }
      if (selected) select.value = selected;
      if (!state.selectedRunId && runs.length) state.selectedRunId = runs[0].id;
      if (state.selectedRunId) await loadRun(state.selectedRunId);
      return runs;
    }

    async function loadRun(runId) {
      if (!runId) return;
      state.selectedRunId = runId;
      const [run, events, artifacts] = await Promise.all([
        request(`/runs/${runId}`),
        request(`/runs/${runId}/events`),
        request(`/runs/${runId}/artifacts`),
      ]);
      $("selected-run-pill").textContent = run.status;
      $("selected-run-pill").className = `pill ${run.status}`;
      $("run-summary").innerHTML = `
        <strong>${run.task}</strong><br>
        Provider: ${run.model_provider}/${run.model}<br>
        Sandbox: ${run.sandbox_backend}<br>
        Saved dir: ${run.saved_dir || "-"}<br>
        Summary: ${run.summary || "-"}
      `;
      renderEvents(events);
      renderJson("artifacts-output", artifacts);
      await loadDiff(run);
    }

    function renderEvents(events) {
      const timeline = $("timeline");
      timeline.innerHTML = "";
      for (const event of events) appendEvent(event);
      if (!events.length) timeline.innerHTML = '<div class="muted">No events yet.</div>';
    }

    function appendEvent(event) {
      const timeline = $("timeline");
      const item = document.createElement("div");
      item.className = "event";
      item.dataset.eventId = event.id;
      item.innerHTML = `
        <span class="dot"></span>
        <div>
          <strong>${event.event_type}</strong>
          <div class="muted">${event.created_at}</div>
          <code>${JSON.stringify(event.payload, null, 2)}</code>
        </div>
      `;
      timeline.appendChild(item);
      timeline.scrollTop = timeline.scrollHeight;
    }

    async function loadDiff(run) {
      if (!run.diff_path) {
        $("diff-output").textContent = "No diff for this run.";
        return;
      }
      try {
        const diff = await request(`/runs/${run.id}/diff`);
        $("diff-output").textContent = diff.diff || "(empty diff)";
      } catch (error) {
        $("diff-output").textContent = String(error);
      }
    }

    async function createProject() {
      const payload = {
        name: $("project-name").value,
        repo_path: $("repo-path").value,
        memory_path: $("memory-path").value || null,
        default_model_provider: $("default-provider").value || null,
      };
      const project = await request("/projects", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await refreshProjects();
      $("project-select").value = project.id;
    }

    async function createRun() {
      const payload = {
        project_id: $("project-select").value,
        task: $("task").value,
        sandbox_backend: $("sandbox-backend").value,
      };
      if ($("provider-override").value.trim()) {
        payload.model_provider = $("provider-override").value.trim();
      }
      const run = await request("/runs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.selectedRunId = run.id;
      await refreshRuns();
      followRun();
    }

    function followRun() {
      if (!state.selectedRunId) return;
      if (state.eventSource) state.eventSource.close();
      $("timeline").innerHTML = "";
      const url = `${api}/runs/${state.selectedRunId}/events/stream?follow=true`;
      state.eventSource = new EventSource(url);
      state.eventSource.onmessage = (message) => {
        appendEvent(JSON.parse(message.data));
      };
      const eventNames = [
        "run.queued", "run.started", "sandbox.runtime_checked", "verification.completed",
        "artifact.created", "run.completed", "run.failed", "run.cancelled"
      ];
      for (const name of eventNames) {
        state.eventSource.addEventListener(name, (message) => {
          const event = JSON.parse(message.data);
          if (!document.querySelector(`[data-event-id="${event.id}"]`)) appendEvent(event);
          if (name === "run.completed" || name === "run.failed" || name === "run.cancelled") {
            state.eventSource.close();
            refreshRuns().catch(showError);
          }
        });
      }
      state.eventSource.onerror = () => {
        state.eventSource.close();
        refreshRuns().catch(showError);
      };
    }

    async function refreshAll() {
      await refreshRuntime();
      await refreshProjects();
      await refreshRuns();
    }

    $("start-worker").addEventListener("click", () => {
      request("/worker/start", { method: "POST" }).then(refreshRuntime).catch(showError);
    });
    $("stop-worker").addEventListener("click", () => {
      request("/worker/stop", { method: "POST" }).then(refreshRuntime).catch(showError);
    });
    $("refresh").addEventListener("click", () => refreshAll().catch(showError));
    $("create-project").addEventListener("click", () => createProject().catch(showError));
    $("create-run").addEventListener("click", () => createRun().catch(showError));
    $("follow-run").addEventListener("click", followRun);
    $("run-select").addEventListener("change", (event) => {
      loadRun(event.target.value).catch(showError);
    });

    refreshAll().catch(showError);
    setInterval(() => refreshRuntime().catch(showError), 5000);
  </script>
</body>
</html>
"""
