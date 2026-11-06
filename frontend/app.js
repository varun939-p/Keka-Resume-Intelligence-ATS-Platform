/* ==========================================================================
   Resume Intelligence — dashboard client
   State-driven vanilla JS. Every control calls a real endpoint in main.py;
   nothing here fabricates candidate data.
   ========================================================================== */
"use strict";

(() => {
  // ------------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name, cls = "") => `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  const nf = new Intl.NumberFormat("en-IN");
  const fmtInt = (n) => (n == null ? "—" : nf.format(n));
  const fmtMs = (ms) => (ms == null ? "—" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`);
  const fmtYears = (y) => (y == null ? "—" : `${Number(y).toFixed(1).replace(/\.0$/, "")} yrs`);
  const fmtSize = (b) => (b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(0)} KB` : `${(b / 1048576).toFixed(1)} MB`);
  const fmtClock = (iso) => {
    const d = new Date(iso);
    return `${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}.${String(d.getMilliseconds()).padStart(3, "0")}`;
  };
  const fmtDateTime = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
  };
  const relTime = (iso) => {
    if (!iso) return "never";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 45) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return fmtDateTime(iso);
  };
  const debounce = (fn, ms) => {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  };
  const prefs = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable: preference lasts this session */ } },
  };
  const qs = (o) => {
    const p = new URLSearchParams();
    Object.entries(o).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== "") p.set(k, v); });
    const s = p.toString();
    return s ? `?${s}` : "";
  };
  const safeName = (name) => name.replace(/\\/g, "/").split("/").pop().replace(/[^A-Za-z0-9._ ()-]/g, "_").slice(0, 140) || "resume";
  const initials = (name) => (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  const avatar = (name, lg) => `<span class="avatar ${lg ? "lg" : ""}" aria-hidden="true">${esc(initials(name))}</span>`;
  const isTyping = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);

  const STAGES = {
    shortlisted: { label: "Shortlisted", short: "Shortlisted", band: "short" },
    technical_review: { label: "Technical Review", short: "Tech review", band: "review" },
    hold: { label: "Hold / Borderline", short: "Hold", band: "hold" },
    rejected: { label: "Rejected", short: "Rejected", band: "rejected" },
    duplicate: { label: "Duplicate Flagged", short: "Duplicates", band: "dup" },
  };
  const STAGE_ORDER = Object.keys(STAGES);
  const DIMENSIONS = [
    { key: "technical", label: "Technical skills match" },
    { key: "experience", label: "Experience & seniority" },
    { key: "impact", label: "Project & impact depth" },
    { key: "education", label: "Education & keywords" },
  ];
  const SORTS = { overall: "Overall fit", technical: "Technical", experience: "Experience", impact: "Impact", education: "Education", years: "Years of experience", name: "Name", scanned_at: "Newest first" };
  const LAYER_LABEL = { file: "File hash", contact: "Contact hash", semantic: "Semantic" };
  const VIEWS = { pipeline: "Candidates", scan: "Batch scan", jobs: "Job descriptions", audit: "Audit log", integrations: "Integrations" };
  const ACCEPTED = /\.(pdf|docx|txt|md)$/i;
  const DEFAULT_TH = { shortlist: 75, review: 60, hold: 45 };
  const DEFAULT_WEIGHTS = { technical: 40, experience: 25, impact: 20, education: 15 };

  // ------------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------------
  const state = {
    mode: prefs.get("ri.mode", "demo") === "live" ? "live" : "demo",
    view: "pipeline",
    settings: null,
    integrations: null,
    health: null,
    jds: [],
    samples: [],
    batches: [],
    filters: { q: "", stage: "all", batch: "all", minScore: null, sort: prefs.get("ri.sort", "overall"), order: prefs.get("ri.order", "desc") },
    rows: [],
    total: 0,
    stageCounts: {},
    analytics: null,
    loaded: false,
    error: null,
    selection: new Set(),
    drawer: { id: null, data: null, tab: "overview" },
    scan: { demoJd: null, demoSelected: null, liveJd: null, queue: [], skipped: [], run: null, logOpen: false },
    jobs: { selectedId: null, draft: null, saving: false, analyzing: false },
    audit: { entries: [], total: 0, filter: "", loading: false },
  };
  if (!SORTS[state.filters.sort]) state.filters.sort = "overall";
  let listToken = 0;
  let lastFocus = null;
  const ws = () => state.mode;
  // Per-file upload cap reported by the server (10 MB locally, 4 MB on Vercel).
  const maxFileMb = () => state.settings?.limits?.max_file_mb || 10;

  // ------------------------------------------------------------------------
  // API
  // ------------------------------------------------------------------------
  class ApiError extends Error {
    constructor(code, message, status) { super(message); this.code = code; this.status = status; }
  }

  async function api(path, { method = "GET", json, form } = {}) {
    const init = { method, headers: {} };
    if (json !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(json); }
    if (form) init.body = form;
    let res;
    try {
      res = await fetch(path, init);
    } catch {
      throw new ApiError("network", "Can't reach the server. Check that the API is running.", 0);
    }
    const type = res.headers.get("content-type") || "";
    const body = type.includes("application/json") ? await res.json().catch(() => null) : await res.text();
    if (!res.ok) {
      const err = body && body.error;
      throw new ApiError(err?.code || `http_${res.status}`, err?.message || `Request failed (${res.status}).`, res.status);
    }
    return body;
  }

  async function download(url, fallbackName) {
    try {
      const res = await fetch(url);
      if (!res.ok) {
        let msg = `Download failed (${res.status}).`;
        try { const j = await res.json(); msg = j.error?.message || msg; } catch { /* non-JSON error body */ }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const match = /filename="?([^";]+)"?/i.exec(res.headers.get("content-disposition") || "");
      const name = match ? match[1] : fallbackName;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      toast(`Downloaded ${name}`);
    } catch (e) {
      toast(e.message, "err");
    }
  }

  // ------------------------------------------------------------------------
  // UI primitives: toast, tooltip, menu, confirm
  // ------------------------------------------------------------------------
  function toast(message, kind = "ok", action) {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.setAttribute("role", kind === "err" ? "alert" : "status");
    el.innerHTML = `${icon(kind === "err" ? "alert" : "check")}<span>${esc(message)}</span>`;
    if (action) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = action.label;
      b.addEventListener("click", () => { el.remove(); action.run(); });
      el.append(b);
    }
    if (kind === "err") {
      // Errors stay until dismissed so they can be read.
      const x = document.createElement("button");
      x.type = "button";
      x.className = "toast-close";
      x.setAttribute("aria-label", "Dismiss");
      x.innerHTML = icon("x");
      x.addEventListener("click", () => el.remove());
      el.append(x);
    }
    const stack = $("#toasts");
    stack.append(el);
    while (stack.children.length > 3) stack.firstElementChild.remove();
    if (kind !== "err") setTimeout(() => el.remove(), 4500);
  }

  const tipEl = $("#tooltip");
  let tipTarget = null;
  function showTip(el) {
    const text = el.getAttribute("data-tip");
    if (!text) return;
    tipTarget = el;
    const title = el.getAttribute("data-tip-title");
    tipEl.innerHTML = `${title ? `<strong>${esc(title)}</strong>` : ""}${esc(text)}`;
    tipEl.hidden = false;
    const r = el.getBoundingClientRect();
    const t = tipEl.getBoundingClientRect();
    let top = r.top - t.height - 8;
    if (top < 8) top = r.bottom + 8;
    const left = clamp(r.left + r.width / 2 - t.width / 2, 8, innerWidth - t.width - 8);
    tipEl.style.top = `${top}px`;
    tipEl.style.left = `${left}px`;
  }
  function hideTip() { tipEl.hidden = true; tipTarget = null; }
  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (el && el !== tipTarget) showTip(el);
    else if (!el && tipTarget) hideTip();
  });
  // Keyboard focus shows a tip; programmatic focus after a click does not.
  document.addEventListener("focusin", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (el && e.target.matches(":focus-visible")) showTip(el);
  });
  document.addEventListener("focusout", hideTip);
  document.addEventListener("pointerdown", hideTip, true);
  addEventListener("scroll", hideTip, true);

  const menuEl = $("#menu");
  let menu = null;
  function openMenu(anchor, items, onSelect, { align = "start", title } = {}) {
    if (menu && menu.anchor === anchor) { closeMenu(); return; }
    closeMenu();
    hideTip();
    menuEl.innerHTML = (title ? `<div class="menu-title">${esc(title)}</div>` : "") + items.map((it, i) => {
      if (it.sep) return `<div class="menu-sep" role="separator"></div>`;
      return `<button type="button" class="menu-item ${it.danger ? "danger" : ""}" role="menuitem" data-i="${i}" ${it.disabled ? 'aria-disabled="true"' : ""}>`
        + `${it.glyph ? stageGlyph(it.glyph, `var(--gl-${STAGES[it.glyph].band})`) : it.icon ? icon(it.icon) : ""}<span class="grow">${esc(it.label)}${it.sub ? `<span class="sub">${esc(it.sub)}</span>` : ""}</span>`
        + `${it.hint ? `<span class="hint">${esc(it.hint)}</span>` : ""}${it.checked ? icon("check", "check") : ""}</button>`;
    }).join("");
    menuEl.hidden = false;
    const r = anchor.getBoundingClientRect();
    const m = menuEl.getBoundingClientRect();
    let top = r.bottom + 6;
    if (top + m.height > innerHeight - 8) top = Math.max(8, r.top - m.height - 6);
    const left = clamp(align === "end" ? r.right - m.width : r.left, 8, innerWidth - m.width - 8);
    menuEl.style.top = `${top}px`;
    menuEl.style.left = `${left}px`;
    menu = { anchor, items, onSelect };
    anchor.setAttribute("aria-expanded", "true");
    (menuEl.querySelector(".menu-item[aria-checked], .menu-item:not([aria-disabled])") || menuEl).focus?.();
  }
  function closeMenu() {
    if (!menu) return;
    menu.anchor.setAttribute("aria-expanded", "false");
    menuEl.hidden = true;
    menu = null;
  }
  menuEl.addEventListener("click", (e) => {
    const b = e.target.closest(".menu-item");
    if (!b || b.getAttribute("aria-disabled") || !menu) return;
    const { items, onSelect, anchor } = menu;
    closeMenu();
    if (document.contains(anchor)) anchor.focus({ preventScroll: true });
    onSelect(items[+b.dataset.i]);
  });
  menuEl.addEventListener("keydown", (e) => {
    const items = $$(".menu-item:not([aria-disabled])", menuEl);
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); const a = menu?.anchor; closeMenu(); a?.focus(); }
  });
  document.addEventListener("mousedown", (e) => {
    if (menu && !menuEl.contains(e.target) && !menu.anchor.contains(e.target)) closeMenu();
  });
  addEventListener("resize", closeMenu);

  function confirmDialog({ title, body, confirm = "Confirm", danger = true }) {
    const dlg = $("#confirm-dialog");
    $("#confirm-title").textContent = title;
    $("#confirm-body").textContent = body;
    const ok = $("#confirm-ok");
    ok.textContent = confirm;
    ok.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
    dlg.returnValue = "";
    return new Promise((resolve) => {
      dlg.addEventListener("close", () => resolve(dlg.returnValue === "confirm"), { once: true });
      dlg.showModal();
    });
  }

  // ------------------------------------------------------------------------
  // Shared renderers
  // ------------------------------------------------------------------------
  function ruler(score, th, dup) {
    const t = th || DEFAULT_TH;
    const bands = [["rejected", t.hold], ["hold", t.review - t.hold], ["review", t.shortlist - t.review], ["short", 100 - t.shortlist]];
    return `<div class="ruler ${dup ? "is-dup" : ""}" role="img" aria-label="Score ${score} of 100">`
      + `<div class="ruler-track">${bands.map(([b, w]) => `<span class="b-${b}" style="flex:${Math.max(w, 0)} 1 0"></span>`).join("")}</div>`
      + `<span class="ruler-mark" style="left:${clamp(score, 0, 100)}%"></span></div>`;
  }

  function rulerLarge(score, th, dup) {
    const t = th || DEFAULT_TH;
    const bands = [["rejected", t.hold], ["hold", t.review - t.hold], ["review", t.shortlist - t.review], ["short", 100 - t.shortlist]];
    const mark = score == null ? "" : `<span class="ruler-score" style="left:${clamp(score, 0, 100)}%">${score}</span><span class="ruler-mark" style="left:${clamp(score, 0, 100)}%"></span>`;
    return `<div class="ruler ruler-lg ${dup ? "is-dup" : ""}" role="img" aria-label="${score == null ? "Routing bands" : `Score ${score} of 100`}; hold from ${t.hold}, technical review from ${t.review}, shortlist from ${t.shortlist}">`
      + `<div class="ruler-track">${bands.map(([b, w]) => `<span class="b-${b}" style="flex:${Math.max(w, 0)} 1 0"></span>`).join("")}</div>${mark}</div>`
      + `<div class="ruler-scale" aria-hidden="true">`
      + [[0, "0", "first"], [t.hold, t.hold, ""], [t.review, t.review, ""], [t.shortlist, t.shortlist, ""], [100, "100", "last"]].map(([p, l, c]) => `<span class="tick ${c}" style="left:${p}%">${l}</span>`).join("")
      + `<span class="band-name" style="left:0">Rejected</span><span class="band-name" style="left:${t.hold}%">Hold</span>`
      + `<span class="band-name" style="left:${t.review}%">Tech review</span><span class="band-name" style="left:${t.shortlist}%">Shortlist</span></div>`;
  }

  const LAYER_SHORT = { file: "File", contact: "Contact", semantic: "Semantic" };

  function trace(d) {
    const parts = d.layers.map((l) => `${LAYER_LABEL[l.key]}: ${l.status}`);
    const text = d.status === "duplicate" && d.duplicate_of ? `Duplicate of ${d.duplicate_of.name} · ${parts.join(" · ")}` : parts.join(" · ");
    const label = d.status === "duplicate" ? LAYER_SHORT[d.primary_layer] || "Match" : d.status === "review" ? "Review" : "Unique";
    const cls = d.status === "duplicate" ? "is-match" : d.status === "review" ? "is-review" : "";
    return `<span class="trace-cell ${cls}" tabindex="0" data-tip="${esc(text)}" aria-label="${esc(text)}"><span class="trace">${d.layers.map((l) => `<i class="${esc(l.status)}"></i>`).join("")}</span>${label}</span>`;
  }

  const SHORT_BADGE = { shortlisted: "Shortlisted", technical_review: "Tech review", hold: "Hold", rejected: "Rejected", duplicate: "Duplicate" };
  // Stage glyphs on a 12px grid. Decisions are solid discs (check / cross), the
  // open stages are Harvey balls (3/4 review, 1/2 hold), and the copy mark flags
  // duplicates. Shape carries the stage without relying on colour.
  const RING = `<circle cx="6" cy="6" r="5.1" fill="none" stroke="currentColor" stroke-width="1.5"/>`;
  const STAGE_GLYPHS = {
    shortlisted: `<circle cx="6" cy="6" r="5.85" fill="currentColor"/><path class="ko" d="M3.55 6.15 5.25 7.8 8.45 4.55" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>`,
    technical_review: `${RING}<path d="M6 6V3.05A2.95 2.95 0 1 1 3.05 6Z" fill="currentColor"/>`,
    hold: `${RING}<path d="M6 3.05A2.95 2.95 0 0 1 6 8.95Z" fill="currentColor"/>`,
    rejected: `<circle cx="6" cy="6" r="5.85" fill="currentColor"/><path class="ko" d="M4.15 4.15 7.85 7.85M7.85 4.15 4.15 7.85" fill="none" stroke-width="1.5" stroke-linecap="round"/>`,
    duplicate: `<path d="M2.9 7.9h-.5A1.5 1.5 0 0 1 .9 6.4v-4A1.5 1.5 0 0 1 2.4.9h4a1.5 1.5 0 0 1 1.5 1.5v.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><rect x="4.1" y="4.1" width="7" height="7" rx="1.6" fill="currentColor"/>`,
  };
  const stageGlyph = (stage, color) => (STAGE_GLYPHS[stage] ? `<svg class="sg" viewBox="0 0 12 12" aria-hidden="true" focusable="false"${color ? ` style="color:${color}"` : ""}>${STAGE_GLYPHS[stage]}</svg>` : "");
  const badge = (stage) => `<span class="badge stage st-${stage}">${stageGlyph(stage)}<span class="lbl-long">${esc(STAGES[stage]?.label || stage)}</span><span class="lbl-short">${esc(SHORT_BADGE[stage] || stage)}</span></span>`;

  function stageButton(c, from = "row") {
    const over = c.stage_overridden ? `<span class="override-dot" data-tip="Set manually. Auto route: ${esc(STAGES[c.auto_stage].label)}"></span>` : "";
    const aria = `Stage: ${STAGES[c.stage].label}${c.stage_overridden ? ", set manually" : ""}. Change stage`;
    return `<button type="button" class="stage-btn" data-action="menu-stage" data-id="${c.id}" data-from="${from}" aria-haspopup="menu" aria-label="${esc(aria)}">${badge(c.stage)}${over}${icon("chevron-down")}</button>`;
  }

  const bandText = (j) => (j.experience_min == null ? "Any experience" : j.experience_max == null ? `${j.experience_min}+ yrs` : `${j.experience_min}–${j.experience_max} yrs`);

  // ------------------------------------------------------------------------
  // Shell: routing, mode, theme, status
  // ------------------------------------------------------------------------
  function navigate(view) {
    if (location.hash !== `#${view}`) location.hash = view;
    else route();
  }

  function route() {
    const v = location.hash.replace("#", "");
    state.view = VIEWS[v] ? v : "pipeline";
    $$(".view").forEach((s) => { s.hidden = s.dataset.view !== state.view; });
    $$(".nav a").forEach((a) => (a.dataset.nav === state.view ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    $("#page-title").textContent = VIEWS[state.view];
    document.title = `${VIEWS[state.view]} · Resume Intelligence`;
    $("#topbar-scan").hidden = state.view === "scan";
    closeRail();
    closeMenu();
    if (state.view === "pipeline") renderPipeline();
    if (state.view === "scan") renderScan();
    if (state.view === "jobs") loadJobsView();
    if (state.view === "audit") loadAudit(true);
    if (state.view === "integrations") loadIntegrations();
    renderPageMeta();
  }

  function renderPageMeta() {
    const el = $("#page-meta");
    let text = "";
    if (state.view === "pipeline" && state.loaded) text = `${fmtInt(state.stageCounts.all ?? 0)} candidates · ${scopeLabel()}`;
    if (state.view === "scan") text = state.scan.run ? `${state.scan.run.label} · ${state.scan.run.status === "running" ? "running" : "finished"}` : `${state.mode === "demo" ? "Demo" : "Live"} workspace`;
    if (state.view === "jobs") text = `${state.jds.length} job descriptions`;
    if (state.view === "audit") text = `${fmtInt(state.audit.total)} events`;
    if (state.view === "integrations") text = state.settings ? `Engine: ${engineLabel()}` : "";
    el.textContent = text;
  }

  function openRail() { $("#rail").classList.add("is-open"); $(".rail-scrim").hidden = false; }
  function closeRail() { $("#rail").classList.remove("is-open"); $(".rail-scrim").hidden = true; }

  function renderModeSwitch() {
    $$("#mode-switch button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === state.mode)));
    $("#topbar-scan span").textContent = state.mode === "demo" ? "Run batch scan" : "Upload resumes";
    $("#topbar-scan").querySelector("use").setAttribute("href", state.mode === "demo" ? "#i-play" : "#i-upload");
  }

  function renderBanner() {
    const el = $("#mode-banner");
    if (state.mode !== "demo") { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = `<span class="tag">DEMO</span><span><strong>Sample workspace.</strong> ${state.jds.length || 3} job descriptions from sample_jd/ and ${state.samples.length || 10} resumes from sample_resumes/. Each scan starts clean.</span>`
      + `<button type="button" class="btn btn-ghost" data-action="set-mode" data-mode="live">Switch to Live</button>`;
  }

  async function setMode(mode) {
    if (mode === state.mode) return;
    if (state.scan.run?.status === "running") { toast("A batch is still running. Switch after it finishes.", "err"); return; }
    state.mode = mode;
    prefs.set("ri.mode", mode);
    state.filters = { ...state.filters, batch: "all", stage: "all", q: "", minScore: null };
    $("#search").value = "";
    state.selection.clear();
    state.scan.run = null;
    state.jobs.selectedId = null;
    state.jobs.draft = null;
    state.analytics = null;
    state.rows = [];
    state.loaded = false;
    closeDrawer();
    renderModeSwitch();
    await loadWorkspace();
    renderBanner();
    route();
    toast(mode === "demo" ? "Demo workspace: sample JDs and resumes" : "Live workspace: your resumes and job descriptions");
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    prefs.set("ri.theme", theme);
    const b = $("#theme-btn");
    b.innerHTML = icon(theme === "dark" ? "sun" : "moon");
    b.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
    b.dataset.tip = theme === "dark" ? "Light theme" : "Dark theme";
  }

  const engineLabel = () => {
    const s = state.settings;
    if (!s) return "Deterministic engine";
    return s.provider === "deterministic" ? "Deterministic engine" : `Hybrid · ${s.providers[s.provider].label} ${s.providers[s.provider].model}`;
  };

  function renderRailStatus() {
    const s = state.settings;
    if (!s) return;
    $("#engine-dot").className = "status-dot on";
    $("#engine-label").textContent = engineLabel();
    $("#sheets-dot").className = `status-dot ${s.sheets.configured ? "on" : ""}`;
    $("#sheets-label").textContent = s.sheets.configured ? "Google Sheets connected" : "Google Sheets off";
  }

  function renderNavCount() {
    const total = state.batches.reduce((n, b) => n + Object.values(b.summary?.stage_counts || {}).reduce((a, c) => a + c, 0), 0);
    $("#nav-count").textContent = total ? fmtInt(total) : "";
  }

  // ------------------------------------------------------------------------
  // Workspace data
  // ------------------------------------------------------------------------
  async function loadWorkspace() {
    try {
      const [jds, batches] = await Promise.all([
        api(`/api/jds${qs({ workspace: ws() })}`),
        api(`/api/batches${qs({ workspace: ws() })}`),
      ]);
      state.jds = jds.jds;
      state.batches = batches.batches;
    } catch (e) {
      state.error = e.message;
    }
    if (state.filters.batch !== "all" && !state.batches.some((b) => b.id === state.filters.batch)) state.filters.batch = "all";
    ensureScanDefaults();
    renderNavCount();
    await refreshPipeline();
  }

  function ensureScanDefaults() {
    const samples = state.jds.filter((j) => j.kind === "sample");
    if (!samples.some((j) => j.id === state.scan.demoJd)) {
      state.scan.demoJd = (samples.find((j) => j.id === "sample-backend_engineer") || samples[0] || {}).id || null;
    }
    if (!state.scan.demoSelected) state.scan.demoSelected = new Set(state.samples.map((s) => s.filename));
    if (!state.jds.some((j) => j.id === state.scan.liveJd)) {
      const custom = state.jds.find((j) => j.kind === "custom");
      state.scan.liveJd = (custom || state.jds.find((j) => j.id === "sample-backend_engineer") || state.jds[0] || {}).id || null;
    }
  }

  // ------------------------------------------------------------------------
  // Candidates view
  // ------------------------------------------------------------------------
  async function refreshPipeline() {
    const token = ++listToken;
    const f = state.filters;
    const batchId = f.batch === "all" ? null : f.batch;
    if (state.loaded) $("#cand-table").classList.add("stale");
    else renderSkeletons();
    try {
      const [list, analytics] = await Promise.all([
        api(`/api/candidates${qs({ workspace: ws(), batch_id: batchId, stage: f.stage, q: f.q.trim(), min_score: f.minScore, sort: f.sort, order: f.order })}`),
        api(`/api/analytics${qs({ workspace: ws(), batch_id: batchId })}`),
      ]);
      if (token !== listToken) return;
      state.rows = list.rows;
      state.total = list.total;
      state.stageCounts = list.stage_counts;
      state.analytics = analytics;
      state.error = null;
      const visible = new Set(state.rows.map((r) => r.id));
      [...state.selection].forEach((id) => { if (!visible.has(id)) state.selection.delete(id); });
    } catch (e) {
      if (token !== listToken) return;
      state.error = e.message;
    }
    state.loaded = true;
    $("#cand-table").classList.remove("stale");
    renderPipeline();
  }

  function renderSkeletons() {
    $("#kpis").innerHTML = Array.from({ length: 5 }, () => `<div class="kpi skeleton"><div class="kpi-label"><span class="sk" style="width:60%"></span></div><div class="kpi-value">00</div><div class="kpi-sub">—</div></div>`).join("");
    $("#cand-body").innerHTML = Array.from({ length: 6 }, () => `<tr class="skeleton"><td class="col-check"></td><td><span class="sk" style="width:70%"></span></td><td><span class="sk" style="width:80%"></span></td><td class="col-num"><span class="sk"></span></td><td class="col-num"><span class="sk"></span></td><td class="col-num hide-md"><span class="sk"></span></td><td class="col-num hide-md"><span class="sk"></span></td><td class="hide-sm hide-lg"><span class="sk" style="width:70%"></span></td><td class="hide-sm"><span class="sk" style="width:40px"></span></td><td><span class="sk" style="width:90px"></span></td></tr>`).join("");
  }

  function renderPipeline() {
    if (!state.loaded) return;
    const err = $("#pipeline-error");
    if (state.error && state.rows.length) {
      err.hidden = false;
      err.innerHTML = `${icon("alert")}<span>Couldn't refresh: ${esc(state.error)} These are the last loaded numbers.</span><button type="button" class="btn" data-action="retry-pipeline">${icon("refresh")}Retry</button>`;
    } else err.hidden = true;
    renderScope();
    renderKpis();
    renderTabs();
    renderTable();
    renderBulk();
    renderDistribution();
    renderGaps();
    renderPageMeta();
    renderNavCount();
  }

  function scopeLabel() {
    if (state.filters.batch === "all") return "All batches";
    const b = state.batches.find((x) => x.id === state.filters.batch);
    return b ? b.label : "All batches";
  }

  function renderScope() {
    const b = state.batches.find((x) => x.id === state.filters.batch);
    const rescore = $("#rescore-btn");
    rescore.hidden = !b || b.status === "running";
    rescore.disabled = state.scan.run?.status === "running";
    $("#scope-label").textContent = b ? `${b.label} · ${b.jd_title}` : "All batches";
    $("#scope-meta").innerHTML = b
      ? `<span class="mono">${esc(fmtDateTime(b.created_at))}</span> · ${b.provider === "deterministic" ? "deterministic engine" : esc(b.provider)}`
      : `${state.batches.length} batch${state.batches.length === 1 ? "" : "es"}`;
  }

  function delta(cur, prev, better, unit = "") {
    if (cur == null || prev == null) return "";
    if (better === "count" && prev < 5) return `<span class="delta flat">was ${prev}</span>`;
    const diff = cur - prev;
    if (Math.abs(diff) < 0.5) return `<span class="delta flat">±0${unit}</span>`;
    const good = better === "higher" ? diff > 0 : better === "lower" ? diff < 0 : null;
    const cls = good == null ? "flat" : good ? "up" : "down";
    const n = Math.abs(diff) >= 10 || unit === "" ? Math.round(Math.abs(diff)) : Math.abs(diff).toFixed(1);
    return `<span class="delta ${cls}">${icon(diff > 0 ? "arrow-up" : "arrow-down")}${n}${unit}</span>`;
  }

  function renderKpis() {
    const a = state.analytics;
    if (!a) return;
    const c = a.current;
    const p = a.previous;
    const vs = p ? `<span>vs ${esc(p.batch_label || "prev.")}</span>` : "";
    const tiles = [
      {
        label: "Total scanned", value: fmtInt(c.total_scanned),
        sub: p ? `${delta(c.total_scanned, p.total_scanned, "count")}${vs}` : `<span>${c.total_scanned ? `${fmtInt(c.unique)} unique` : "No resumes yet"}</span>`,
        tip: "Resumes parsed and scored in this scope, duplicates included.",
      },
      {
        label: "Shortlist conversion", value: c.shortlist_rate == null ? "—" : c.shortlist_rate.toFixed(c.shortlist_rate % 1 ? 1 : 0), unit: c.shortlist_rate == null ? "" : "%",
        sub: `${p ? delta(c.shortlist_rate, p.shortlist_rate, "higher", " pp") : ""}<span>${c.unique ? `${c.shortlisted} of ${c.unique} unique` : "—"}</span>`,
        tip: "Shortlisted candidates as a share of unique candidates.",
      },
      {
        label: "Duplicates blocked", value: fmtInt(c.duplicates_blocked),
        sub: `${p ? delta(c.duplicates_blocked, p.duplicates_blocked, "count") : ""}<span>${c.total_scanned ? `${Math.round(c.duplicate_rate)}% of intake` : "—"}</span>`,
        tip: "Flagged by file hash, contact hash or semantic similarity before reaching a recruiter.",
      },
      {
        label: "Avg match score", value: c.avg_match == null ? "—" : Math.round(c.avg_match), unit: c.avg_match == null ? "" : "/100",
        sub: `${p ? delta(c.avg_match, p.avg_match, "higher") : ""}<span>${c.median_match == null ? "—" : `median ${Math.round(c.median_match)}`}</span>`,
        tip: "Mean overall role fit of unique candidates.",
      },
      {
        label: "Processing speed", value: c.median_ms == null ? "—" : Math.round(c.median_ms), unit: c.median_ms == null ? "" : "ms",
        sub: `${p ? delta(c.median_ms, p.median_ms, "lower", " ms") : ""}<span>${c.throughput_per_min ? `${fmtInt(Math.round(c.throughput_per_min))} resumes/min` : "per resume"}</span>`,
        tip: "Median end-to-end time per resume: parse, deduplicate, score and route.",
      },
    ];
    $("#kpis").innerHTML = tiles.map((t) => `<div class="kpi" tabindex="0" data-tip="${esc(t.tip)}"><div class="kpi-label">${esc(t.label)}</div>`
      + `<div class="kpi-value">${t.value}${t.unit ? `<small>${t.unit}</small>` : ""}</div><div class="kpi-sub">${t.sub}</div></div>`).join("");
  }

  function renderTabs() {
    const c = state.stageCounts || {};
    const tabs = [["all", "All", null], ...STAGE_ORDER.map((k) => [k, STAGES[k].short, STAGES[k].band])];
    $("#stage-tabs").innerHTML = tabs.map(([k, label, band]) => `<button type="button" class="stage-tab" role="tab" aria-selected="${state.filters.stage === k}" data-action="stage-filter" data-stage="${k}" title="${esc(k === "all" ? "All stages" : STAGES[k].label)}">`
      + `${band ? stageGlyph(k, `var(--gl-${band})`) : ""}<span class="lbl">${esc(label)}</span><span class="count">${c[k] ?? 0}</span></button>`).join("");
    $("#minscore-label").textContent = state.filters.minScore == null ? "Any" : `${state.filters.minScore}+`;
    $("#sort-label").textContent = SORTS[state.filters.sort];
  }

  function renderTable() {
    const f = state.filters;
    $$(".th-sort").forEach((b) => {
      const active = b.dataset.sort === f.sort;
      b.toggleAttribute("data-active", active);
      b.querySelector(".ic")?.remove();
      if (active) b.insertAdjacentHTML("beforeend", icon(f.order === "asc" ? "arrow-up" : "arrow-down"));
      b.closest("th").setAttribute("aria-sort", active ? (f.order === "asc" ? "ascending" : "descending") : "none");
    });
    const body = $("#cand-body");
    const foot = $("#table-foot");
    if (state.error && !state.rows.length) {
      body.innerHTML = `<tr><td colspan="10"><div class="empty">${icon("alert")}<h3>Couldn't load candidates</h3><p>${esc(state.error)}</p><div class="actions"><button type="button" class="btn" data-action="retry-pipeline">${icon("refresh")}Retry</button></div></div></td></tr>`;
      foot.innerHTML = "";
      return;
    }
    if (!state.rows.length) {
      body.innerHTML = `<tr><td colspan="10">${emptyState()}</td></tr>`;
      foot.innerHTML = "";
      $("#check-all").checked = false;
      return;
    }
    body.innerHTML = state.rows.map(rowHtml).join("");
    const all = state.rows.length && state.rows.every((r) => state.selection.has(r.id));
    $("#check-all").checked = all;
    $("#check-all").indeterminate = !all && state.selection.size > 0;
    foot.innerHTML = `<span><span class="mono">${fmtInt(state.rows.length)}</span> of <span class="mono">${fmtInt(state.stageCounts.all)}</span> · sorted by ${esc(SORTS[f.sort].toLowerCase())}</span><span class="hide-sm"><kbd>/</kbd> search · <kbd>Enter</kbd> open · <kbd>J</kbd> <kbd>K</kbd> next · <kbd>S</kbd> <kbd>T</kbd> <kbd>H</kbd> <kbd>R</kbd> set stage</span>`;
  }

  function emptyState() {
    const filtered = state.filters.q || state.filters.stage !== "all" || state.filters.minScore != null;
    if (filtered && (state.stageCounts.all || state.analytics?.current.total_scanned)) {
      return `<div class="empty">${icon("search")}<h3>No candidates match</h3><p>Nothing in ${esc(scopeLabel().toLowerCase())} matches these filters.</p><div class="actions"><button type="button" class="btn" data-action="clear-filters">Clear filters</button></div></div>`;
    }
    if (state.mode === "demo") {
      return `<div class="empty">${icon("layers")}<h3>No demo candidates yet</h3><p>Run the sample batch: ${state.samples.length || 10} resumes, two of them planted duplicates, scored against the Senior Python Backend Engineer JD.</p>`
        + `<div class="actions"><button type="button" class="btn btn-primary" data-action="run-demo-now">${icon("play")}Run demo scan</button><button type="button" class="btn" data-action="nav" data-to="scan">Choose JD and resumes</button></div></div>`;
    }
    return `<div class="empty">${icon("upload")}<h3>No candidates in the Live workspace</h3><p>Upload a folder of resumes and score them against one of your job descriptions.</p>`
      + `<div class="actions"><button type="button" class="btn btn-primary" data-action="nav" data-to="scan">${icon("upload")}Upload resumes</button><button type="button" class="btn" data-action="nav" data-to="jobs">${icon("plus")}New job description</button></div></div>`;
  }

  function rowHtml(r) {
    const sel = state.selection.has(r.id);
    const sk = r.skills;
    const miss = sk.missing_critical;
    const gapHtml = miss.length
      ? `<span class="gap-name">Missing ${esc(miss[0])}</span>${miss.length > 1 ? `<span class="gap-more">+${miss.length - 1}</span>` : ""}`
      : "All critical covered";
    const sub = [r.title, r.city].filter(Boolean).join(" · ") || r.email || r.file_name;
    return `<tr class="row ${sel ? "is-selected" : ""} ${state.drawer.id === r.id ? "is-open" : ""}" data-id="${r.id}" tabindex="0" aria-label="${esc(r.name)}, fit ${r.scores.overall}, ${esc(STAGES[r.stage].label)}">`
      + `<td class="col-check" data-stop><input type="checkbox" data-action="select-row" data-id="${r.id}" ${sel ? "checked" : ""} aria-label="Select ${esc(r.name)}"></td>`
      + `<td class="col-name"><div class="cell-person">${avatar(r.name)}<div><div class="cell-name">${esc(r.name)}</div><div class="cell-sub">${esc(sub)}</div></div></div></td>`
      + `<td class="col-fit"><div class="cell-fit"><span class="fit-num">${r.scores.overall}</span>${ruler(r.scores.overall, r.thresholds, r.stage === "duplicate")}${r.knockout ? `<span class="knock" data-tip="Capped: covers under 35% of critical requirements">capped</span>` : ""}</div></td>`
      + `<td class="col-num">${r.scores.technical}</td><td class="col-num">${r.scores.experience}</td>`
      + `<td class="col-num hide-md">${r.scores.impact}</td><td class="col-num hide-md">${r.scores.education}</td>`
      + `<td class="col-skills hide-sm hide-lg"><div class="skills-cell"><span class="ratio"><span class="mono">${sk.critical.matched}/${sk.critical.total}</span> critical</span><span class="gap ${miss.length ? "" : "none"}" ${miss.length ? `data-tip="${esc(`Missing: ${miss.join(", ")}`)}"` : ""}>${gapHtml}</span></div></td>`
      + `<td class="col-dedup hide-sm">${trace(r.dedup)}</td>`
      + `<td class="col-stage" data-stop>${stageButton(r)}</td></tr>`;
  }

  function renderBulk() {
    const n = state.selection.size;
    const el = $("#bulkbar");
    el.hidden = n === 0;
    if (!n) return;
    const canCompare = n >= 2 && n <= 4;
    el.innerHTML = `<strong>${n} selected</strong>`
      + `<button type="button" class="btn ${canCompare ? "btn-primary" : ""}" data-action="bulk-compare" ${canCompare ? "" : `aria-disabled="true" data-tip="Select 2 to 4 candidates to compare"`}>${icon("sliders")}Compare</button>`
      + `<button type="button" class="btn" data-action="bulk-stage" aria-haspopup="menu">Move to stage${icon("chevron-down", "sm")}</button>`
      + `<button type="button" class="btn" data-action="bulk-auto">${icon("undo")}Restore auto stage</button>`
      + `<button type="button" class="btn" data-action="bulk-export">${icon("download")}Export selected</button>`
      + `<button type="button" class="btn btn-danger" data-action="bulk-delete">${icon("trash")}Delete</button>`
      + `<button type="button" class="btn btn-ghost" data-action="bulk-clear">Clear selection</button>`;
  }

  function renderDistribution() {
    const el = $("#distribution");
    const rows = state.rows;
    const th = rows[0]?.thresholds || state.analytics?.thresholds || DEFAULT_TH;
    $("#dist-meta").textContent = rows.length ? `${rows.length} shown · thresholds ${th.hold} / ${th.review} / ${th.shortlist}` : "";
    if (!rows.length) {
      el.innerHTML = `<div class="empty-inline">Each candidate appears here as a dot on the routing scale after the first scan.</div>`;
      return;
    }
    const bins = new Map();
    [...rows].sort((a, b) => (a.stage === "duplicate") - (b.stage === "duplicate") || b.scores.overall - a.scores.overall).forEach((r) => {
      const key = Math.min(49, Math.floor(r.scores.overall / 2));
      if (!bins.has(key)) bins.set(key, []);
      bins.get(key).push(r);
    });
    const maxRows = 11;
    let dots = "";
    bins.forEach((list, key) => {
      const left = key * 2 + 1;
      list.slice(0, maxRows).forEach((r, i) => {
        const dup = r.stage === "duplicate";
        dots += `<button type="button" class="dist-dot ${dup ? "dup" : ""}" data-action="open-candidate" data-id="${r.id}" style="left:${left}%;bottom:${14 + i * 12}px;--dot:var(--band-${STAGES[r.stage].band})" data-tip-title="${r.scores.overall}" data-tip="${esc(`${r.name} · ${STAGES[r.stage].label}`)}" aria-label="${esc(`${r.name}, ${r.scores.overall}, ${STAGES[r.stage].label}`)}"></button>`;
      });
      if (list.length > maxRows) dots += `<span class="dist-overflow" style="left:${left}%;bottom:${14 + maxRows * 12}px">+${list.length - maxRows}</span>`;
    });
    const bands = [["rejected", th.hold], ["hold", th.review - th.hold], ["review", th.shortlist - th.review], ["short", 100 - th.shortlist]];
    el.innerHTML = `<div class="dist-plot">`
      + `<div class="dist-bands">${bands.map(([b, w]) => `<span style="flex:${w} 1 0;background:color-mix(in srgb, var(--band-${b}) 30%, var(--card))"></span>`).join("")}</div>`
      + [["Hold", th.hold], ["Technical review", th.review], ["Shortlist", th.shortlist]].map(([l, v]) => `<div class="dist-threshold" style="left:${v}%" data-tip="${l} from ${v}"><span>${v}</span></div>`).join("")
      + dots + `</div>`
      + `<div class="dist-axis">${[0, 20, 40, 60, 80, 100].map((v) => `<span style="left:${v}%">${v}</span>`).join("")}</div>`
      + `<div class="legend">${STAGE_ORDER.map((k) => `<span><i class="${k === "duplicate" ? "ring" : ""}" style="background:var(--band-${STAGES[k].band})"></i>${esc(STAGES[k].label)}</span>`).join("")}</div>`;
  }

  function renderGaps() {
    const el = $("#gaps");
    const a = state.analytics;
    const gaps = (a?.skill_gaps || []).slice(0, 6);
    if (!gaps.length) {
      el.innerHTML = `<div class="empty-inline">${a?.current.unique ? "Every unique candidate in this scope covers the critical requirements." : "Critical requirements most candidates lack appear here after the first scan."}</div>`;
      return;
    }
    el.innerHTML = `<div class="rank-list">${gaps.map((g) => `<div class="rank-row" tabindex="0" data-tip="${esc(`${g.missing} of ${a.current.unique} unique candidates lack ${g.skill}`)}">`
      + `<span class="label">${esc(g.skill)}</span><span class="val">${g.missing}</span><span class="share">${g.share}%</span><span class="bar"><i style="width:${g.share}%"></i></span></div>`).join("")}</div>`;
  }

  async function changeStage(ids, stage, { undoable = true, from } = {}) {
    const rows = ids.map((id) => state.rows.find((r) => r.id === id) || (state.drawer.data?.id === id ? state.drawer.data : null)).filter(Boolean);
    const previous = new Map(rows.map((r) => [r.id, r.stage]));
    try {
      if (ids.length === 1 && stage !== "__auto") await api(`/api/candidates/${ids[0]}`, { method: "PATCH", json: { stage } });
      else await api("/api/candidates/bulk", { method: "POST", json: stage === "__auto" ? { ids, action: "restore_auto" } : { ids, action: "stage", stage } });
    } catch (e) { toast(e.message, "err"); return; }
    const name = rows.length === 1 ? (rows[0].name || rows[0].profile?.name) : `${ids.length} candidates`;
    const label = stage === "__auto" ? "their auto stage" : STAGES[stage].label;
    toast(`Moved ${name} to ${label}`, "ok", undoable && from !== "undo" ? {
      label: "Undo",
      run: async () => {
        const groups = {};
        previous.forEach((st, id) => { (groups[st] = groups[st] || []).push(id); });
        for (const [st, list] of Object.entries(groups)) await changeStage(list, st, { undoable: false, from: "undo" });
      },
    } : undefined);
    await refreshPipeline();
    if (state.drawer.id && ids.includes(state.drawer.id)) openDrawer(state.drawer.id, { keepTab: true });
  }

  function openStageMenu(anchor, id) {
    const c = state.rows.find((r) => r.id === id) || (state.drawer.data?.id === id ? { ...state.drawer.data, name: state.drawer.data.profile.name } : null);
    if (!c) return;
    const items = STAGE_ORDER.map((k) => ({ label: STAGES[k].label, value: k, glyph: k, checked: c.stage === k, hint: c.auto_stage === k ? "auto" : "" }));
    if (c.stage_overridden) items.push({ sep: true }, { label: `Restore auto stage`, sub: STAGES[c.auto_stage].label, value: "__auto", icon: "undo" });
    openMenu(anchor, items, (it) => { if (it.value !== c.stage) changeStage([id], it.value); }, { title: "Move to stage", align: "end" });
  }

  async function deleteCandidates(ids) {
    const ok = await confirmDialog({
      title: ids.length === 1 ? "Delete this candidate?" : `Delete ${ids.length} candidates?`,
      body: "They are removed from the talent pool and the deduplication registry, so a re-upload will be treated as new. The audit log keeps a record of the deletion.",
      confirm: "Delete",
    });
    if (!ok) return;
    try {
      const res = await api("/api/candidates/bulk", { method: "POST", json: { ids, action: "delete" } });
      ids.forEach((id) => state.selection.delete(id));
      if (ids.includes(state.drawer.id)) closeDrawer();
      toast(`Deleted ${res.affected} candidate${res.affected === 1 ? "" : "s"}`);
      await loadWorkspace();
    } catch (e) { toast(e.message, "err"); }
  }

  function exportUrl(ids) {
    const f = state.filters;
    return `/api/exports/candidates.xlsx${qs({ workspace: ws(), batch_id: f.batch === "all" ? null : f.batch, stage: ids ? null : f.stage, q: ids ? null : f.q.trim(), ids: ids ? ids.join(",") : null })}`;
  }

  async function rescoreBatch(jdId) {
    const batch = state.batches.find((b) => b.id === state.filters.batch);
    if (!batch) return;
    const btn = $("#rescore-btn");
    btn.disabled = true;
    btn.querySelector("span").textContent = "Rescoring…";
    try {
      const res = await api(`/api/batches/${batch.id}/rescore`, { method: "POST", json: { jd_id: jdId } });
      toast(`${batch.label} rescored against ${res.jd_title} · ${res.changed_stage} changed stage${res.skipped.length ? ` · ${res.skipped.length} skipped` : ""}`);
      closeDrawer();
      await loadWorkspace();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      btn.disabled = false;
      btn.querySelector("span").textContent = "Rescore batch";
    }
  }

  // Side-by-side comparison of 2-4 selected candidates, built from the table rows already loaded.
  function openCompare(ids) {
    const rows = ids.map((id) => state.rows.find((r) => r.id === id)).filter(Boolean);
    if (rows.length < 2) { toast("Select 2 to 4 candidates to compare.", "err"); return; }
    const best = (get, higher = true) => {
      const vals = rows.map(get);
      const target = higher ? Math.max(...vals) : Math.min(...vals);
      return (v) => vals.filter((x) => x === target).length < rows.length && v === target;
    };
    const cell = (v, isBest, extra = "") => `<div class="cmp-cell ${isBest ? "is-best" : ""}"><div class="cmp-val">${v}${isBest ? `<span class="cmp-best">${icon("check", "sm")}Best</span>` : ""}</div>${extra}</div>`;
    const dimRow = (label, key) => {
      const isBest = best((r) => r.scores[key]);
      return `<div class="cmp-label">${label}</div>` + rows.map((r) => cell(`<span class="cmp-num">${r.scores[key]}</span>`, isBest(r.scores[key]), `<span class="cmp-bar"><i style="width:${r.scores[key]}%"></i></span>`)).join("");
    };
    const fitBest = best((r) => r.scores.overall);
    const covBest = best((r) => r.skills.critical_coverage);
    const yrsBest = best((r) => r.years || 0);
    $("#compare-meta").textContent = `${rows.length} candidates · ${rows[0].jd_title}`;
    $("#compare-body").style.setProperty("--cols", rows.length);
    $("#compare-body").innerHTML = `<div class="cmp-grid">`
      + `<div class="cmp-label"></div>` + rows.map((r) => `<div class="cmp-person">${avatar(r.name)}<div><div class="cell-name">${esc(r.name)}</div><div class="cell-sub">${esc(r.title || r.email || "")}</div></div></div>`).join("")
      + `<div class="cmp-label">Stage</div>` + rows.map((r) => `<div class="cmp-cell">${badge(r.stage)}</div>`).join("")
      + `<div class="cmp-label">Overall role fit</div>` + rows.map((r) => cell(`<span class="cmp-num lg">${r.scores.overall}</span>`, fitBest(r.scores.overall), ruler(r.scores.overall, r.thresholds, r.stage === "duplicate"))).join("")
      + dimRow("Technical skills", "technical") + dimRow("Experience & seniority", "experience") + dimRow("Project & impact", "impact") + dimRow("Education & keywords", "education")
      + `<div class="cmp-label">Critical coverage</div>` + rows.map((r) => cell(`<span class="cmp-num">${r.skills.critical.matched}/${r.skills.critical.total}</span>`, covBest(r.skills.critical_coverage))).join("")
      + `<div class="cmp-label">Experience</div>` + rows.map((r) => cell(`<span class="cmp-num">${fmtYears(r.years)}</span>`, yrsBest(r.years || 0))).join("")
      + `<div class="cmp-label">Missing critical</div>` + rows.map((r) => `<div class="cmp-cell"><div class="chips">${r.skills.missing_critical.slice(0, 3).map((m) => `<span class="chip miss">${icon("x", "sm")}${esc(m)}</span>`).join("") || `<span class="muted">None</span>`}${r.skills.missing_critical.length > 3 ? `<span class="muted">+${r.skills.missing_critical.length - 3}</span>` : ""}</div></div>`).join("")
      + `<div class="cmp-label">Dedup</div>` + rows.map((r) => `<div class="cmp-cell">${trace(r.dedup)}</div>`).join("")
      + `<div class="cmp-label">Location</div>` + rows.map((r) => `<div class="cmp-cell">${esc(r.city || "Not stated")}</div>`).join("")
      + `<div class="cmp-label"></div>` + rows.map((r) => `<div class="cmp-cell"><button type="button" class="btn" data-action="compare-open" data-id="${r.id}">Open profile${icon("chevron-right")}</button></div>`).join("")
      + `</div>`;
    $("#compare-dialog").showModal();
  }

  async function syncSheets() {
    const sheets = state.settings?.sheets;
    if (sheets && !sheets.configured) {
      // Known locally: say what is missing instead of making a request that must fail.
      toast(`Google Sheets is not connected. Missing: ${sheets.missing.join(", ")}.`, "err",
        state.view === "integrations" ? undefined : { label: "Set up", run: () => navigate("integrations") });
      return;
    }
    try {
      const res = await api("/api/integrations/sheets/sync", { method: "POST", json: { workspace: ws() } });
      toast(`Synced ${res.rows} rows to Google Sheets`, "ok", res.sheet_url ? { label: "Open sheet", run: () => window.open(res.sheet_url, "_blank", "noopener") } : undefined);
      loadSettings();
    } catch (e) {
      toast(e.message, "err", e.code === "sheets_not_configured" ? { label: "Set up", run: () => navigate("integrations") } : undefined);
    }
  }

  // ------------------------------------------------------------------------
  // Candidate drawer
  // ------------------------------------------------------------------------
  function markOpenRow() {
    $$("#cand-body tr.row").forEach((tr) => tr.classList.toggle("is-open", tr.dataset.id === state.drawer.id));
  }

  async function openDrawer(id, { keepTab } = {}) {
    const d = $("#drawer");
    const s = $("#drawer-scrim");
    if (!keepTab && state.drawer.id !== id) state.drawer.tab = "overview";
    state.drawer.id = id;
    if (d.hidden) {
      lastFocus = document.activeElement;
      d.hidden = false;
      s.hidden = false;
      requestAnimationFrame(() => { d.classList.add("is-open"); s.classList.add("is-open"); });
    }
    markOpenRow();
    if (!state.drawer.data || state.drawer.data.id !== id) {
      d.innerHTML = `<div class="drawer-loading"><span class="sk" style="width:45%;height:16px"></span><span class="sk" style="width:70%"></span><span class="sk" style="width:100%;height:120px;border-radius:10px"></span><span class="sk" style="width:100%;height:180px;border-radius:10px"></span></div>`;
    }
    try {
      const data = await api(`/api/candidates/${id}`);
      if (state.drawer.id !== id) return;
      state.drawer.data = data;
      renderDrawer();
      if (!keepTab) $("#drawer [data-action='close-drawer']")?.focus({ preventScroll: true });
    } catch (e) {
      if (state.drawer.id !== id) return;
      d.innerHTML = `<div class="drawer-head"><span></span><div><h2 id="drawer-title">Candidate unavailable</h2><p>${esc(e.message)}</p></div><div class="drawer-nav"><button type="button" class="icon-btn" data-action="close-drawer" aria-label="Close">${icon("x")}</button></div></div>`;
    }
  }

  function closeDrawer() {
    const d = $("#drawer");
    if (d.hidden) return;
    d.classList.remove("is-open");
    $("#drawer-scrim").classList.remove("is-open");
    setTimeout(() => {
      if (!d.classList.contains("is-open")) { d.hidden = true; $("#drawer-scrim").hidden = true; }
    }, 260);
    state.drawer.id = null;
    state.drawer.data = null;
    markOpenRow();
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
  }

  function stepDrawer(dir) {
    const idx = state.rows.findIndex((r) => r.id === state.drawer.id);
    const next = state.rows[idx + dir];
    if (next) openDrawer(next.id, { keepTab: true });
  }

  function renderDrawer() {
    const c = state.drawer.data;
    if (!c) return;
    const p = c.profile;
    const idx = state.rows.findIndex((r) => r.id === c.id);
    const tab = state.drawer.tab;
    const tabs = [["overview", "Overview", "Overview"], ["skills", "Skills & experience", "Skills"], ["integrity", "Dedup & processing", "Dedup"], ["activity", "Notes & activity", "Notes"]];
    const sub = [p.current_title, p.current_company].filter(Boolean).join(" · ") || p.headline || c.file.name;
    $("#drawer").innerHTML = `<div class="drawer-head">${avatar(p.name, true)}<div><h2 id="drawer-title">${esc(p.name)}</h2><p>${esc(sub)}</p></div>`
      + `<div class="drawer-nav"><button type="button" class="icon-btn" data-action="drawer-prev" aria-label="Previous candidate" data-tip="Previous (K)" ${idx <= 0 ? "disabled" : ""}>${icon("chevron-up")}</button>`
      + `<button type="button" class="icon-btn" data-action="drawer-next" aria-label="Next candidate" data-tip="Next (J)" ${idx < 0 || idx >= state.rows.length - 1 ? "disabled" : ""}>${icon("chevron-down")}</button>`
      + `<button type="button" class="icon-btn" data-action="close-drawer" aria-label="Close" data-tip="Close (Esc)">${icon("x")}</button></div></div>`
      + `<div class="drawer-actions">${stageButton(c, "drawer")}${c.stage_overridden ? `<span class="auto-note">${icon("cpu", "sm")}Auto route: ${esc(STAGES[c.auto_stage].label)}</span>` : ""}<span class="spacer"></span>`
      + `<button type="button" class="btn" data-action="download-resume" data-id="${c.id}">${icon("download")}Resume</button>`
      + `<button type="button" class="icon-btn bordered" data-action="delete-candidate" data-id="${c.id}" aria-label="Delete candidate" data-tip="Delete from talent pool">${icon("trash")}</button></div>`
      + `<div class="drawer-tabs" role="tablist">${tabs.map(([k, l, s]) => `<button type="button" role="tab" aria-selected="${tab === k}" data-action="drawer-tab" data-tab="${k}" aria-label="${esc(l)}"><span class="lbl-long">${esc(l)}</span><span class="lbl-short">${esc(s)}</span></button>`).join("")}</div>`
      + `<div class="drawer-body" id="drawer-body">${tab === "overview" ? drawerOverview(c) : tab === "skills" ? drawerSkills(c) : tab === "integrity" ? drawerIntegrity(c) : drawerActivity(c)}</div>`;
  }

  function drawerOverview(c) {
    const p = c.profile;
    const s = c.scores;
    const rec = c.recommendation;
    const dup = c.dedup.duplicate_of;
    const list = (items, cls, title) => (items?.length ? `<div class="rec-list ${cls}"><h4>${title}</h4><ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "");
    const contacts = [
      ["mail", p.email, p.email ? `<a href="mailto:${esc(p.email)}">${esc(p.email)}</a>` : "No email found", p.email && "Email"],
      ["phone", p.phone, p.phone ? `<span class="mono">${esc(p.phone)}</span>` : "No phone found", p.phone && "Phone"],
      ["user", p.linkedin, p.linkedin ? `<a href="${esc(p.linkedin)}" target="_blank" rel="noopener">${esc(p.linkedin.replace(/^https?:\/\/(www\.)?/, ""))}</a>` : "No LinkedIn", null],
      ["code", p.github, p.github ? `<a href="${esc(p.github)}" target="_blank" rel="noopener">${esc(p.github.replace(/^https?:\/\/(www\.)?/, ""))}</a>` : "No GitHub", null],
      ["pin", p.location, esc(p.location || "Location not stated"), null],
      ["briefcase", p.total_experience_years, `${fmtYears(p.total_experience_years)} <span class="muted">· ${esc(p.experience_source)}</span>`, null],
    ];
    return `${dup && c.stage === "duplicate" ? `<div class="callout dup">${icon("shield")}<span>Duplicate of <button type="button" class="link-btn" data-action="open-candidate" data-id="${dup.candidate_id}">${esc(dup.name)}</button> (${esc(dup.filename || "")}), caught by the ${esc(LAYER_LABEL[c.dedup.primary_layer] || "")} layer.</span></div>` : ""}`
      + `<section class="d-section"><h3>Overall role fit<span class="meta">${esc(c.jd.title)}</span></h3><div class="fit-hero"><div class="score">${s.overall}<small>/100</small></div><div>${rulerLarge(s.overall, c.thresholds, c.stage === "duplicate")}</div></div>`
      + `${c.knockout ? `<div class="callout warn">${icon("alert")}<span>${esc(c.knockout)}</span></div>` : ""}</section>`
      + `<section class="d-section"><div class="rec"><div class="rec-head">${esc(rec.headline)}<span class="engine">${esc(c.engine.label)}${c.engine.fallback_reason ? ` · ${esc(c.engine.fallback_reason)}` : ""}</span></div><p>${esc(rec.summary)}</p>`
      + `<div class="rec-cols">${list(rec.strengths, "pos", "Strengths")}${list(rec.concerns, "neg", "Concerns")}</div>${list(rec.interview_focus, "focus", "Interview focus")}</div></section>`
      + `<section class="d-section"><h3>Score breakdown<span class="meta">weights from the JD</span></h3><div class="dims">${DIMENSIONS.map((d) => `<div class="dim"><div class="dim-label">${d.label}<span class="w">×${c.weights[d.key]}%</span></div><div class="dim-val">${s[d.key]}</div><div class="dim-bar"><i style="width:${s[d.key]}%"></i></div><div class="dim-ev">${esc(c.evidence[d.key])}</div></div>`).join("")}</div></section>`
      + `<section class="d-section"><h3>Contact & profile</h3><div class="contact-grid">${contacts.map(([ic, raw, html, copy]) => `<div class="contact">${icon(ic)}<span class="v ${raw ? "" : "missing"}">${html}</span>${copy ? `<button type="button" class="icon-btn" data-action="copy" data-value="${esc(raw)}" data-label="${copy}" aria-label="Copy ${copy.toLowerCase()}" data-tip="Copy">${icon("copy")}</button>` : ""}</div>`).join("")}</div></section>`;
  }

  function drawerSkills(c) {
    const sk = c.skills;
    const p = c.profile;
    const tierChips = (tier, missing, missCls) => {
      const matched = sk.matched_detail[tier] || [];
      const chips = matched.map((m) => `<span class="chip match ${m.demonstrated ? "" : "listed"}" data-tip="${esc(m.demonstrated ? `Shown in work history (${m.skill})` : `Listed in skills only (${m.skill})`)}">${icon("check", "sm")}${esc(m.requirement)}</span>`).join("")
        + missing.map((m) => `<span class="chip ${missCls}">${icon("x", "sm")}${esc(m)}</span>`).join("");
      return chips || `<span class="muted">None in this JD</span>`;
    };
    const counts = sk.counts;
    const edu = p.education || [];
    return `<section class="d-section"><h3>Critical requirements<span class="meta"><span class="mono">${counts.critical.matched}/${counts.critical.total}</span> · <span class="mono">${sk.critical_coverage}%</span> coverage · dashed = listed, not shown in work</span></h3><div class="chips">${tierChips("critical", sk.missing_critical, "miss")}</div></section>`
      + `<section class="d-section"><h3>Core requirements<span class="meta mono">${counts.core.matched}/${counts.core.total}</span></h3><div class="chips">${tierChips("core", sk.missing_core, "gap")}</div></section>`
      + `<section class="d-section"><h3>Nice to have<span class="meta mono">${counts.bonus.matched}/${counts.bonus.total}</span></h3><div class="chips">${(sk.matched_detail.bonus || []).map((m) => `<span class="chip bonus">${esc(m.requirement)}</span>`).join("") || `<span class="muted">None matched</span>`}</div></section>`
      + `<section class="d-section"><h3>Other skills on the resume</h3><div class="chips">${sk.additional.map((x) => `<span class="chip">${esc(x)}</span>`).join("") || `<span class="muted">None beyond the JD</span>`}</div></section>`
      + `<section class="d-section"><h3>Experience<span class="meta">${fmtYears(p.total_experience_years)} ${esc(p.experience_source)}${p.timeline_years && p.experience_source === "stated" ? ` · ${fmtYears(p.timeline_years)} from dates` : ""}</span></h3>`
      + (p.timeline?.length ? `<div class="timeline">${p.timeline.map((r) => `<div class="tl-row"><span class="dot"></span><div><div class="tl-title">${esc(r.title)}</div><div class="tl-sub">${esc(r.company || "")}</div></div><span class="tl-when">${esc(r.start)} – ${esc(r.end)}</span></div>`).join("")}</div>` : `<span class="muted">No dated roles found</span>`)
      + `</section>`
      + `<section class="d-section"><h3>Education</h3>${edu.length ? `<dl class="facts">${edu.map((e) => `<dt>${esc(e.level)}</dt><dd>${esc(e.degree)}${e.field ? ` in ${esc(e.field)}` : ""}${e.institution ? ` · ${esc(e.institution)}` : ""}${e.graduation_year ? ` · <span class="mono">${e.graduation_year}</span>` : ""}${e.gpa ? ` · GPA <span class="mono">${esc(e.gpa)}</span>` : ""}${e.honors ? ` · ${esc(e.honors)}` : ""}</dd>`).join("")}</dl>` : `<span class="muted">No degree found</span>`}</section>`;
  }

  function drawerIntegrity(c) {
    const d = c.dedup;
    const m = c.metrics;
    const f = c.file;
    const statusBadge = d.status === "duplicate" ? `<span class="badge dup">Duplicate</span>` : d.status === "review" ? `<span class="badge warn">Possible duplicate</span>` : `<span class="badge ok">Unique</span>`;
    const layer = (l, i) => {
      const st = l.status === "match" ? `<span class="badge dup plain">Match</span>` : l.status === "review" ? `<span class="badge warn plain">Review</span>` : l.status === "skipped" ? `<span class="badge neutral plain">Skipped</span>` : `<span class="badge neutral plain">Clear</span>`;
      const value = l.key === "semantic"
        ? `<span class="mono">${(l.score * 100).toFixed(1)}%</span><span class="muted">similarity · match at ${(l.threshold * 100).toFixed(0)}%</span>`
        : l.hash ? `<span class="hash">${esc(l.key === "contact" ? `${l.hash.slice(0, 24)}…` : l.hash)}</span>` : "";
      return `<div class="layer ${l.status === "match" ? "is-match" : l.status === "review" ? "is-review" : ""}"><div class="layer-name"><span class="n">L${i + 1}</span>${esc(l.label)}</div>${st}`
        + `<div class="layer-method">${esc(l.method)}</div><div class="layer-detail"><span>${esc(l.detail)}</span>${value}</div>`
        + `${l.matched ? `<div class="layer-detail">Closest record: <button type="button" class="link-btn" data-action="open-candidate" data-id="${l.matched.candidate_id}">${esc(l.matched.name)}</button><span class="muted">${esc(l.matched.filename || "")}</span></div>` : ""}</div>`;
    };
    return `<section class="d-section"><h3>Three-layer deduplication<span class="meta">${statusBadge}</span></h3><div class="muted" style="font-size:12.5px">Checked against <span class="mono">${d.pool_size}</span> profile${d.pool_size === 1 ? "" : "s"} already in the ${esc(c.workspace)} talent pool.</div>${d.layers.map(layer).join("")}</section>`
      + `<section class="d-section"><h3>Processing</h3><div class="metrics-strip"><div><span>Parse</span><strong>${fmtMs(m.parse_ms)}</strong></div><div><span>Dedup</span><strong>${fmtMs(m.dedup_ms)}</strong></div><div><span>Score</span><strong>${fmtMs(m.score_ms)}</strong></div><div><span>Total</span><strong>${fmtMs(m.total_ms)}</strong></div></div></section>`
      + `<section class="d-section"><h3>Source</h3><dl class="facts">`
      + `<dt>File</dt><dd>${esc(f.name)}</dd><dt>Format</dt><dd><span class="mono">${esc(f.format)} · ${f.pages} page${f.pages === 1 ? "" : "s"} · ${fmtSize(f.size_bytes)}</span></dd>`
      + `<dt>File SHA-256</dt><dd><span class="hash">${esc(f.sha256)}</span></dd><dt>Text SHA-256</dt><dd><span class="hash">${esc(f.text_sha256)}</span></dd>`
      + `<dt>Batch</dt><dd>${esc(c.batch_label || c.batch_id)} · <span class="code">${esc(c.batch_id)}</span></dd><dt>Job description</dt><dd>${esc(c.jd.title)}</dd>`
      + `<dt>Scoring engine</dt><dd>${esc(c.engine.label)} · <span class="code">${esc(c.engine.model)}</span>${c.engine.fallback_reason ? ` · ${esc(c.engine.fallback_reason)}` : ""}</dd>`
      + `<dt>Scanned</dt><dd class="mono">${esc(new Date(c.scanned_at).toLocaleString("en-GB"))}</dd><dt>Candidate ID</dt><dd class="code">${esc(c.id)}</dd></dl></section>`;
  }

  function drawerActivity(c) {
    const notes = c.notes || [];
    const hist = c.history || [];
    return `<section class="d-section"><h3>Recruiter notes<span class="meta mono">${notes.length}</span></h3>`
      + `<div class="notes">${notes.slice().reverse().map((n) => `<div class="note"><span class="when">${esc(n.author || "Recruiter")} · ${esc(fmtDateTime(n.at))}</span><span>${esc(n.text)}</span></div>`).join("")}</div>`
      + `<form class="note-form" data-form="note" data-id="${c.id}"><textarea class="textarea" name="note" maxlength="2000" placeholder="Add a note for the hiring panel" aria-label="Note"></textarea><div class="row"><button type="submit" class="btn btn-primary">${icon("message")}Add note</button></div></form></section>`
      + `<section class="d-section"><h3>Audit trail<span class="meta mono">${hist.length}</span></h3><div class="history">${hist.map((h) => `<div class="history-row"><span class="t">${esc(fmtDateTime(h.timestamp))}</span><span><span class="evt ${/duplicate|failed|deleted/.test(h.event) ? "bad" : ""}">${esc(h.event)}</span> · ${esc(h.detail || "")}</span></div>`).join("") || `<span class="muted">No events yet</span>`}</div></section>`;
  }

  // ------------------------------------------------------------------------
  // Batch scan
  // ------------------------------------------------------------------------
  let runRenderQueued = false;
  function renderRunSoon() {
    if (runRenderQueued) return;
    runRenderQueued = true;
    requestAnimationFrame(() => { runRenderQueued = false; if (state.view === "scan") renderRun(); renderPageMeta(); });
  }

  function renderScan() {
    renderScanConfig();
    renderRun();
  }

  function renderScanConfig() {
    const el = $("#scan-config");
    const running = state.scan.run?.status === "running";
    if (state.mode === "demo") {
      const jds = state.jds.filter((j) => j.kind === "sample");
      const sel = state.scan.demoSelected || new Set();
      const all = state.samples.length && state.samples.every((s) => sel.has(s.filename));
      el.innerHTML = `<div class="card"><div class="card-head"><h2>Job description</h2><span class="meta code">sample_jd/</span></div><div class="option-list" role="radiogroup" aria-label="Job description">`
        + jds.map((j) => `<label class="option ${state.scan.demoJd === j.id ? "is-checked" : ""}"><input type="radio" name="demo-jd" value="${j.id}" data-action="pick-demo-jd" ${state.scan.demoJd === j.id ? "checked" : ""} ${running ? "disabled" : ""}>`
          + `<div><div class="option-title">${esc(j.title)}</div><div class="option-meta">${esc(j.city || "Any location")} · <span class="mono">${esc(bandText(j))}</span> · <span class="mono">${j.requirement_counts.critical}</span> critical</div></div></label>`).join("")
        + `</div></div>`
        + `<div class="card"><div class="card-head"><h2>Resumes</h2><label class="meta" style="display:flex;align-items:center;gap:8px"><input type="checkbox" data-action="toggle-all-samples" ${all ? "checked" : ""} ${running ? "disabled" : ""} aria-label="Select all sample resumes"><span class="mono">${sel.size}/${state.samples.length}</span></label></div>`
        + `<div class="file-list">${state.samples.map((s) => `<label class="file-row"><input type="checkbox" data-action="toggle-sample" value="${esc(s.filename)}" ${sel.has(s.filename) ? "checked" : ""} ${running ? "disabled" : ""}><div><div class="name">${esc(s.label)}</div><div class="path">${esc(s.filename)}</div></div><span class="size">${s.size_kb} KB</span></label>`).join("")}</div>`
        + `<div class="card-foot"><button type="button" class="btn btn-primary btn-lg btn-block" data-action="start-scan" ${running || !sel.size ? "disabled" : ""}>${running ? `<span class="spinner"></span>Scanning` : `${icon("play")}Run batch scan · ${sel.size} resume${sel.size === 1 ? "" : "s"}`}</button>`
        + `<div class="hint">${icon("cpu", "sm")}${esc(engineLabel())} · the demo workspace resets on every run</div></div></div>`;
      return;
    }
    const jd = state.jds.find((j) => j.id === state.scan.liveJd);
    const q = state.scan.queue;
    const total = q.reduce((n, f) => n + f.size, 0);
    const skipped = state.scan.skipped;
    const byType = skipped.filter((s) => s.reason === "type");
    const exts = [...new Set(byType.map((s) => (s.path.split(".").pop() || "none").toLowerCase()))].slice(0, 4).map((e) => `.${e}`).join(", ");
    const skippedText = [
      byType.length ? `${byType.length} unsupported type (${exts})` : "",
      skipped.filter((s) => s.reason === "size").length ? `${skipped.filter((s) => s.reason === "size").length} over ${maxFileMb()} MB` : "",
      skipped.filter((s) => s.reason === "empty").length ? `${skipped.filter((s) => s.reason === "empty").length} empty` : "",
    ].filter(Boolean).join(" · ");
    el.innerHTML = `<div class="card"><div class="card-head"><h2>Job description</h2><button type="button" class="btn btn-ghost" data-action="new-jd">${icon("plus")}New</button></div>`
      + `<div class="card-body" style="display:grid;gap:8px"><button type="button" class="select-btn" style="max-width:none;width:100%" data-action="menu-live-jd" aria-haspopup="menu" ${running ? "disabled" : ""}><span class="select-label">JD</span><span>${esc(jd?.title || "Choose a job description")}</span>${icon("chevron-down", "sm")}</button>`
      + (jd ? `<div class="option-meta">${esc(jd.city || "Any location")} · <span class="mono">${esc(bandText(jd))}</span> · <span class="mono">${jd.requirement_counts.critical}</span> critical · weights <span class="mono">${jd.weights.technical}/${jd.weights.experience}/${jd.weights.impact}/${jd.weights.education}</span> · ${jd.kind === "sample" ? "sample" : "custom"}</div>` : "")
      + `</div></div>`
      + `<div class="card"><div class="card-head"><h2>Resumes</h2><span class="meta mono">${q.length} queued${q.length ? ` · ${fmtSize(total)}` : ""}</span></div>`
      + `<div class="dropzone" id="dropzone">${icon("upload")}<strong>Drop a folder or resumes here</strong><p>PDF, DOCX or TXT · up to ${maxFileMb()} MB each · folders are read recursively</p>`
      + `<div class="actions"><button type="button" class="btn" data-action="pick-folder" ${running ? "disabled" : ""}>${icon("folder")}Select folder</button><button type="button" class="btn" data-action="pick-files" ${running ? "disabled" : ""}>${icon("file")}Select files</button></div></div>`
      + (skipped.length ? `<div class="skipped-note" data-tip="${esc(skipped.slice(0, 12).map((s) => s.path).join(", "))}">${skipped.length} file${skipped.length === 1 ? "" : "s"} skipped: ${esc(skippedText)}</div>` : "")
      + (q.length ? `<div class="file-list">${q.map((f, i) => `<div class="file-row">${icon("file")}<div><div class="name">${esc(f.name)}</div>${f.path !== f.name ? `<div class="path">${esc(f.path)}</div>` : ""}</div><div style="display:flex;align-items:center;gap:4px"><span class="size">${fmtSize(f.size)}</span><button type="button" class="icon-btn" data-action="remove-queued" data-i="${i}" aria-label="Remove ${esc(f.name)}">${icon("x", "sm")}</button></div></div>`).join("")}</div>` : "")
      + `<div class="card-foot"><button type="button" class="btn btn-primary btn-lg btn-block" data-action="start-scan" ${!q.length || running || !jd ? "disabled" : ""}>${running ? `<span class="spinner"></span>Processing` : q.length ? `${icon("play")}Process ${q.length} resume${q.length === 1 ? "" : "s"}` : "Add resumes to start"}</button>`
      + (q.length && !running ? `<button type="button" class="btn btn-ghost btn-block" data-action="clear-queue">Clear queue</button>` : "")
      + `<div class="hint">${icon("cpu", "sm")}${esc(engineLabel())} · results stay in the Live workspace</div></div></div>`;
  }

  function renderRun() {
    const el = $("#run-card");
    const run = state.scan.run;
    if (!run) {
      const recent = state.batches.slice(0, 5);
      el.innerHTML = `<div class="run-head"><h2>Screening pipeline</h2><span class="meta">Every resume passes four stages</span></div>`
        + `<div class="pipeline-steps">`
        + `<div><strong><span class="mono">01</span>Parse</strong><p>Contact details, profile links, dated roles, education and skills from PDF, DOCX or TXT.</p></div>`
        + `<div><strong><span class="mono">02</span>Deduplicate</strong><p>File SHA-256, then contact hash, then semantic similarity against the talent pool.</p></div>`
        + `<div><strong><span class="mono">03</span>Score</strong><p>Technical, experience, impact and education dimensions, weighted by the JD.</p></div>`
        + `<div><strong><span class="mono">04</span>Route</strong><p>Shortlisted, Technical Review, Hold, Rejected or Duplicate at the JD's thresholds.</p></div></div>`
        + (recent.length ? `<div class="recent"><div class="recent-head">Recent batches</div>${recent.map((b) => `<div class="recent-row"><div><div style="font-weight:500">${esc(b.label)} · ${esc(b.jd_title)}</div><div class="mono">${b.processed} scored · ${b.duplicates} duplicates · ${b.failed} failed · ${esc(fmtDateTime(b.created_at))}</div></div><span class="badge ${b.status === "completed" ? "ok" : "neutral"} plain">${esc(b.status)}</span><button type="button" class="btn" data-action="view-batch" data-id="${b.id}">Review</button></div>`).join("")}</div>`
          : `<div class="empty"><h3>No batches yet</h3><p>${state.mode === "demo" ? "Pick a job description and the sample resumes, then run the scan." : "Choose a job description, add a folder of resumes, then process them."}</p></div>`);
      return;
    }
    const n = run.items.length;
    const finished = run.done + run.failed;
    const pct = n ? Math.round((finished / n) * 100) : 0;
    const timings = run.items.filter((i) => i.ms != null).map((i) => i.ms).sort((a, b) => a - b);
    const median = timings.length ? timings[Math.floor(timings.length / 2)] : null;
    const running = run.status === "running";
    const statusBadge = running ? `<span class="badge st-technical_review">Running</span>` : run.failed ? `<span class="badge warn">Finished with ${run.failed} failed</span>` : `<span class="badge ok">Completed</span>`;
    const shortlisted = run.items.filter((i) => i.result?.stage === "shortlisted").length;
    el.innerHTML = `<div class="run-head"><h2>${esc(run.label)}</h2><span class="meta">${esc(run.jdTitle)} · ${esc(run.engine)}</span>${statusBadge}</div>`
      + `<div class="progress ${running ? "" : "done"}" role="progressbar" aria-valuemin="0" aria-valuemax="${n}" aria-valuenow="${finished}" aria-label="Batch progress"><i style="width:${pct}%"></i></div>`
      + `<div class="run-stats"><div class="run-stat"><div class="label">Processed</div><div class="value">${finished}/${n}</div></div>`
      + `<div class="run-stat"><div class="label">Shortlisted</div><div class="value">${shortlisted}</div></div>`
      + `<div class="run-stat"><div class="label">Duplicates</div><div class="value">${run.dups}</div></div>`
      + `<div class="run-stat"><div class="label">Elapsed</div><div class="value">${fmtMs(run.elapsed)}</div></div>`
      + `<div class="run-stat"><div class="label">Median / resume</div><div class="value">${fmtMs(median)}</div></div></div>`
      + (!running ? `<div class="run-done">${icon("check")}<span><strong>${run.done} scored</strong> · ${shortlisted} shortlisted · ${run.dups} duplicate${run.dups === 1 ? "" : "s"} blocked${run.failed ? ` · ${run.failed} failed` : ""}</span><button type="button" class="btn btn-primary" data-action="view-batch" data-id="${run.id}">Review candidates${icon("chevron-right")}</button></div>` : "")
      + `<div class="run-files"><div class="run-row" style="height:32px;font-size:12px;color:var(--muted)"><span>File</span>`
      + (running ? `<span class="steps-cell steps-legend"><span>Parse</span><span>Dedup</span><span>Score</span><span>Route</span></span>` : `<span class="steps-cell">Parse · dedup · score</span>`)
      + `<span>Result</span><span style="text-align:right">Total</span></div>`
      + run.items.map((it) => runRow(it, running)).join("") + `</div>`
      + `<details class="event-log" id="event-log" ${state.scan.logOpen ? "open" : ""}><summary>${icon("chevron-right")}Event stream<span class="meta">${run.events.length} events · server-sent</span></summary><div class="log-lines" id="log-lines">${run.events.slice(-200).map(logLine).join("")}</div></details>`;
    const log = $("#log-lines");
    if (log) log.scrollTop = log.scrollHeight;
  }

  function runRow(it, running) {
    let stepsHtml;
    if (!running && it.status === "done" && it.metrics) {
      const m = it.metrics;
      stepsHtml = `<span class="stage-ms" data-tip="Parse ${fmtMs(m.parse_ms)} · Dedup ${fmtMs(m.dedup_ms)} · Score ${fmtMs(m.score_ms)}">${Math.round(m.parse_ms)} · ${Math.round(m.dedup_ms)} · ${Math.round(m.score_ms)} ms</span>`;
    }
    const steps = [0, 1, 2, 3].map((i) => {
      if (it.status === "done") return `<i class="done"></i>`;
      if (it.status === "failed") return `<i class="${i < it.step ? "done" : i === Math.max(it.step, 0) ? "fail" : ""}"></i>`;
      if (it.status === "processing") return `<i class="${i < it.step ? "done" : i === it.step ? "active" : ""}"></i>`;
      return `<i></i>`;
    }).join("");
    let result = `<span class="muted">Queued</span>`;
    if (it.status === "processing") result = `<span class="muted">${["Parsing", "Deduplicating", "Scoring", "Routing"][clamp(it.step, 0, 3)]}</span>`;
    if (it.status === "done") result = `<span class="fit-num">${it.result.scores.overall}</span>${badge(it.result.stage)}`;
    if (it.status === "failed") {
      result = `<span class="err">${esc(it.error)}</span>${it.file ? `<button type="button" class="btn" style="height:26px" data-action="retry-item" data-key="${esc(it.key)}">Retry</button>` : ""}`;
    }
    const clickable = it.status === "done" ? `data-action="open-candidate" data-id="${it.result.id}" style="cursor:pointer" tabindex="0"` : "";
    return `<div class="run-row ${it.status === "failed" ? "is-failed" : ""}" ${clickable}><span class="name" title="${esc(it.path || it.name)}">${esc(it.label || it.name)}</span><span class="steps-cell">${stepsHtml || `<span class="steps">${steps}</span>`}</span><span class="result">${result}</span><span class="ms">${it.ms != null ? fmtMs(it.ms) : ""}</span></div>`;
  }

  function logLine(e) {
    let detail = "";
    if (e.type === "batch.started") detail = `${e.label} · ${e.expected} files · ${e.jd}`;
    if (e.type === "file.started") detail = e.file;
    if (e.type === "file.parsed") detail = `${e.file} → ${e.name} · ${e.skills} skills · ${e.ms} ms`;
    if (e.type === "file.deduped") detail = `${e.file} → ${e.status}${e.layer ? ` via ${e.layer}` : ""}${e.duplicate_of ? ` of ${e.duplicate_of}` : ""} · ${e.ms} ms`;
    if (e.type === "file.scored") detail = `${e.name} → ${e.overall} · ${STAGES[e.stage]?.label} · ${e.ms} ms`;
    if (e.type === "file.failed") detail = `${e.file} → ${e.message}`;
    if (e.type === "batch.completed") detail = `${e.summary.processed} scored · ${e.summary.duplicates} duplicates · ${e.summary.failed} failed`;
    // Failures are errors (burnt sienna); duplicate verdicts keep the duplicate colour (mulberry).
    const tone = e.type === "file.failed" ? "bad" : e.type === "file.deduped" && e.status === "duplicate" ? "dup" : "";
    return `<div><span class="t">${esc(fmtClock(e.at))}</span><span class="k ${tone}">${esc(e.type)}</span>${esc(detail)}</div>`;
  }

  const STEP_OF = { "file.started": 0, "file.parsed": 1, "file.deduped": 2, "file.scored": 4 };

  function openStream(run) {
    if (!window.EventSource) return;
    const es = new EventSource(`/api/batches/${run.id}/events`);
    run.es = es;
    ["batch.started", "file.started", "file.parsed", "file.deduped", "file.scored", "file.failed", "batch.completed"].forEach((type) => {
      es.addEventListener(type, (ev) => {
        let data;
        try { data = JSON.parse(ev.data); } catch { return; }
        if (run.events.some((x) => x.seq === data.seq)) return;
        run.events.push(data);
        if (type in STEP_OF) {
          const it = run.items.find((i) => i.serverName === data.file && i.status === "processing");
          if (it) it.step = Math.max(it.step, STEP_OF[type]);
        }
        if (type === "batch.completed") { es.close(); run.es = null; }
        renderRunSoon();
      });
    });
    es.onerror = () => { if (run.status !== "running") { es.close(); run.es = null; } };
  }

  async function startScan() {
    if (state.scan.run?.status === "running") return;
    const demo = state.mode === "demo";
    const jdId = demo ? state.scan.demoJd : state.scan.liveJd;
    const jd = state.jds.find((j) => j.id === jdId);
    if (!jd) { toast("Choose a job description first.", "err"); return; }
    let items;
    if (demo) {
      items = state.samples.filter((s) => state.scan.demoSelected.has(s.filename))
        .map((s) => ({ key: s.filename, name: s.filename, label: s.filename, status: "queued", step: -1 }));
    } else {
      items = state.scan.queue.map((f) => ({ key: f.path, name: f.name, path: f.path, file: f.file, status: "queued", step: -1 }))
        .sort((a, b) => a.path.localeCompare(b.path, undefined, { numeric: true, sensitivity: "base" }));
    }
    if (!items.length) { toast(demo ? "Select at least one sample resume." : "Add resumes to the queue first.", "err"); return; }
    items.forEach((it) => { it.serverName = safeName(it.path || it.name); });
    let batch;
    try {
      batch = await api("/api/batches", { method: "POST", json: { workspace: ws(), jd_id: jdId, expected: items.length } });
    } catch (e) { toast(e.message, "err"); return; }
    const run = {
      id: batch.id, label: batch.label, jdTitle: batch.jd_title, workspace: batch.workspace,
      engine: batch.provider === "deterministic" ? "Deterministic engine" : `Hybrid · ${batch.provider}`,
      items, events: [], status: "running", started: performance.now(), elapsed: 0, done: 0, failed: 0, dups: 0,
    };
    state.scan.run = run;
    if (!demo) { state.scan.queue = []; state.scan.skipped = []; }
    if (demo) { state.filters.batch = "all"; state.rows = []; state.analytics = null; state.loaded = false; closeDrawer(); }
    $("#nav-live").hidden = false;
    openStream(run);
    renderScan();
    renderPageMeta();
    run.timer = setInterval(() => { run.elapsed = performance.now() - run.started; renderRunSoon(); }, 100);
    let cursor = 0;
    const worker = async () => {
      while (cursor < items.length) {
        const it = items[cursor++];
        await processItem(run, it);
      }
    };
    // Demo runs in file order so the planted duplicates follow their originals; Live uploads three at a time.
    await Promise.all(Array.from({ length: Math.min(demo ? 1 : 3, items.length) }, worker));
    await finishRun(run);
  }

  async function processItem(run, it) {
    it.status = "processing";
    it.step = 0;
    it.error = null;
    renderRunSoon();
    try {
      let res;
      if (run.workspace === "demo") {
        res = await api(`/api/batches/${run.id}/samples`, { method: "POST", json: { filename: it.name } });
      } else {
        const fd = new FormData();
        fd.append("file", it.file, it.name);
        fd.append("relative_path", it.path);
        res = await api(`/api/batches/${run.id}/files`, { method: "POST", form: fd });
      }
      it.status = "done";
      it.step = 4;
      it.result = res.candidate;
      it.ms = res.metrics.total_ms;
      it.metrics = res.metrics;
      run.done += 1;
      if (res.candidate.stage === "duplicate") run.dups += 1;
    } catch (e) {
      it.status = "failed";
      it.error = e.message;
      run.failed += 1;
    }
    renderRunSoon();
  }

  async function finishRun(run) {
    clearInterval(run.timer);
    run.elapsed = performance.now() - run.started;
    try { await api(`/api/batches/${run.id}/complete`, { method: "POST" }); } catch { /* batch auto-completes server-side */ }
    run.status = "finished";
    $("#nav-live").hidden = true;
    setTimeout(() => { if (run.es) { run.es.close(); run.es = null; } }, 3000);
    state.filters.batch = run.id;
    state.filters.stage = "all";
    await loadWorkspace();
    renderScan();
    renderPageMeta();
    toast(`${run.label} finished · ${run.done} scored · ${run.dups} duplicate${run.dups === 1 ? "" : "s"}${run.failed ? ` · ${run.failed} failed` : ""}`, run.failed ? "err" : "ok", { label: "Review", run: () => navigate("pipeline") });
  }

  async function retryItem(key) {
    const run = state.scan.run;
    const it = run?.items.find((i) => i.key === key);
    if (!it || it.status !== "failed") return;
    run.failed -= 1;
    await processItem(run, it);
    await loadWorkspace();
    renderScan();
  }

  async function runDemoNow() {
    if (state.mode !== "demo") return;
    state.scan.demoJd = state.jds.some((j) => j.id === "sample-backend_engineer") ? "sample-backend_engineer" : state.scan.demoJd;
    state.scan.demoSelected = new Set(state.samples.map((s) => s.filename));
    navigate("scan");
    await startScan();
  }

  function addFiles(list) {
    let added = 0;
    for (const { file, path } of list) {
      if (file.name.startsWith(".") || file.name.startsWith("~$")) continue;
      if (!ACCEPTED.test(file.name)) { state.scan.skipped.push({ path, reason: "type" }); continue; }
      if (file.size === 0) { state.scan.skipped.push({ path, reason: "empty" }); continue; }
      if (file.size > maxFileMb() * 1048576) { state.scan.skipped.push({ path, reason: "size" }); continue; }
      if (state.scan.queue.some((q) => q.path === path && q.size === file.size)) continue;
      if (state.scan.queue.length >= 500) { toast("A batch holds up to 500 resumes. Process this one, then add the rest.", "err"); break; }
      state.scan.queue.push({ file, name: file.name, path, size: file.size });
      added += 1;
    }
    renderScanConfig();
    if (added) toast(`${added} resume${added === 1 ? "" : "s"} added to the queue`);
    else if (list.length) toast("No new PDF, DOCX or TXT files found.", "err");
  }

  function readEntry(entry, prefix = "") {
    return new Promise((resolve) => {
      if (entry.isFile) {
        entry.file((f) => resolve([{ file: f, path: prefix + f.name }]), () => resolve([]));
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        const children = [];
        const readBatch = () => reader.readEntries(async (ents) => {
          if (!ents.length) {
            const nested = await Promise.all(children.map((c) => readEntry(c, `${prefix}${entry.name}/`)));
            resolve(nested.flat());
          } else { children.push(...ents); readBatch(); }
        }, () => resolve([]));
        readBatch();
      } else resolve([]);
    });
  }

  // ------------------------------------------------------------------------
  // Job descriptions
  // ------------------------------------------------------------------------
  async function loadJobsView() {
    renderJobsList();
    const id = state.jobs.selectedId && (state.jds.some((j) => j.id === state.jobs.selectedId) || state.jobs.selectedId === "new")
      ? state.jobs.selectedId : state.jds[0]?.id;
    if (id === "new") { renderJobsEditor(); return; }
    if (id && (!state.jobs.draft || state.jobs.draft.id !== id)) await selectJd(id);
    else renderJobsEditor();
  }

  function renderJobsList() {
    const el = $("#jobs-list");
    el.innerHTML = `<div class="card-head"><h2>Job descriptions</h2><button type="button" class="btn btn-primary" data-action="new-jd">${icon("plus")}New</button></div>`
      + `<div class="option-list scroll">${state.jds.map((j) => `<button type="button" class="option ${state.jobs.selectedId === j.id ? "is-checked" : ""}" data-action="select-jd" data-id="${j.id}">`
        + `<div><div class="option-title">${esc(j.title)}</div><div class="option-meta">${esc(j.city || "Any location")} · <span class="mono">${esc(bandText(j))}</span> · <span class="mono">${j.requirement_counts.critical}</span> critical</div></div>`
        + `<span class="job-kind">${j.kind === "sample" ? "SAMPLE" : "CUSTOM"}</span></button>`).join("")}</div>`
      + (state.mode === "demo" ? `<div class="card-foot"><div class="hint">${icon("briefcase", "sm")}Custom job descriptions live in the Live workspace</div></div>` : "");
  }

  async function selectJd(id) {
    state.jobs.selectedId = id;
    renderJobsList();
    $("#jobs-editor").innerHTML = `<div class="drawer-loading"><span class="sk" style="width:40%;height:16px"></span><span class="sk" style="width:100%;height:34px"></span><span class="sk" style="width:100%;height:220px;border-radius:10px"></span></div>`;
    try {
      const jd = await api(`/api/jds/${id}`);
      state.jobs.draft = {
        id: jd.id, kind: jd.kind, filename: jd.filename, title: jd.title, location: jd.location || "", text: jd.text,
        experience_min: jd.experience_min, experience_max: jd.experience_max,
        requirements: { critical: [...jd.requirements.critical], core: [...jd.requirements.core], bonus: [...jd.requirements.bonus] },
        weights: { ...jd.weights }, thresholds: { ...jd.thresholds }, reqEdited: false, updated_at: jd.updated_at, created_at: jd.created_at,
      };
      renderJobsEditor();
    } catch (e) {
      $("#jobs-editor").innerHTML = `<div class="empty">${icon("alert")}<h3>Couldn't load this job description</h3><p>${esc(e.message)}</p></div>`;
    }
  }

  function newDraft(from) {
    state.jobs.selectedId = "new";
    state.jobs.draft = {
      id: null, kind: "custom", filename: from?.filename || null, title: from ? `${from.title} (copy)` : "", location: from?.location || "", text: from?.text || "",
      experience_min: from?.experience_min ?? null, experience_max: from?.experience_max ?? null,
      requirements: from ? JSON.parse(JSON.stringify(from.requirements)) : { critical: [], core: [], bonus: [] },
      weights: from ? { ...from.weights } : { ...DEFAULT_WEIGHTS }, thresholds: from ? { ...from.thresholds } : { ...DEFAULT_TH }, reqEdited: !!from,
    };
    renderJobsList();
    renderJobsEditor();
    $("#jd-title")?.focus();
  }

  function normalizedWeights(w) {
    const total = Object.values(w).reduce((a, b) => a + Number(b || 0), 0) || 1;
    const out = {};
    Object.keys(DEFAULT_WEIGHTS).forEach((k) => { out[k] = Math.round((Number(w[k] || 0) * 100) / total); });
    return out;
  }

  function renderJobsEditor() {
    const el = $("#jobs-editor");
    const d = state.jobs.draft;
    if (!d) { el.innerHTML = `<div class="empty">${icon("briefcase")}<h3>No job description selected</h3><p>Pick one from the list or create a new one.</p></div>`; return; }
    const ro = d.kind === "sample" || state.mode === "demo";
    const dis = ro ? "disabled" : "";
    el.innerHTML = `<div class="card-head"><h2>${esc(d.id ? d.title : "New job description")}</h2><span class="meta">${d.kind === "sample" ? `<span class="code">sample_jd/${esc(d.filename || "")}</span>` : d.updated_at ? `Updated ${esc(relTime(d.updated_at))}` : d.created_at ? `Created ${esc(relTime(d.created_at))}` : "Not saved yet"}</span></div>`
      + `<div class="editor-body">`
      + (ro ? `<div class="readonly-note">${icon("file")}${d.kind === "sample" ? "Sample job descriptions are read-only. Duplicate it to change requirements, weights or thresholds." : "Switch to the Live workspace to edit job descriptions."}</div>` : "")
      + `<div class="field-row"><label class="field"><span>Role title</span><input class="input" id="jd-title" data-jd="title" value="${esc(d.title)}" maxlength="120" placeholder="e.g. Senior Backend Engineer" ${dis}></label>`
      + `<label class="field"><span>Location</span><input class="input" data-jd="location" value="${esc(d.location)}" maxlength="120" placeholder="e.g. Hyderabad (Hybrid)" ${dis}></label></div>`
      + `<div class="field-row"><label class="field"><span>Minimum experience (yrs)</span><input class="input mono" type="number" min="0" max="40" step="0.5" data-jd="experience_min" value="${d.experience_min ?? ""}" placeholder="Any" ${dis}></label>`
      + `<label class="field"><span>Maximum experience (yrs)</span><input class="input mono" type="number" min="0" max="45" step="0.5" data-jd="experience_max" value="${d.experience_max ?? ""}" placeholder="No cap" ${dis}></label></div>`
      + `<div class="field"><span>Job description text</span><textarea class="textarea" id="jd-text" data-jd="text" maxlength="40000" placeholder="Paste the full JD. Requirements, nice-to-haves and the experience band are extracted as you type." ${dis}>${esc(d.text)}</textarea>`
      + (ro ? "" : `<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><button type="button" class="btn" data-action="pick-jd-file">${icon("upload")}Upload JD file</button><button type="button" class="btn btn-ghost" data-action="reextract-jd">${icon("refresh")}Re-extract requirements</button><span class="muted" style="font-size:12px" id="jd-analyzing">${state.jobs.analyzing ? "Extracting…" : ""}</span></div>`)
      + `</div>`
      + `<div class="editor-section" id="req-section">${reqSection(d, ro)}</div>`
      + `<div class="editor-section" id="weights-section">${weightsSection(d, ro)}</div>`
      + `<div class="editor-section" id="threshold-section">${thresholdSection(d, ro)}</div>`
      + `</div><div class="editor-foot">`
      + (ro
        ? `<button type="button" class="btn btn-primary" data-action="duplicate-jd">${icon("copy")}Duplicate to edit</button><button type="button" class="btn" data-action="use-jd">${icon("play")}Scan with this JD</button>`
        : `<button type="button" class="btn btn-primary" data-action="save-jd" ${state.jobs.saving ? "disabled" : ""}>${state.jobs.saving ? `<span class="spinner"></span>` : icon("check")}${d.id ? "Save changes" : "Create job description"}</button>`
          + (d.id ? `<button type="button" class="btn" data-action="use-jd">${icon("play")}Scan with this JD</button>` : "")
          + `<span class="spacer"></span>` + (d.id ? `<button type="button" class="btn btn-danger" data-action="delete-jd">${icon("trash")}Delete</button>` : ""))
      + `</div>`;
  }

  function reqSection(d, ro) {
    const tiers = [["critical", "Critical", "70% of the technical score", "miss"], ["core", "Core", "20%", "gap"], ["bonus", "Nice to have", "10%", "bonus"]];
    return `<h3>Requirements<span class="meta">${d.reqEdited ? "edited by you" : "extracted from the text"} · "A / B" means either satisfies it</span></h3>`
      + tiers.map(([k, label, share]) => `<div class="req-tier"><div class="req-tier-head"><strong>${label}</strong><span>${share}</span><span class="mono">${d.requirements[k].length}</span></div><div class="chips">`
        + d.requirements[k].map((r, i) => `<span class="chip">${esc(r)}${ro ? "" : `<button type="button" data-action="remove-req" data-tier="${k}" data-i="${i}" aria-label="Remove ${esc(r)}">${icon("x")}</button>`}</span>`).join("")
        + (ro ? (d.requirements[k].length ? "" : `<span class="muted" style="font-size:12px">None</span>`) : `<input class="chip-input" data-req-add="${k}" placeholder="Add skill, Enter" aria-label="Add ${label.toLowerCase()} requirement">`)
        + `</div></div>`).join("");
  }

  function weightsSection(d, ro) {
    const n = normalizedWeights(d.weights);
    const colors = { technical: "var(--accent)", experience: "color-mix(in srgb, var(--accent) 65%, var(--card))", impact: "color-mix(in srgb, var(--accent) 40%, var(--card))", education: "color-mix(in srgb, var(--accent) 20%, var(--card))" };
    return `<h3>Scoring weights<span class="meta">normalized to 100</span></h3><div class="weight-stack" aria-hidden="true">${DIMENSIONS.map((dm) => `<span style="flex-grow:${Math.max(n[dm.key], 0.01)};background:${colors[dm.key]}"></span>`).join("")}</div>`
      + `<div class="weights">${DIMENSIONS.map((dm) => `<label class="weight-row"><span>${dm.label}</span><input type="range" min="0" max="100" step="5" value="${d.weights[dm.key]}" data-weight="${dm.key}" ${ro ? "disabled" : ""} aria-label="${dm.label} weight"><span class="mono">${n[dm.key]}%</span></label>`).join("")}</div>`;
  }

  function thresholdSection(d, ro) {
    const t = d.thresholds;
    return `<h3>Routing thresholds<span class="meta">overall fit needed for each stage</span></h3>`
      + `<div class="threshold-inputs">${[["shortlist", "Shortlisted from"], ["review", "Technical review from"], ["hold", "Hold from"]].map(([k, l]) => `<label class="field"><span>${l}</span><input class="input mono" type="number" min="1" max="100" data-threshold="${k}" value="${t[k]}" ${ro ? "disabled" : ""}></label>`).join("")}</div>`
      + `<div id="threshold-preview">${rulerLarge(null, t)}</div>`;
  }

  const analyzeJd = debounce(async () => {
    const d = state.jobs.draft;
    if (!d || d.text.trim().length < 20) return;
    state.jobs.analyzing = true;
    const flag = $("#jd-analyzing");
    if (flag) flag.textContent = "Extracting…";
    try {
      const prof = await api("/api/jds/analyze", { method: "POST", json: { text: d.text, title: d.title || null } });
      if (state.jobs.draft !== d) return;
      if (!d.reqEdited) d.requirements = prof.requirements;
      if (d.experience_min == null && prof.experience_min != null) d.experience_min = prof.experience_min;
      if (d.experience_max == null && prof.experience_max != null) d.experience_max = prof.experience_max;
      if (!d.location && prof.location) d.location = prof.location;
      $("#req-section").innerHTML = reqSection(d, false);
      $$("[data-jd='experience_min']").forEach((i) => { if (document.activeElement !== i) i.value = d.experience_min ?? ""; });
      $$("[data-jd='experience_max']").forEach((i) => { if (document.activeElement !== i) i.value = d.experience_max ?? ""; });
    } catch (e) {
      toast(e.message, "err");
    } finally {
      state.jobs.analyzing = false;
      const f2 = $("#jd-analyzing");
      if (f2) f2.textContent = "";
    }
  }, 500);

  async function saveJd() {
    const d = state.jobs.draft;
    if (!d) return;
    if ((d.title || "").trim().length < 2) { toast("Give the role a title.", "err"); $("#jd-title")?.focus(); return; }
    if ((d.text || "").trim().length < 40) { toast("Paste the job description text (at least 40 characters).", "err"); $("#jd-text")?.focus(); return; }
    const payload = {
      title: d.title.trim(), text: d.text, location: d.location || null,
      experience_min: d.experience_min === "" ? null : d.experience_min, experience_max: d.experience_max === "" ? null : d.experience_max,
      weights: d.weights, thresholds: d.thresholds, requirements: d.reqEdited ? d.requirements : null, filename: d.filename,
    };
    state.jobs.saving = true;
    renderJobsEditor();
    try {
      const saved = await api(d.id ? `/api/jds/${d.id}` : "/api/jds", { method: d.id ? "PUT" : "POST", json: payload });
      toast(d.id ? "Saved. New scans use these settings." : "Job description created");
      state.jobs.saving = false;
      const jds = await api(`/api/jds${qs({ workspace: ws() })}`);
      state.jds = jds.jds;
      state.jobs.draft = null;
      await selectJd(saved.id);
    } catch (e) {
      state.jobs.saving = false;
      renderJobsEditor();
      toast(e.message, "err");
    }
  }

  async function deleteJd() {
    const d = state.jobs.draft;
    if (!d?.id) return;
    const ok = await confirmDialog({ title: `Delete “${d.title}”?`, body: "Candidates already scored against it keep their scores. New batches can no longer use it.", confirm: "Delete" });
    if (!ok) return;
    try {
      await api(`/api/jds/${d.id}`, { method: "DELETE" });
      toast("Job description deleted");
      const jds = await api(`/api/jds${qs({ workspace: ws() })}`);
      state.jds = jds.jds;
      state.jobs.selectedId = null;
      state.jobs.draft = null;
      ensureScanDefaults();
      loadJobsView();
    } catch (e) { toast(e.message, "err"); }
  }

  async function uploadJdFile(file) {
    const fd = new FormData();
    fd.append("file", file, file.name);
    try {
      const res = await api("/api/jds/extract", { method: "POST", form: fd });
      const d = state.jobs.draft;
      d.text = res.text;
      d.filename = res.filename;
      if (!d.title) d.title = res.profile.title;
      if (!d.location && res.profile.location) d.location = res.profile.location;
      if (res.profile.experience_min != null) d.experience_min = res.profile.experience_min;
      if (res.profile.experience_max != null) d.experience_max = res.profile.experience_max;
      d.requirements = res.profile.requirements;
      d.reqEdited = false;
      renderJobsEditor();
      toast(`Read ${res.filename}`);
    } catch (e) { toast(e.message, "err"); }
  }

  // ------------------------------------------------------------------------
  // Audit log
  // ------------------------------------------------------------------------
  const AUDIT_FILTERS = [
    ["", "All events"], ["candidate.scored", "Scored"], ["candidate.duplicate_flagged", "Duplicates flagged"],
    ["candidate.stage_changed", "Stage changes"], ["candidate.note_added", "Notes"], ["candidate.deleted", "Deletions"],
    ["batch", "Batches"], ["file.failed", "Failed files"], ["export", "Exports"], ["jd", "Job descriptions"],
    ["sheets", "Sheets sync"], ["workspace", "Workspace resets"], ["settings", "Settings"],
  ];

  async function loadAudit(reset) {
    const a = state.audit;
    if (reset) { a.entries = []; a.total = 0; }
    a.loading = true;
    renderAudit();
    try {
      const res = await api(`/api/audit${qs({ workspace: ws(), event: a.filter, limit: 50, offset: a.entries.length })}`);
      a.entries = reset ? res.entries : a.entries.concat(res.entries);
      a.total = res.total;
      a.error = null;
    } catch (e) { a.error = e.message; }
    a.loading = false;
    renderAudit();
    renderPageMeta();
  }

  function renderAudit() {
    const a = state.audit;
    $("#audit-filter-label").textContent = AUDIT_FILTERS.find(([k]) => k === a.filter)[1];
    $("#audit-meta").textContent = `${state.mode} workspace · ${fmtInt(a.total)} events`;
    const body = $("#audit-body");
    if (a.error && !a.entries.length) {
      body.innerHTML = `<tr><td colspan="6"><div class="empty">${icon("alert")}<h3>Couldn't load the audit log</h3><p>${esc(a.error)}</p></div></td></tr>`;
    } else if (!a.entries.length) {
      body.innerHTML = a.loading
        ? Array.from({ length: 5 }, () => `<tr><td><span class="sk" style="width:90px"></span></td><td><span class="sk" style="width:120px"></span></td><td><span class="sk" style="width:100px"></span></td><td class="hide-sm"><span class="sk"></span></td><td class="hide-sm"></td><td class="hide-md"></td></tr>`).join("")
        : `<tr><td colspan="6"><div class="empty">${icon("list")}<h3>No events yet</h3><p>Scans, stage changes, notes, exports and syncs are recorded here and in keka_sheets_audit_log.csv / .json.</p></div></td></tr>`;
    } else {
      body.innerHTML = a.entries.map((e) => {
        const cls = /duplicate/.test(e.event) ? "dup" : /failed|deleted|reset/.test(e.event) ? "bad" : e.event === "candidate.scored" ? "good" : "";
        const who = e.candidate_id && e.event !== "candidate.deleted"
          ? `<button type="button" class="link-btn" data-action="open-candidate" data-id="${e.candidate_id}">${esc(e.candidate_name || e.candidate_id)}</button>`
          : esc(e.candidate_name || "—");
        return `<tr><td>${esc(fmtDateTime(e.timestamp))}</td><td><span class="evt ${cls}">${esc(e.event)}</span></td><td>${who}</td><td class="hide-sm"><div class="detail-cell" title="${esc(e.detail || "")}">${esc(e.detail || "")}</div></td><td class="col-num hide-sm">${e.overall ?? ""}</td><td class="hide-md">${esc(e.actor)}</td></tr>`;
      }).join("");
    }
    $("#audit-foot").innerHTML = `<span><span class="mono">${fmtInt(a.entries.length)}</span> of <span class="mono">${fmtInt(a.total)}</span></span>`
      + (a.entries.length < a.total ? `<button type="button" class="btn" data-action="audit-more" ${a.loading ? "disabled" : ""}>Load 50 more</button>` : "");
  }

  // ------------------------------------------------------------------------
  // Integrations
  // ------------------------------------------------------------------------
  async function loadSettings() {
    try {
      state.settings = await api("/api/settings");
      renderRailStatus();
    } catch { /* rail keeps its last known status */ }
  }

  async function loadIntegrations() {
    const grid = $("#settings-grid");
    if (!state.integrations) grid.innerHTML = `<div class="card"><div class="drawer-loading"><span class="sk" style="width:40%"></span><span class="sk"></span><span class="sk"></span></div></div>`;
    try {
      const [s, i, h] = await Promise.all([api("/api/settings"), api("/api/integrations"), api("/api/health")]);
      state.settings = s;
      state.integrations = i;
      state.health = h;
      renderIntegrations();
      renderRailStatus();
      renderPageMeta();
    } catch (e) {
      grid.innerHTML = `<div class="card"><div class="empty">${icon("alert")}<h3>Couldn't load integrations</h3><p>${esc(e.message)}</p></div></div>`;
    }
  }

  function renderIntegrations() {
    const s = state.settings;
    const i = state.integrations;
    const h = state.health;
    const sh = i.sheets;
    const providers = ["deterministic", "groq", "openai"].map((k) => {
      const p = s.providers[k];
      const on = s.provider === k;
      return `<label class="provider ${p.available ? "" : "is-disabled"}"><input type="radio" name="provider" value="${k}" data-action="set-provider" ${on ? "checked" : ""} ${p.available ? "" : "disabled"}>`
        + `<div><div class="provider-title">${k === "deterministic" ? "Deterministic engine" : `Hybrid · ${esc(p.label)}`}</div><div class="provider-meta">${k === "deterministic" ? "Rule-based, offline, identical scores for identical input" : `Half of each dimension from <span class="code">${esc(p.model)}</span>, narrative from the model`}</div></div>`
        + `${p.available ? `<span class="badge ok plain">Ready</span>` : `<span class="badge neutral plain">Needs ${esc(p.missing)}</span>`}</label>`;
    }).join("");
    $("#settings-grid").innerHTML = `<div class="card"><div class="card-head"><h2>Scoring engine</h2><span class="meta">Applies to new batches</span></div>${providers}</div>`
      + `<div class="card"><div class="card-head"><h2>Google Sheets</h2>${sh.configured ? `<span class="badge ok">Connected</span>` : `<span class="badge neutral">Not connected</span>`}</div>`
      + `<dl class="kv"><dt>Spreadsheet</dt><dd>${sh.sheet_id ? `<span class="code">${esc(sh.sheet_id)}</span>` : `<span class="muted">GOOGLE_SHEET_ID not set</span>`}</dd>`
      + `<dt>Worksheet</dt><dd>ATS Candidates (full mirror on each sync)</dd><dt>Last sync</dt><dd>${sh.last_sync ? `${esc(relTime(sh.last_sync.at))} · <span class="mono">${sh.last_sync.rows}</span> rows` : "Never"}</dd>`
      + (sh.last_error ? `<dt>Last error</dt><dd style="color:var(--st-dup)">${esc(sh.last_error)}</dd>` : "")
      + (sh.missing.length ? `<dt>Missing</dt><dd>${sh.missing.map((m) => `<span class="chip">${esc(m)}</span>`).join(" ")}</dd>` : "")
      + `</dl><div class="danger-zone"><button type="button" class="btn btn-primary" data-action="sync-sheets">${icon("sheet")}Sync ${esc(state.mode)} workspace now</button>${sh.sheet_url ? `<a class="btn" href="${esc(sh.sheet_url)}" target="_blank" rel="noopener">${icon("external")}Open sheet</a>` : ""}</div></div>`
      + `<div class="card"><div class="card-head"><h2>Environment</h2><span class="meta code">.env</span></div><div class="table-wrap"><table class="grid env-table"><thead><tr><th>Key</th><th>Status</th><th class="hide-sm">Used for</th></tr></thead><tbody>`
      + i.env.map((e) => `<tr><td>${esc(e.key)}</td><td>${e.set ? `<span class="badge ok plain">Set</span>` : `<span class="badge neutral plain">Missing</span>`}</td><td class="hide-sm">${esc(e.purpose)}</td></tr>`).join("")
      + `</tbody></table></div><div class="card-foot"><div class="hint">${icon("file", "sm")}Edit .env in the project root, share the sheet with the service account email, then restart the server.</div></div></div>`
      + `<div class="card"><div class="card-head"><h2>Data & storage</h2><span class="meta">${esc(h.storage)}</span></div><dl class="kv">`
      + `<dt>Data directory</dt><dd class="code">${esc(h.data_dir)}</dd><dt>Audit log</dt><dd class="code">${esc(i.audit_files.csv)} · ${esc(i.audit_files.json)}</dd>`
      + `<dt>Candidates</dt><dd>Demo <span class="mono">${h.candidates.demo}</span> · Live <span class="mono">${h.candidates.live}</span></dd><dt>Audit events</dt><dd class="mono">${fmtInt(h.audit_events)}</dd><dt>Version</dt><dd class="mono">${esc(h.version)} · ${esc(h.environment)}</dd></dl>`
      + `<div class="danger-zone"><button type="button" class="btn btn-danger" data-action="reset-workspace" data-ws="demo">${icon("trash")}Reset demo workspace</button><button type="button" class="btn btn-danger" data-action="reset-workspace" data-ws="live">${icon("trash")}Reset live workspace</button></div></div>`;
  }

  async function resetWorkspace(target) {
    const ok = await confirmDialog({
      title: `Reset the ${target} workspace?`,
      body: target === "live"
        ? "Every Live candidate, batch, stored upload and deduplication fingerprint is deleted. Custom job descriptions and the audit log are kept. This cannot be undone."
        : "Demo candidates, batches and fingerprints are cleared. The sample files are untouched.",
      confirm: `Reset ${target}`,
    });
    if (!ok) return;
    try {
      const res = await api(`/api/workspaces/${target}/reset`, { method: "POST" });
      toast(`${target === "live" ? "Live" : "Demo"} workspace reset · ${res.removed.candidates} candidates removed`);
      if (target === state.mode) { state.filters.batch = "all"; state.scan.run = null; closeDrawer(); await loadWorkspace(); }
      loadIntegrations();
    } catch (e) { toast(e.message, "err"); }
  }

  // ------------------------------------------------------------------------
  // Events
  // ------------------------------------------------------------------------
  const actions = {
    nav: (el) => navigate(el.dataset.to),
    "go-scan": () => navigate("scan"),
    "set-mode": (el) => setMode(el.dataset.mode),
    "toggle-theme": () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"),
    "open-rail": openRail,
    "close-rail": closeRail,
    "retry-pipeline": () => refreshPipeline(),
    "clear-filters": () => {
      state.filters = { ...state.filters, q: "", stage: "all", minScore: null };
      $("#search").value = "";
      refreshPipeline();
    },
    "run-demo-now": runDemoNow,
    "stage-filter": (el) => { state.filters.stage = el.dataset.stage; refreshPipeline(); },
    "menu-batch": (el) => {
      const items = [{ label: "All batches", sub: `${state.batches.length} in the ${state.mode} workspace`, value: "all", checked: state.filters.batch === "all" }];
      if (state.batches.length) items.push({ sep: true });
      state.batches.forEach((b) => items.push({
        label: `${b.label} · ${b.jd_title}`, sub: `${b.processed} scored · ${b.duplicates} duplicates · ${fmtDateTime(b.created_at)}`, value: b.id, checked: state.filters.batch === b.id,
      }));
      openMenu(el, items, (it) => { state.filters.batch = it.value; refreshPipeline(); }, { title: "Scope" });
    },
    "menu-minscore": (el) => {
      const th = state.analytics?.thresholds || DEFAULT_TH;
      const items = [
        { label: "Any score", value: null }, { label: `${th.hold}+`, sub: "Hold and above", value: th.hold },
        { label: `${th.review}+`, sub: "Technical review and above", value: th.review }, { label: `${th.shortlist}+`, sub: "Shortlist band", value: th.shortlist },
      ].map((x) => ({ ...x, checked: state.filters.minScore === x.value }));
      openMenu(el, items, (it) => { state.filters.minScore = it.value; refreshPipeline(); }, { title: "Minimum role fit", align: "end" });
    },
    "menu-sort": (el) => {
      openMenu(el, Object.entries(SORTS).map(([k, l]) => ({ label: l, value: k, checked: state.filters.sort === k })), (it) => {
        state.filters.sort = it.value;
        state.filters.order = it.value === "name" ? "asc" : "desc";
        prefs.set("ri.sort", it.value);
        prefs.set("ri.order", state.filters.order);
        refreshPipeline();
      }, { title: "Sort by", align: "end" });
    },
    "menu-export": (el) => {
      openMenu(el, [
        { label: "Excel report (.xlsx)", sub: "Current view: summary, candidates, skill gaps, audit", value: "xlsx", icon: "sheet" },
        { sep: true },
        { label: "Audit log (.csv)", sub: "keka_sheets_audit_log.csv", value: "csv", icon: "list" },
        { label: "Audit log (.json)", sub: "keka_sheets_audit_log.json", value: "json", icon: "code" },
      ], (it) => {
        if (it.value === "xlsx") download(exportUrl(), "keka_ats_report.xlsx");
        if (it.value === "csv") download(`/api/exports/audit.csv${qs({ workspace: ws() })}`, "keka_sheets_audit_log.csv");
        if (it.value === "json") download(`/api/exports/audit.json${qs({ workspace: ws() })}`, "keka_sheets_audit_log.json");
      }, { align: "end" });
    },
    "sync-sheets": syncSheets,
    "menu-rescore": (el) => {
      const batch = state.batches.find((b) => b.id === state.filters.batch);
      if (!batch) return;
      const items = state.jds.map((j) => ({
        label: j.title,
        sub: j.id === batch.jd_id ? "Current JD · re-run with its latest weights" : `${j.kind === "sample" ? "Sample" : "Custom"} · ${bandText(j)} · ${j.requirement_counts.critical} critical`,
        value: j.id,
        checked: j.id === batch.jd_id,
      }));
      openMenu(el, items, (it) => rescoreBatch(it.value), { title: `Rescore ${batch.label} against`, align: "end" });
    },
    "bulk-compare": () => openCompare([...state.selection]),
    "close-compare": () => $("#compare-dialog").close(),
    "compare-open": (el) => { $("#compare-dialog").close(); openDrawer(el.dataset.id); },
    "menu-stage": (el) => openStageMenu(el, el.dataset.id),
    "open-candidate": (el) => openDrawer(el.dataset.id),
    "close-drawer": closeDrawer,
    "drawer-prev": () => stepDrawer(-1),
    "drawer-next": () => stepDrawer(1),
    "drawer-tab": (el) => { state.drawer.tab = el.dataset.tab; renderDrawer(); $(`#drawer [data-tab='${el.dataset.tab}']`)?.focus(); },
    "download-resume": (el) => download(`/api/candidates/${el.dataset.id}/file`, "resume"),
    "delete-candidate": (el) => deleteCandidates([el.dataset.id]),
    copy: async (el) => {
      try { await navigator.clipboard.writeText(el.dataset.value); toast(`${el.dataset.label} copied`); }
      catch { toast("Clipboard is unavailable in this browser.", "err"); }
    },
    "bulk-stage": (el) => openMenu(el, STAGE_ORDER.map((k) => ({ label: STAGES[k].label, value: k, glyph: k })), (it) => changeStage([...state.selection], it.value), { title: `Move ${state.selection.size} to` }),
    "bulk-auto": () => changeStage([...state.selection], "__auto"),
    "bulk-export": () => download(exportUrl([...state.selection]), "keka_ats_report.xlsx"),
    "bulk-delete": () => deleteCandidates([...state.selection]),
    "bulk-clear": () => { state.selection.clear(); renderTable(); renderBulk(); },
    "view-batch": (el) => {
      state.filters = { ...state.filters, batch: el.dataset.id, stage: "all", q: "", minScore: null };
      $("#search").value = "";
      navigate("pipeline");
      refreshPipeline();
    },
    "start-scan": startScan,
    "pick-folder": () => $("#pick-folder").click(),
    "pick-files": () => $("#pick-files").click(),
    "remove-queued": (el) => { state.scan.queue.splice(+el.dataset.i, 1); renderScanConfig(); },
    "clear-queue": () => { state.scan.queue = []; state.scan.skipped = []; renderScanConfig(); },
    "retry-item": (el) => retryItem(el.dataset.key),
    "menu-live-jd": (el) => {
      const items = state.jds.map((j) => ({ label: j.title, sub: `${j.kind === "sample" ? "Sample" : "Custom"} · ${bandText(j)} · ${j.requirement_counts.critical} critical`, value: j.id, checked: state.scan.liveJd === j.id }));
      items.push({ sep: true }, { label: "New job description", value: "__new", icon: "plus" });
      openMenu(el, items, (it) => {
        if (it.value === "__new") { navigate("jobs"); newDraft(); return; }
        state.scan.liveJd = it.value;
        renderScanConfig();
      }, { title: "Score against" });
    },
    "new-jd": async () => {
      if (state.mode === "demo") { await setMode("live"); }
      navigate("jobs");
      newDraft();
    },
    "select-jd": (el) => selectJd(el.dataset.id),
    "duplicate-jd": async () => {
      const src = state.jobs.draft;
      if (state.mode === "demo") await setMode("live");
      navigate("jobs");
      newDraft(src);
      toast("Copy created. Edit and save it as a custom job description.");
    },
    "use-jd": () => {
      const d = state.jobs.draft;
      if (state.mode === "demo") state.scan.demoJd = d.id;
      else state.scan.liveJd = d.id;
      navigate("scan");
    },
    "save-jd": saveJd,
    "delete-jd": deleteJd,
    "pick-jd-file": () => $("#pick-jd").click(),
    "reextract-jd": () => { if (state.jobs.draft) { state.jobs.draft.reqEdited = false; analyzeJd(); } },
    "remove-req": (el) => {
      const d = state.jobs.draft;
      d.requirements[el.dataset.tier].splice(+el.dataset.i, 1);
      d.reqEdited = true;
      $("#req-section").innerHTML = reqSection(d, false);
    },
    "menu-audit-filter": (el) => openMenu(el, AUDIT_FILTERS.map(([k, l]) => ({ label: l, value: k, checked: state.audit.filter === k })), (it) => { state.audit.filter = it.value; loadAudit(true); }, { title: "Show" }),
    "audit-more": () => loadAudit(false),
    "download-audit-csv": () => download(`/api/exports/audit.csv${qs({ workspace: ws() })}`, "keka_sheets_audit_log.csv"),
    "download-audit-json": () => download(`/api/exports/audit.json${qs({ workspace: ws() })}`, "keka_sheets_audit_log.json"),
    "reset-workspace": (el) => resetWorkspace(el.dataset.ws),
  };

  document.addEventListener("click", (e) => {
    const nav = e.target.closest(".nav a");
    if (nav) { closeRail(); return; }
    const el = e.target.closest("[data-action]");
    if (el && !el.disabled && el.getAttribute("aria-disabled") !== "true") {
      const name = el.dataset.action;
      // Inputs handle their own changes below.
      if (["select-row", "pick-demo-jd", "toggle-sample", "toggle-all-samples", "set-provider"].includes(name)) return;
      if (actions[name]) { e.preventDefault(); actions[name](el, e); return; }
    }
    const row = e.target.closest("tr.row");
    if (row && !e.target.closest("[data-stop]") && !e.target.closest("a")) openDrawer(row.dataset.id);
  });

  document.addEventListener("change", async (e) => {
    const t = e.target;
    const action = t.dataset.action;
    if (action === "select-row") {
      t.checked ? state.selection.add(t.dataset.id) : state.selection.delete(t.dataset.id);
      t.closest("tr").classList.toggle("is-selected", t.checked);
      const all = state.rows.length && state.rows.every((r) => state.selection.has(r.id));
      $("#check-all").checked = all;
      $("#check-all").indeterminate = !all && state.selection.size > 0;
      renderBulk();
    } else if (t.id === "check-all") {
      if (t.checked) state.rows.forEach((r) => state.selection.add(r.id));
      else state.selection.clear();
      renderTable();
      renderBulk();
    } else if (action === "pick-demo-jd") {
      state.scan.demoJd = t.value;
      renderScanConfig();
    } else if (action === "toggle-sample") {
      t.checked ? state.scan.demoSelected.add(t.value) : state.scan.demoSelected.delete(t.value);
      renderScanConfig();
    } else if (action === "toggle-all-samples") {
      state.scan.demoSelected = new Set(t.checked ? state.samples.map((s) => s.filename) : []);
      renderScanConfig();
    } else if (action === "set-provider") {
      try {
        state.settings = await api("/api/settings", { method: "PATCH", json: { provider: t.value } });
        renderRailStatus();
        renderIntegrations();
        toast(`New batches use the ${engineLabel()}`);
      } catch (err) { toast(err.message, "err"); loadIntegrations(); }
    } else if (t.id === "pick-folder" || t.id === "pick-files") {
      addFiles([...t.files].map((f) => ({ file: f, path: f.webkitRelativePath || f.name })));
      t.value = "";
    } else if (t.id === "pick-jd") {
      if (t.files[0]) uploadJdFile(t.files[0]);
      t.value = "";
    } else if (t.dataset.threshold) {
      const d = state.jobs.draft;
      d.thresholds[t.dataset.threshold] = clamp(Number(t.value) || 0, 0, 100);
      $("#threshold-preview").innerHTML = rulerLarge(null, d.thresholds);
    }
  });

  document.addEventListener("input", (e) => {
    const t = e.target;
    if (t.id === "search") { searchChanged(t.value); return; }
    const d = state.jobs.draft;
    if (!d) return;
    if (t.dataset.jd) {
      const key = t.dataset.jd;
      d[key] = t.type === "number" ? (t.value === "" ? null : Number(t.value)) : t.value;
      if (key === "text") analyzeJd();
    } else if (t.dataset.weight) {
      // Update numbers in place: replacing the range input mid-drag would drop the drag.
      d.weights[t.dataset.weight] = Number(t.value);
      const n = normalizedWeights(d.weights);
      $$("#weights-section .weight-row").forEach((row) => {
        const key = row.querySelector("[data-weight]").dataset.weight;
        row.querySelector(".mono").textContent = `${n[key]}%`;
      });
      $$("#weights-section .weight-stack span").forEach((span, i) => { span.style.flexGrow = Math.max(n[DIMENSIONS[i].key], 0.01); });
    }
  });

  const searchChanged = debounce((v) => { state.filters.q = v; refreshPipeline(); }, 220);

  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("[data-form='note']");
    if (!form) return;
    e.preventDefault();
    const text = form.note.value.trim();
    if (!text) { form.note.focus(); return; }
    try {
      await api(`/api/candidates/${form.dataset.id}`, { method: "PATCH", json: { note: text } });
      toast("Note added");
      await openDrawer(form.dataset.id, { keepTab: true });
      refreshPipeline();
    } catch (err) { toast(err.message, "err"); }
  });

  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t.dataset?.reqAdd && e.key === "Enter") {
      e.preventDefault();
      const value = t.value.trim();
      if (!value) return;
      const d = state.jobs.draft;
      if (!d.requirements[t.dataset.reqAdd].includes(value)) d.requirements[t.dataset.reqAdd].push(value);
      d.reqEdited = true;
      const tier = t.dataset.reqAdd;
      $("#req-section").innerHTML = reqSection(d, false);
      $(`[data-req-add='${tier}']`)?.focus();
      return;
    }
    if (e.key === "Escape") {
      if (menu) return;
      if ($("#confirm-dialog").open || $("#compare-dialog").open) return;
      if (!$("#drawer").hidden) { closeDrawer(); return; }
      if ($("#rail").classList.contains("is-open")) closeRail();
      return;
    }
    const drawerOpen = !$("#drawer").hidden;
    if (drawerOpen && e.key === "Tab") {
      const focusables = $$("#drawer button:not([disabled]), #drawer a[href], #drawer textarea, #drawer input, #drawer [tabindex='0']");
      if (focusables.length) {
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        else if (!$("#drawer").contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      }
      return;
    }
    if (isTyping(t) || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "/" && state.view === "pipeline") { e.preventDefault(); $("#search").focus(); return; }
    if (drawerOpen && (e.key === "j" || e.key === "J")) { stepDrawer(1); return; }
    if (drawerOpen && (e.key === "k" || e.key === "K")) { stepDrawer(-1); return; }
    const hotkey = { s: "shortlisted", t: "technical_review", h: "hold", r: "rejected" }[e.key.toLowerCase()];
    if (drawerOpen && hotkey && state.drawer.data && state.drawer.data.stage !== hotkey) { changeStage([state.drawer.id], hotkey); return; }
    if (e.key === "Enter") {
      const row = t.closest?.("tr.row");
      if (row) { openDrawer(row.dataset.id); return; }
      const runRow2 = t.closest?.(".run-row[data-action='open-candidate']");
      if (runRow2) openDrawer(runRow2.dataset.id);
    }
  });

  document.addEventListener("toggle", (e) => {
    if (e.target.id === "event-log") state.scan.logOpen = e.target.open;
  }, true);

  // Drag and drop (folders included) onto the Live dropzone.
  document.addEventListener("dragover", (e) => {
    const zone = e.target.closest?.("#dropzone");
    if (!zone || state.mode !== "live") return;
    e.preventDefault();
    zone.classList.add("is-over");
  });
  document.addEventListener("dragleave", (e) => {
    const zone = e.target.closest?.("#dropzone");
    if (zone && !zone.contains(e.relatedTarget)) zone.classList.remove("is-over");
  });
  document.addEventListener("drop", async (e) => {
    const zone = e.target.closest?.("#dropzone");
    if (!zone) return;
    e.preventDefault();
    zone.classList.remove("is-over");
    if (state.scan.run?.status === "running") { toast("Wait for the running batch to finish.", "err"); return; }
    const items = [...(e.dataTransfer.items || [])];
    let files = [];
    const entries = items.length && items[0].webkitGetAsEntry ? items.map((i) => i.webkitGetAsEntry()).filter(Boolean) : [];
    if (entries.length) {
      files = (await Promise.all(entries.map((en) => readEntry(en)))).flat();
    } else {
      // Some drag sources expose files without directory entries.
      files = [...e.dataTransfer.files].map((f) => ({ file: f, path: f.name }));
    }
    addFiles(files);
  });

  $("#compare-dialog").addEventListener("click", (e) => { if (e.target.id === "compare-dialog") e.target.close(); });

  $("#mode-switch").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-mode]");
    if (b) setMode(b.dataset.mode);
  });
  $("#mode-switch").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = state.mode === "demo" ? "live" : "demo";
    setMode(next).then(() => $(`#mode-switch [data-mode='${next}']`).focus());
  });

  $$(".th-sort").forEach((b) => b.addEventListener("click", () => {
    const key = b.dataset.sort;
    const f = state.filters;
    if (f.sort === key) f.order = f.order === "asc" ? "desc" : "asc";
    else { f.sort = key; f.order = key === "name" ? "asc" : "desc"; }
    prefs.set("ri.sort", f.sort);
    prefs.set("ri.order", f.order);
    refreshPipeline();
  }));

  // ------------------------------------------------------------------------
  // Boot
  // ------------------------------------------------------------------------
  async function init() {
    applyTheme(document.documentElement.dataset.theme || "light");
    renderModeSwitch();
    renderSkeletons();
    try {
      const [settings, samples] = await Promise.all([api("/api/settings"), api("/api/samples")]);
      state.settings = settings;
      state.samples = samples.samples;
    } catch (e) {
      state.error = e.message;
    }
    renderRailStatus();
    await loadWorkspace();
    renderBanner();
    addEventListener("hashchange", route);
    route();
  }

  init();
})();
