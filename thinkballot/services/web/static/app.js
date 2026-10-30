/* ThinkBallot browser code: stars, reading progress, share links, the Ask box, and visitor analytics.
   Stars and "read" ticks live only in this browser (localStorage). On www, page and button use is sent to
   ThinkBallot's own server (see Privacy on the methodology page), unless the browser sends Global Privacy
   Control or Do Not Track. */

const store = {
  get(key) {
    try { return JSON.parse(localStorage.getItem(key)) || {}; } catch { return {}; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: just don't save */ }
  },
};

/* The page's language: strings come from the page (body data-i18n, filled by the server in the page's
   language) and links keep the page's language prefix ("", "/es" or "/zh"). */
let UI = {};
try { UI = JSON.parse(document.body.dataset.i18n || "{}"); } catch { UI = {}; }
const PREFIX = document.body.dataset.prefix || "";
function t(key, vars) {
  let s = UI[key] || key;
  Object.entries(vars || {}).forEach(([k, v]) => { s = s.split(`{${k}}`).join(v); });
  return s;
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");  // also safe inside attributes
}

/* ---------- analytics ----------
   Events go to our own server with the page's signed token (body data-et), in small batches: every 5 s,
   at 20 events, and when the page is hidden or closed. Failures are ignored; nothing is retried. */
const ET = document.body.dataset.et || "";
const OPTED_OUT = typeof navigator === "undefined"
  || navigator.globalPrivacyControl === true || navigator.doNotTrack === "1";
const PAGE = (typeof location === "undefined" ? "" : location.pathname.slice(PREFIX.length)) || "/";
let queue = [];

function flush(leaving) {
  if (!queue.length) return;
  const body = JSON.stringify({ t: ET, p: PAGE, events: queue.splice(0, 20) });
  try {
    if (leaving && navigator.sendBeacon) {
      navigator.sendBeacon(PREFIX + "/api/e", new Blob([body], { type: "application/json" }));
    } else {
      fetch(PREFIX + "/api/e", { method: "POST", headers: { "Content-Type": "application/json" }, body,
        keepalive: true }).catch(() => {});
    }
  } catch { /* analytics never gets in the way */ }
  if (queue.length) flush(leaving);
}

function track(type, props) {
  if (!ET || OPTED_OUT) return;
  queue.push({ type, ts: Date.now(), props: props || {} });
  if (queue.length >= 20) flush(false);
}

/* Every control a visitor uses is logged by what it is (name, kind, visible label), never by what was typed:
   text boxes are not logged at all. data-track gives the important controls stable names. */
const CONTROLS = "a, button, summary, select, input[type=checkbox], input[type=radio], [role=button], [role=tab], "
  + "[data-track]";
const cut = (v, n) => String(v == null ? "" : v).replace(/\s+/g, " ").trim().slice(0, n);

function measureOf(el, href) {
  const card = el.closest("[data-measure]");
  const m = (card && card.dataset.measure) || ((href || "").match(/\/prop\/([a-z0-9-]+)/) || [])[1]
    || (PAGE.match(/^\/prop\/([a-z0-9-]+)/) || [])[1];
  return m || undefined;
}

function describe(el) {
  const kind = el.tagName === "INPUT" ? el.type : el.tagName.toLowerCase();
  const p = { name: cut(el.dataset.track || el.id || (el.className || "").split(" ")[0] || kind, 40), kind: cut(kind, 16) };
  const label = el.dataset.trackLabel || el.getAttribute("aria-label")
    || (el.tagName === "INPUT" ? el.labels && el.labels[0] && el.labels[0].textContent : el.textContent);
  if (cut(label, 80)) p.label = cut(label, 80);
  let href;
  if (el.tagName === "A" && el.href) {
    try {
      const u = new URL(el.href, location.href);
      href = u.origin === location.origin ? (u.pathname.replace(/^\/(es|zh)(?=\/|$)/, "") || "/") + u.hash : u.hostname;
    } catch { /* not a URL */ }
  }
  const measure = measureOf(el, href);
  if (measure) p.measure = measure;
  if (href) p.href = cut(href, 120);
  const rank = parseInt(el.dataset.rank || el.dataset.index, 10);
  if (rank >= 0) p.rank = rank;
  if (el.tagName === "INPUT") p.on = !!el.checked;
  else if (el.tagName === "SUMMARY" && el.parentElement) p.on = !!el.parentElement.open;
  else if (el.getAttribute("aria-pressed") != null) p.on = el.getAttribute("aria-pressed") === "true";
  return p;
}

function initControlTracking() {
  document.addEventListener("click", (e) => {
    const el = e.target && e.target.closest && e.target.closest(CONTROLS);
    if (!el || el.tagName === "SELECT") return;  // dropdowns are logged when a choice is made
    setTimeout(() => track("click", describe(el)), 0);  // after the control's own handler (star, open/close)
  }, true);
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (!el || el.tagName !== "SELECT") return;
    const p = { name: cut(el.dataset.track || el.id || el.name || "select", 40) };
    if (el.dataset.track) {  // the choice itself only for named dropdowns (never, e.g., a political leaning)
      const opt = el.options && el.options[el.selectedIndex];
      p.value = cut(el.value, 80);
      if (opt && cut(opt.text, 80)) p.label = cut(opt.text, 80);
    }
    const measure = measureOf(el);
    if (measure) p.measure = measure;
    track("select", p);
  }, true);
  const seen = new Set();
  addEventListener("scroll", () => {
    const total = document.documentElement.scrollHeight || 1;
    const pct = ((window.scrollY || 0) + innerHeight) / total * 100;
    [25, 50, 75, 100].forEach((d) => { if (pct >= d && !seen.has(d)) { seen.add(d); track("scroll", { depth: d }); } });
  }, { passive: true });
  let errors = 0;
  const report = (message, source, line) => {
    if (errors++ >= 5) return;
    track("error", { message: cut(message, 200), source: cut(String(source || "").replace(location.origin, ""), 120),
      line: Math.max(0, Math.min(line | 0, 10000000)) });
  };
  addEventListener("error", (e) => report(e.message, e.filename, e.lineno));
  addEventListener("unhandledrejection", (e) => report(e.reason && (e.reason.message || e.reason), "promise", 0));
}

