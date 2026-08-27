const PAGES = [
  ["/engine", "Engine"],
  ["/evidence", "Evidence"],
  ["/console", "Console"],
  ["/docs", "Docs"],
  ["/company", "Company"],
];

const SEAL = `<svg width="26" height="26" viewBox="0 0 256 256" fill="none" aria-hidden="true">
  <path d="M128 24 A104 104 0 1 1 24 128" stroke="currentColor" stroke-width="18" stroke-linecap="round"/>
  <path d="M96 96 H176 M136 96 V176" stroke="currentColor" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="68" cy="68" r="12" fill="currentColor"/>
</svg>`;

function navHtml(path) {
  const links = PAGES.map(([href, label]) => {
    const active = path === href ? " is-active" : "";
    return `<a class="${active.trim()}" href="${href}">${label}</a>`;
  }).join("");
  return `<a class="skip" href="#main">Skip to content</a>
  <div class="mast">
    <div class="wrap mast-inner">
      <span>Independent verification protocol</span>
      <span class="mast-mid">Verifier ≠ Builder</span>
      <span>v0.1 freeze · v0.2 IR · v0.3 MiniTodos</span>
    </div>
  </div>
  <header class="nav">
    <div class="wrap nav-inner">
      <a class="brand" href="/">${SEAL}<span>OpenTruth</span></a>
      <button class="nav-toggle" type="button" data-nav-toggle aria-expanded="false" aria-label="Open menu">Menu</button>
      <nav class="nav-links" data-nav-links>
        ${links}
        <span class="engine-flag"><span class="status-dot" data-engine-dot></span><span data-engine-label>Engine</span></span>
        <a class="nav-cta" href="/console">Run proof</a>
      </nav>
    </div>
  </header>`;
}

function footerHtml() {
  return `<footer class="footer">
    <div class="wrap footer-lab">
      <div>
        <div class="brand-foot">${SEAL}<span>OpenTruth</span></div>
        <p>Independent verification protocol. The sealed run is the source of truth. This site is a control surface, not a second engine.</p>
      </div>
      <div>
        <div class="kicker kicker-pad">Surfaces</div>
        <a href="/engine">Engine</a>
        <a href="/evidence">Evidence</a>
        <a href="/console">Console</a>
        <a href="/docs">Docs</a>
        <a href="/company">Company</a>
      </div>
      <div>
        <div class="kicker kicker-pad">Status</div>
        <p class="mono faint">Apache-2.0</p>
        <p class="mono faint">v0.1 MiniAuth freeze</p>
        <p class="mono faint">v0.2 Verification IR</p>
        <p class="mono faint">v0.3 MiniTodos · planner=ir</p>
      </div>
    </div>
    <div class="wrap footer-inner">
      <div>Verifier ≠ Builder · Complex protocol. Simple interface.</div>
      <div class="mono">PROVEN is a sealed graph, not a log line.</div>
    </div>
  </footer>`;
}

export function mountChrome() {
  const path = location.pathname.replace(/\/$/, "") || "/";
  const nav = document.getElementById("site-nav");
  const foot = document.getElementById("site-footer");
  if (nav) nav.innerHTML = navHtml(path === "/index.html" ? "/" : path);
  if (foot) foot.innerHTML = footerHtml();
  const toggle = document.querySelector("[data-nav-toggle]");
  const links = document.querySelector("[data-nav-links]");
  toggle?.addEventListener("click", () => {
    const open = links?.classList.toggle("open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  });
  fetch("/api/v1/health")
    .then((r) => r.json())
    .then((data) => {
      const dot = document.querySelector("[data-engine-dot]");
      const label = document.querySelector("[data-engine-label]");
      if (data.ok) {
        dot?.classList.add("on");
        if (label) label.textContent = "Engine online";
      }
    })
    .catch(() => {});
}

mountChrome();

async function hydrateHome() {
  const runsEl = document.querySelector("[data-live-runs]");
  const verdictEl = document.querySelector("[data-live-verdict]");
  if (!runsEl && !verdictEl) return;
  try {
    const health = await fetch("/api/v1/health").then((r) => r.json());
    if (runsEl) runsEl.textContent = String(health.runs ?? 0);
    if (verdictEl) {
      const latest = health.latest;
      verdictEl.textContent = latest
        ? `${latest.verdict} · ${latest.run_id}`
        : "none yet";
    }
  } catch {
    /* nav health ping is enough */
  }
}

hydrateHome();
