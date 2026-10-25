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

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

/* ---------- stars ---------- */
function paintStar(btn, on) {
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.textContent = on ? "★ Starred" : "☆ Star";
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
    ids.map((id) => `<li><a href="/prop/${encodeURIComponent(id)}">${esc(stars[id])}</a></li>`).join("");
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
  const cards = document.querySelectorAll(".card[data-measure]");
  let n = 0;
  cards.forEach((card) => {
    const done = !!read[card.dataset.measure];
    card.querySelector(".read-tick").hidden = !done;
    if (done) n += 1;
  });
  const total = cards.length;
  document.getElementById("read-count").textContent = n;
  document.getElementById("read-bar").style.width = total ? (100 * n / total) + "%" : "0";
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
    } catch { prompt("Copy this link:", url); }
  });
}

/* ---------- ask ---------- */
const VERDICT_TEXT = {
  pass: "Bias Buster: passed",
  revised: "Bias Buster: edited",
};

function renderAnswer(r) {
  if (r.status === "answered") {
    const points = r.points.map((p) => `
      <li><p>${esc(p.claim)}</p>
        <blockquote>“${esc(p.quote)}” <a class="src" href="${esc(p.source_url)}" target="_blank" rel="noopener">${esc(p.source_label)}</a></blockquote>
      </li>`).join("");
    const findings = r.findings.length
      ? `<ul class="findings">${r.findings.map((f) => `<li>${esc(f.detail)}</li>`).join("")}</ul>` : "";
    return `<div class="answer"><ul class="points">${points}</ul>
      <div class="verdict ${esc(r.verdict)}">${esc(VERDICT_TEXT[r.verdict] || "Bias Buster")}
        ${r.findings.length ? `· ${r.findings.length} change${r.findings.length > 1 ? "s" : ""}` : ""}</div>${findings}</div>`;
  }
  if (r.status === "blocked") {
    return `<div class="answer held"><p>${esc(r.reason)}</p><div class="verdict blocked">Bias Buster: held back</div></div>`;
  }
  return `<div class="answer refused"><p>${esc(r.reason)}</p></div>`;
}

function initAsk() {
  const form = document.querySelector(".ask-form");
  if (!form) return;
  const out = document.querySelector(".ask-result");
  const measureId = form.dataset.measure;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = form.question.value.trim();
    if (!question) return;
    const button = form.querySelector("button");
    button.disabled = true;
    out.innerHTML = `<p class="hint thinking">Reading the official text and running Bias Buster…</p>`;
    try {
      const resp = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ measure_id: measureId, question }),
      });
      out.innerHTML = renderAnswer(await resp.json());
    } catch {
      out.innerHTML = renderAnswer({ status: "error", reason: "Couldn't reach ThinkBallot. Check your connection." });
    } finally {
      button.disabled = false;
    }
  });
  // Suggested questions: fill the box and ask straight away.
  document.querySelectorAll(".suggest").forEach((b) => b.addEventListener("click", () => {
    form.question.value = b.textContent;
    form.requestSubmit();
  }));
}

document.addEventListener("DOMContentLoaded", () => {
  markRead();
  initStars();
  paintProgress();
  initShare();
  initAsk();
});