function initAnalytics() {
  if (!ET || OPTED_OUT) return;
  setInterval(() => flush(false), 5000);
  initControlTracking();
  let shownAt = Date.now(), shown = 0;
  const engaged = () => {
    if (shownAt) { shown += Date.now() - shownAt; shownAt = 0; }
    if (shown > 0) { track("engaged", { ms: Math.min(shown, 86400000) }); shown = 0; }
  };
  addEventListener("pagehide", () => { engaged(); flush(true); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") { engaged(); flush(true); } else shownAt = Date.now();
  });
  const timing = () => setTimeout(() => {  // after load has finished, so loadEventEnd is set
    const nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
    const ms = (v) => Math.max(0, Math.round(v || 0));
    track("timing", { ttfb: ms(nav && nav.responseStart), dom: ms(nav && nav.domContentLoadedEventEnd),
      load: ms(nav && nav.loadEventEnd), vw: innerWidth, vh: innerHeight });
  }, 0);
  if (document.readyState === "complete") timing(); else addEventListener("load", timing);
}

/* ---------- stars ---------- */
function paintStar(btn, on) {
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.textContent = on ? t("starred") : t("star");
}

function initStars() {
  const stars = store.get("tb_stars");
  document.querySelectorAll("[data-measure]").forEach((el) => {
    const id = el.dataset.measure;
    const btn = el.querySelector(".star");
    if (!btn) return;
    paintStar(btn, !!stars[id]);
    btn.addEventListener("click", () => {
      const s = store.get("tb_stars");
      if (s[id]) delete s[id]; else s[id] = el.dataset.title;
      store.set("tb_stars", s);
      paintStar(btn, !!s[id]);
      renderStarred();
    });
  });
  renderStarred();
}

function renderStarred() {
  const section = document.getElementById("starred");
  if (!section) return;
  const stars = store.get("tb_stars");
  const ids = Object.keys(stars);
  section.hidden = ids.length === 0;
  document.getElementById("starred-list").innerHTML =
    ids.map((id) => `<li><a href="${PREFIX}/prop/${encodeURIComponent(id)}">${esc(stars[id])}</a></li>`).join("");
}

/* ---------- reading progress ---------- */
function markRead() {
  const page = document.querySelector(".measure-page");
  if (!page) return;
  const read = store.get("tb_read");
  read[page.dataset.measure] = true;
  store.set("tb_read", read);
}

