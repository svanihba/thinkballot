/* ThinkBallot browser code: stars, reading progress, share links, and the Ask box.
   Stars and "read" ticks live only in this browser (localStorage); nothing is sent to the server. */

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
  return d.innerHTML;
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

function renderAnswer(r) {
  if (r.status === "answered") {
    const points = r.points.map((p) => `
      <li><p>${esc(p.claim)}</p>
        <blockquote>“${esc(p.quote)}” <a class="src" href="${esc(p.source_url)}" target="_blank" rel="noopener">${esc(p.source_label)}</a></blockquote>
      </li>`).join("");
    const findings = r.findings.length
      ? `<ul class="findings">${r.findings.map((f) => `<li>${esc(f.detail)}</li>`).join("")}</ul>` : "";
    return `<div class="answer"><ul class="points">${points}</ul>
      <div class="verdict ${esc(r.verdict)}">${esc(VERDICT_TEXT[r.verdict] || t("bias"))}
        ${r.findings.length ? `· ${esc(r.findings.length > 1 ? t("changes", { n: r.findings.length }) : t("change"))}` : ""}</div>${findings}${preparedNote(r)}</div>`;
  }
  if (r.status === "blocked") {
    return `<div class="answer held"><p>${esc(r.reason)}</p><div class="verdict blocked">${esc(t("held"))}</div></div>`;
  }
  return `<div class="answer refused"><p>${esc(r.reason)}</p>${preparedNote(r)}</div>`;
}

// The server doesn't report its steps, so the bar follows the clock: it eases toward 95% over the
// ~85 s time budget and the answer replaces it as soon as it arrives.
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
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = form.question.value.trim();
    if (!question) return;
    const button = form.querySelector("button");
    button.disabled = true;
    suggestions.forEach((b) => { b.disabled = true; });
    form.question.blur();  // phones: close the on-screen keyboard so the progress bar shows
    out.setAttribute("aria-busy", "true");
    const stopProgress = showAskProgress(out);
    revealIfHidden(out);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 110000);
    try {
      const resp = await fetch(PREFIX + "/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ measure_id: measureId, question }),
        signal: ctrl.signal,
      });
      out.innerHTML = renderAnswer(await resp.json());
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
  document.querySelectorAll(".suggest").forEach((b) => b.addEventListener("click", () => {
    form.question.value = b.dataset.question || b.textContent;  // suggested questions are asked in English
    form.requestSubmit();
  }));
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
});
