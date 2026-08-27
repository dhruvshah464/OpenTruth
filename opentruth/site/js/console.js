const $ = (sel, root = document) => root.querySelector(sel);

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function verdictClass(v) {
  return (v || "").replace(/\s+/g, "_");
}

function pct(confidence) {
  return confidence == null ? "—" : `${Math.round(Number(confidence) * 100)}%`;
}

function renderStamp(payload) {
  const v = payload.verdict || "—";
  const conf = pct(payload.confidence);
  const left = payload.left?.run_id;
  const right = payload.right?.run_id;
  const delta = left && right ? `<p class="muted stamp-sub">diff ${esc(left)} → ${esc(right)}</p>` : "";
  return `<div class="kicker">Sealed verdict</div>
    <div class="stamp-verdict ${verdictClass(v)}">${esc(v)}</div>
    <p class="muted stamp-sub">run <span class="mono">${esc(payload.run_id)}</span> · confidence ${esc(conf)}</p>
    ${delta}`;
}

function renderLoopStamps(loop) {
  const box = $("#loop-stamps");
  if (!loop) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  box.innerHTML = ["planted", "fixed", "diff"]
    .map((key) => {
      const row = loop[key];
      return `<button type="button" class="mini-stamp" data-open="${esc(row.run_id)}">
        <span class="kicker">${esc(key)}</span>
        <strong class="${verdictClass(row.verdict)}">${esc(row.verdict)}</strong>
        <span class="mono">${esc(row.run_id)}</span>
      </button>`;
    })
    .join("");
  box.onclick = (ev) => {
    const btn = ev.target.closest("[data-open]");
    if (btn) showRun(btn.getAttribute("data-open")).catch(setError);
  };
}