function paintProgress() {
  const box = document.querySelector(".progress");
  if (!box) return;
  const read = store.get("tb_read");
  const cards = document.querySelectorAll(".card[data-measure]:not(.local)");  // the meter counts statewide props
  let n = 0;
  document.querySelectorAll(".card.local[data-measure]").forEach((card) => {
    card.querySelector(".read-tick").hidden = !read[card.dataset.measure];
  });
  cards.forEach((card) => {
    const done = !!read[card.dataset.measure];
    card.querySelector(".read-tick").hidden = !done;
    if (done) n += 1;
  });
  const total = cards.length;
  document.getElementById("read-count").textContent = n;
  const bar = document.getElementById("read-bar");
  bar.style.width = total ? (100 * n / total) + "%" : "0";
  bar.parentElement.setAttribute("aria-valuenow", n);
  document.getElementById("ballot-ready").hidden = !(total && n === total);
}

/* ---------- share ---------- */
function initShare() {
  const btn = document.querySelector(".share");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const url = location.origin + location.pathname;
    const title = document.querySelector(".measure-page").dataset.title;
    if (navigator.share) {
      try { await navigator.share({ title, url }); return; } catch { /* cancelled: fall back to copy */ }
    }
    try {
      await navigator.clipboard.writeText(url);
      document.querySelector(".share-done").hidden = false;
    } catch { prompt(t("copy"), url); }
  });
}

/* ---------- ask ---------- */
const VERDICT_TEXT = {
  pass: t("pass"),
  revised: t("revised"),
};

// Answers to the suggested questions may be prepared in advance; say so, and when.
function preparedNote(r) {
  if (!r.prepared) return "";
  const locale = { es: "es-US", "zh-Hant": "zh-TW" }[document.documentElement.lang] || "en-US";
  const day = new Date(r.prepared + "T00:00:00Z").toLocaleDateString(locale,
    { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
  const note = t(r.status === "answered" ? "prepared_checked" : "prepared", { day: esc(day) });
  return `<p class="prepared-note">${note}</p>`;
}

// suggested: the answer is to a suggested question (on other pages it may come translated).
function renderAnswer(r, suggested) {
  if (r.status === "answered") {
    // A translated answer: claims in the page's language; each quote is official text, in the page's
    // language where the official translation has it, otherwise the English original (marked so).
    const translated = !!(PREFIX && r.translated);
    const points = r.points.map((p) => `
      <li><p>${esc(p.claim)}</p>
        <blockquote${translated && p.quote_lang === "en" ? ' lang="en"' : ""}>“${esc(p.quote)}” <a class="src" href="${esc(p.source_url)}" target="_blank" rel="noopener">${esc(p.source_label)}</a></blockquote>
      </li>`).join("");
    const findings = r.findings.length
      ? `<ul class="findings">${r.findings.map((f) => `<li>${esc(f.detail)}</li>`).join("")}</ul>` : "";
    let langNote = "";
    if (translated) langNote = `<p class="prepared-note">${esc(t("translated"))}</p>`;
    else if (PREFIX && suggested) langNote = `<p class="prepared-note">${esc(t("in_english"))}</p>`;
    // Other answers are written in English from the English official text: mark them so on other pages.
    return `<div class="answer"><ul class="points"${PREFIX && !translated ? ' lang="en"' : ""}>${points}</ul>
      <div class="verdict ${esc(r.verdict)}">${esc(VERDICT_TEXT[r.verdict] || t("bias"))}
        ${r.findings.length ? `· ${esc(r.findings.length > 1 ? t("changes", { n: r.findings.length }) : t("change"))}` : ""}</div>${findings}${langNote}<p class="prepared-note">${esc(t("ai_label"))}</p>${preparedNote(r)}</div>`;
  }
  if (r.status === "blocked") {
    return `<div class="answer held"><p>${esc(r.reason)}</p><div class="verdict blocked">${esc(t("held"))}</div></div>`;
  }
  return `<div class="answer refused"><p>${esc(r.reason)}</p>${preparedNote(r)}</div>`;
}

// The server doesn't report its steps, so the bar follows the clock: it eases toward 95% over the
// ~100 s time budget and the answer replaces it as soon as it arrives.
function showAskProgress(out) {
  out.innerHTML = `<div class="ask-progress" role="status">
    <p class="hint">${esc(t("working"))}</p>
    <div class="progress-bar" role="progressbar" aria-label="${esc(t("working_label"))}"
      aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span></span></div>
    <p class="progress-text" aria-hidden="true">${esc(t("processing"))} <span class="elapsed">0</span> ${esc(t("seconds"))}</p></div>`;
  const bar = out.querySelector(".progress-bar"), fill = bar.querySelector("span");
  const elapsed = out.querySelector(".elapsed"), started = Date.now();
  const tick = () => {
    const t = (Date.now() - started) / 1000;
    const pct = Math.round(95 * (1 - Math.exp(-t / 35)));
    fill.style.width = pct + "%";
    bar.setAttribute("aria-valuenow", pct);
    elapsed.textContent = Math.floor(t);
  };
  tick();
  const id = setInterval(tick, 500);
  return () => clearInterval(id);
}

// Bring the progress bar or the answer into view, but only when its top is off screen: someone
// reading the page shouldn't be yanked around. Honours prefers-reduced-motion.
function revealIfHidden(el) {
  const r = el.getBoundingClientRect();
  if (r.top >= 0 && r.top < window.innerHeight - 48) return;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ block: "start", behavior: still ? "auto" : "smooth" });
}

