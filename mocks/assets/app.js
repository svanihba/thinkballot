/* ThinkBallot mock — shared behavior. Mock login is a localStorage flag; nothing is real. */

const TBApp = {
  user() {
    try { return localStorage.getItem("tb_mock_user"); } catch { return null; }
  },
  signIn(name) {
    localStorage.setItem("tb_mock_user", name || "demo_voter");
    location.reload();
  },
  signOut() {
    localStorage.removeItem("tb_mock_user");
    location.reload();
  },

  esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  },

  srcChip(id) {
    const s = TB.sources[id];
    if (!s) return "";
    return `<a class="src" href="${s.url}" title="${this.esc(s.label)}">[${id.replace("src-", "")}]</a>`;
  },

  /* header auth chip */
  initHeader() {
    const el = document.getElementById("auth-chip");
    if (!el) return;
    const u = this.user();
    if (u) {
      el.textContent = "@" + u + " · sign out";
      el.classList.add("signed-in");
      el.addEventListener("click", (e) => { e.preventDefault(); this.signOut(); });
    } else {
      el.textContent = "sign in";
      el.setAttribute("href", "account.html");
    }
  },

  param(name, fallback) {
    return new URLSearchParams(location.search).get(name) || fallback;
  },

  measureCard(m) {
    return `
      <article class="card measure">
        <div class="top"><span class="tag">Measure</span><span class="chip">${this.esc(m.scope)}</span></div>
        <h3><a href="item-measure.html?id=${m.id}">${this.esc(m.title)}</a></h3>
        <p class="summary">${this.esc(m.summary)}</p>
        <div class="foot">
          <a class="btn ghost small" href="item-measure.html?id=${m.id}">Full card →</a>
          ${m.sources.map((s) => this.srcChip(s)).join(" ")}
        </div>
      </article>`;
  },

  raceCard(r) {
    return `
      <article class="card race">
        <div class="top"><span class="tag">Race</span><span class="chip">${this.esc(r.scope)}</span></div>
        <h3><a href="item-race.html?id=${r.id}">${this.esc(r.office)}</a></h3>
        <p class="summary">${r.candidates.map((c) => this.esc(c.name) + " (" + this.esc(c.party) + ")").join(" · ")}</p>
        <div class="foot">
          <a class="btn ghost small" href="item-race.html?id=${r.id}">Full card →</a>
          ${r.sources.map((s) => this.srcChip(s)).join(" ")}
        </div>
      </article>`;
  },

  communityZone(itemId) {
    const u = this.user();
    const comments = (TB.comments[itemId] || [])
      .map((c) => `<div class="comment"><div class="who">${this.esc(c.who)}</div><p>${this.esc(c.text)}</p></div>`)
      .join("");
    const facts = (TB.communityFacts[itemId] || [])
      .map(
        (f) => `<div class="fact"><span class="status ${f.status}">${f.status}</span><p>${this.esc(f.text)}</p><div class="meta">${this.esc(f.meta)}</div></div>`
      )
      .join("");
    const composer = u
      ? `<div class="composer"><textarea placeholder="Join the discussion as @${this.esc(u)} — be civil; moderation is viewpoint-neutral (mock)"></textarea><button class="btn small" onclick="alert('Mock only — nothing is posted.')">Post comment</button>
         <button class="btn ghost small" onclick="alert('Mock only — a real submission would require citations, pass grounding checks, then Community-Notes-style cross-perspective rating, then human review.')">Submit a fact (requires citations)</button></div>`
      : `<div class="locked">Reading is always open. <a href="account.html">Sign in</a> to comment, submit facts, or subscribe — accounts exist only for interaction.</div>`;
    return `
      <section class="community">
        <div class="zone-label">▚ Community discussion — separate from the official grounded content above · post-moderated · viewpoint-neutral rules</div>
        ${comments || '<p class="hint">No comments yet on this item.</p>'}
        ${facts ? `<div class="zone-label" style="margin-top:1.4rem">▚ Community-submitted facts — cited, vetted (bridging consensus), human-reviewed</div>${facts}` : ""}
        ${composer}
      </section>`;
  },
};

document.addEventListener("DOMContentLoaded", () => TBApp.initHeader());