function renderConstraints(rows, runId) {
  if (!rows?.length) return "<p class='muted'>No constraints yet.</p>";
  const body = rows
    .map((row) => {
      const result = String(row.result || "").toUpperCase();
      return `<tr data-node="${esc(row.id)}" data-run="${esc(runId)}">
        <td>${esc(row.id)}</td>
        <td>${esc(row.statement || row.kind || "")}</td>
        <td><span class="badge ${esc(result.toLowerCase())}">${esc(result)}</span></td>
      </tr>`;
    })
    .join("");
  return `<table class="spec spec-click">
    <thead><tr><th>ID</th><th>Constraint</th><th>Result</th></tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

function nodeMap(nodes) {
  const map = {};
  for (const n of nodes || []) map[n.id] = n;
  return map;
}

function nodeLabel(n) {
  if (n.statement) return n.statement;
  if (n.check) return `${n.check}${n.expect ? " " + n.expect : ""}`;
  if (n.type && n.target) return `${n.type} ${n.target}`;
  if (n.method && n.status != null) return `${n.method} → ${n.status}`;
  if (n.payload_kind) return String(n.payload_kind);
  return n.kind || "";
}

function renderTree(root, children, nodes) {
  const walk = (id) => {
    const n = nodes[id];
    if (!n) return "";
    const kids = children[id] || [];
    const result = n.result
      ? ` <span class="badge ${esc(String(n.result).toLowerCase())}">${esc(String(n.result).toUpperCase())}</span>`
      : "";
    let html = `<li><button type="button" data-node="${esc(n.id)}"><span class="id">${esc(n.id)}</span> <span class="kind">${esc(n.kind)}</span> ${esc(nodeLabel(n))}${result}</button>`;
    if (kids.length) html += `<ul>${kids.map(walk).join("")}</ul>`;
    return `${html}</li>`;
  };
  return `<ul class="tree-root">${walk(root)}</ul>`;
}

function renderFiles(files) {
  const panel = $("#files-panel");
  const view = $("#files-view");
  const groups = files || {};
  const parts = [];
  for (const kind of ["screenshots", "network", "artifacts"]) {
    const rows = groups[kind] || [];
    if (!rows.length) continue;
    const items = rows
      .map((f) => {
        if (kind === "screenshots") {
          return `<a href="${esc(f.url)}" target="_blank" rel="noopener"><img src="${esc(f.url)}" alt="${esc(f.name)}"/></a>`;
        }
        return `<a class="file-chip" href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.name)}</a>`;
      })
      .join("");
    parts.push(`<div class="file-group"><div class="kicker">${esc(kind)}</div><div class="file-row">${items}</div></div>`);
  }
  if (!parts.length) {
    panel.hidden = true;
    view.innerHTML = "";
    return;
  }
  panel.hidden = false;
  view.innerHTML = parts.join("");
}

async function api(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
    throw new Error(detail || res.statusText);
  }
  return data;
}

async function loadRun(runId) {
  return api(`/api/v1/runs/${runId}`);
}

async function explain(runId, nodeId) {
  const data = await api(`/api/v1/runs/${runId}/explain/${nodeId}`);
  $("#explain-out").textContent = data.text || "No explanation.";
}

async function showRun(runId) {
  const payload = await loadRun(runId);
  $("#result-stamp").innerHTML = renderStamp(payload);
  $("#result-table").innerHTML = renderConstraints(payload.constraints, runId);
  const nodes = nodeMap(payload.nodes);
  $("#graph-tree").innerHTML = renderTree(payload.root, payload.children || {}, nodes);
  const plan = payload.plan || {};
  $("#plan-meta").textContent = [
    plan.mode && `mode ${plan.mode}`,
    plan.planner && `planner ${plan.planner}`,
    plan.planner_requested && plan.planner_requested !== plan.planner && `requested ${plan.planner_requested}`,
    plan.planner_model && `model ${plan.planner_model}`,
    plan.llm_error && `llm_error ${plan.llm_error}`,
    payload.integrity_ok === false ? "INTEGRITY FAILED" : "integrity sealed",
  ]
    .filter(Boolean)
    .join(" · ");
  const pack = $("#pack-link");
  pack.hidden = false;
  pack.href = `/api/v1/runs/${runId}/pack`;
  pack.setAttribute("download", `${runId}.zip`);
  $("#explain-out").textContent = "Select a constraint or graph node.";
  renderFiles(payload.files);
  const onNode = (id) => explain(runId, id).catch(setError);
  $("#graph-tree").onclick = (ev) => {
    const btn = ev.target.closest("[data-node]");
    if (btn) onNode(btn.getAttribute("data-node"));
  };
  $("#result-table").onclick = (ev) => {
    const row = ev.target.closest("[data-node]");
    if (row) onNode(row.getAttribute("data-node"));
  };
  const url = new URL(location.href);
  url.searchParams.set("run", runId);
  history.replaceState({}, "", url);
  await refreshRuns(runId);
}

async function refreshRuns(active) {
  const data = await api("/api/v1/runs");
  const box = $("#run-list");
  if (!data.runs?.length) {
    box.innerHTML = "<p class='muted'>No sealed runs yet.</p>";
    return data.runs || [];
  }
  box.innerHTML = data.runs
    .map(
      (r) => `<button class="run-chip ${r.run_id === active ? "on" : ""}" type="button" data-open="${esc(r.run_id)}">
        <span>${esc(r.run_id)}</span><span>${esc(r.verdict || r.mode || "")}</span>
      </button>`
    )
    .join("");
  box.onclick = (ev) => {
    const btn = ev.target.closest("[data-open]");
    if (btn) showRun(btn.getAttribute("data-open")).catch(setError);
  };
  const left = $("#diff-left");
  const right = $("#diff-right");
  const opts = data.runs
    .map((r) => `<option value="${esc(r.run_id)}">${esc(r.run_id)} · ${esc(r.verdict || r.mode || "")}</option>`)
    .join("");
  const keepLeft = left?.value;
  const keepRight = right?.value;
  if (left) left.innerHTML = opts;
  if (right) right.innerHTML = opts;
  if (right && data.runs[0]) right.value = keepRight && data.runs.some((r) => r.run_id === keepRight) ? keepRight : data.runs[0].run_id;
  if (left && data.runs[1]) {
    left.value = keepLeft && data.runs.some((r) => r.run_id === keepLeft) ? keepLeft : data.runs[1].run_id;
  } else if (left && data.runs[0]) {
    left.value = data.runs[0].run_id;
  }
  return data.runs;
}

let busyTimer = null;

function setBusy(on, message) {
  const el = $("#console-busy");
  const buttons = [$("#loop-btn"), $("#verify-btn"), $("#diff-btn")];
  if (busyTimer) {
    clearInterval(busyTimer);
    busyTimer = null;
  }
  if (on) {
    const start = Date.now();
    el.hidden = false;
    const tick = () => {
      const s = Math.round((Date.now() - start) / 1000);
      el.textContent = `${message} ${s}s`;
    };
    tick();
    busyTimer = setInterval(tick, 250);
    buttons.forEach((b) => {
      if (b) b.disabled = true;
    });
  } else {
    el.hidden = true;
    buttons.forEach((b) => {
      if (b) b.disabled = false;
    });
  }
}

function setError(err) {
  $("#console-error").textContent = err.message || String(err);
  setBusy(false);
}

async function runVerify(ev) {
  ev.preventDefault();
  $("#console-error").textContent = "";
  setBusy(true, "Executing plan… sealing run…");
  try {
    const data = await api("/api/v1/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: $("#mode").value,
        persist_session: $("#persist").checked,
        write_identity: $("#identity").checked,
        llm: Boolean($("#llm")?.checked),
      }),
    });
    renderLoopStamps(null);
    await showRun(data.run_id);
  } catch (err) {
    setError(err);
    return;
  }
  setBusy(false);
}

async function runLoop(ev) {
  ev.preventDefault();
  $("#console-error").textContent = "";
  setBusy(true, "Planted → claimed fix → diff…");
  try {
    const data = await api("/api/v1/loop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: $("#loop-mode").value }),
    });
    renderLoopStamps(data);
    await showRun(data.diff.run_id);
    $("#explain-out").textContent =
      `Loop sealed.\nplanted ${data.planted.run_id} ${data.planted.verdict}\nfixed   ${data.fixed.run_id} ${data.fixed.verdict}\ndiff    ${data.diff.run_id} ${data.diff.verdict}\n\nSelect C-3 on planted vs fixed, or open a stamp above.`;
  } catch (err) {
    setError(err);
    return;
  }
  setBusy(false);
}

async function runDiff(ev) {
  ev.preventDefault();
  $("#console-error").textContent = "";
  setBusy(true, "Comparing sealed runs…");
  try {
    const data = await api("/api/v1/diff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ left: $("#diff-left").value, right: $("#diff-right").value }),
    });
    renderLoopStamps(null);
    await showRun(data.run_id);
  } catch (err) {
    setError(err);
    return;
  }
  setBusy(false);
}

document.getElementById("verify-form")?.addEventListener("submit", runVerify);
document.getElementById("loop-form")?.addEventListener("submit", runLoop);
document.getElementById("diff-form")?.addEventListener("submit", runDiff);

const params = new URLSearchParams(location.search);
const initial = params.get("run");
refreshRuns(initial)
  .then(() => {
    if (initial) return showRun(initial);
    return null;
  })
  .catch(setError);