function initAsk() {
  const form = document.querySelector(".ask-form");
  if (!form) return;
  const out = document.querySelector(".ask-result");
  const measureId = form.dataset.measure;
  const suggestions = document.querySelectorAll(".suggest");
  let suggested = null;  // number of the suggested question being asked; null for a typed question
  form.question.addEventListener("input", () => { suggested = null; });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = form.question.value.trim();
    if (!question) return;
    const which = suggested;
    suggested = null;
    const button = form.querySelector("button");
    button.disabled = true;
    suggestions.forEach((b) => { b.disabled = true; });
    form.question.blur();  // phones: close the on-screen keyboard so the progress bar shows
    out.setAttribute("aria-busy", "true");
    const stopProgress = showAskProgress(out);
    revealIfHidden(out);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 125000);
    try {
      const resp = await fetch(PREFIX + "/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign(which === null ? { measure_id: measureId, question }
          : { measure_id: measureId, question, suggested: which }, ET ? { t: ET } : {})),
        signal: ctrl.signal,
      });
      out.innerHTML = renderAnswer(await resp.json(), which !== null);
    } catch (err) {
      out.innerHTML = renderAnswer({ status: "error", reason: err.name === "AbortError"
        ? t("too_long") : t("offline") });
    } finally {
      clearTimeout(timer);
      stopProgress();
      button.disabled = false;
      suggestions.forEach((b) => { b.disabled = false; });
      out.removeAttribute("aria-busy");
      revealIfHidden(out);
    }
  });
  // Suggested questions: fill the box and ask straight away.
  // The server finds the prepared answer by the question's number; the box shows the English question.
  document.querySelectorAll(".suggest").forEach((b) => b.addEventListener("click", () => {
    form.question.value = b.dataset.question || b.textContent;  // suggested questions are asked in English
    suggested = Number(b.dataset.index);
    form.requestSubmit();
  }));
}

/* ---------- ZIP code box ---------- */
/* Suggests the ZIP codes ThinkBallot has districts for (loaded on first use) and accepts only those.
   The server checks again, so the box still works without this code. */
function initZipBox() {
  const input = document.querySelector("input[name=zip][list]");
  if (!input) return;
  const list = document.getElementById(input.getAttribute("list"));
  let known = null, loading = null;
  const load = () => loading || (loading = fetch(input.dataset.zips)
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((data) => {
      known = new Set(data.zips.map(([zip]) => zip));
      const frag = document.createDocumentFragment();
      data.zips.forEach(([zip, city]) => {
        const o = document.createElement("option");
        o.value = zip;
        o.label = city;
        frag.appendChild(o);
      });
      list.appendChild(frag);
    })
    .catch(() => { loading = null; }));  // leave checking to the server; try again next time
  const check = () => {
    const v = input.value.trim();
    input.setCustomValidity(known && v.length === 5 && !known.has(v) ? t("zip_unknown") : "");
  };
  input.addEventListener("focus", load, { once: true });
  input.addEventListener("input", () => {
    input.value = input.value.replace(/\D/g, "").slice(0, 5);
    load();
    check();
  });
  input.form.addEventListener("submit", (e) => {
    const v = input.value.trim();
    if (known && !known.has(v)) {
      e.preventDefault();
      input.setCustomValidity(t("zip_unknown"));
      input.reportValidity();
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  // Choosing a proposition on the Ask page reloads it for that proposition (no inline handlers: CSP).
  document.querySelectorAll("select.autosubmit").forEach((s) => s.addEventListener("change", () => s.form.submit()));
  // Phones show the topics as a sideways strip: keep the chosen topic in view.
  const strip = document.querySelector(".filters"), chosen = strip && strip.querySelector(".on");
  if (chosen && strip.scrollWidth > strip.clientWidth) strip.scrollLeft = chosen.offsetLeft - strip.offsetLeft - 16;
  markRead();
  initStars();
  paintProgress();
  initShare();
  initAsk();
  initZipBox();
  initAnalytics();
});
