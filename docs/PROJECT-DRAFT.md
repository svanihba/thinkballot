# ThinkBallot — Project Draft & Founding Spec

> **Project name:** ThinkBallot
> **Purpose of this document:** a complete, self-contained brief to **seed a fresh git repository** and
> serve as the starting point for coding agents. It captures the product spec, the options considered, the
> decisions and their reasons, the technical design, a phased build plan, and agent-facing conventions.
> Anything a new contributor (human or agent) needs to begin should be here.

---

## 1. Motivation

First-time and young voters are overwhelmed and under-informed when they get their ballot — especially the
confusing "bottom of the ballot" (propositions, local measures, down-ballot races). Existing resources are
either partisan, dense (official guides run hundreds of pages), or too generic to reflect a specific
ballot.

**ThinkBallot turns a voter's actual ballot into clear, trustworthy, nonpartisan, source-cited
explanations.** It pairs an ingestion pipeline over official election sources with a *grounded* AI layer
and address→district resolution, so a voter can see exactly what's on their ballot and what each item means
— with citations one click away.

Beyond individual voters, ThinkBallot aims to become **civic data infrastructure**: the same grounded,
cited dataset is exposed through a public API for journalists, researchers, and civic developers.

---

## 2. Product overview

**ThinkBallot** is a **California-first web app**, adaptable by design to any state or county (D15). A
user enters their home address and sees **their
personalized ballot** — the statewide propositions plus the district races and county measures that apply
to them — rendered as a set of **plain-language, strictly nonpartisan, source-cited cards**, one per item.

- **Primary user:** first-time & young voters (≈18–24) facing their first ballot.
- **Secondary audience:** journalists, researchers, and civic developers who build on the grounded dataset
  through the public read API (D8).
- **Core value:** understand *what's on my ballot* and *what a yes/no or a given candidate actually means*,
  quickly, without spin, with the receipts (citations) available.
- **No login required:** the site is **fully functional read-only without an account** — ballot lookup,
  cards, search, methodology. Accounts exist *only* for users who want to interact (D10, §5.4).
- **Non-goals (explicitly out of scope):** telling anyone how to vote; endorsements; predictions; partisan
  framing; national coverage (v1); precinct-perfect reproduction of every hyper-local seat (v1).

**Platform vision (long-term):** ThinkBallot is ultimately a *platform*, not just a website — a canonical,
grounded ballot dataset behind multiple clients and APIs. The web app ships first; on top of its read-only
core, a **community layer** — a *separate service* with optional accounts — adds interaction: discussion,
notifications and email digests, grounded AI Q&A, and community-vetted facts. A **public read API** makes
ThinkBallot **civic data infrastructure** for journalists, researchers, and civic developers; a
**government intake API** lets election officials push ballot data into our pipeline; and native **Android
and iOS apps** join as additional clients. The core is **jurisdiction-agnostic**: California first,
adaptable to any state or county, including **separately hosted instances** for individual entities (a
state, a county, a district) via configuration. ThinkBallot also meets voters where their discourse
already happens — embeds, shareable artifacts, and opt-in neutral bots on Discord, Reddit, and
Facebook/Instagram (§5.5). (Scope: §5.3–5.5; decisions: D7–D17 in §3.)

---

## 3. Decisions made (with the options considered and the reasons)

Each row records the **options weighed**, the **decision**, and **why** — so a contributor understands
intent, not just the outcome.

| # | Decision | Options considered | Chosen & why |
|---|---|---|---|
| D1 | **Geographic scope** | (a) California-focused; (b) hyperlocal to one region; (c) national; (d) props-only | **(a) California-focused.** Depth and accuracy beat breadth; a single state keeps data integration tractable and reliable, while national coverage is a large, fragile integration problem. Architecture stays extensible to other states later. |
| D2 | **Primary user** | (a) first-time/young voters; (b) general public; (c) non-English speakers; (d) down-ballot-overwhelmed | **(a) first-time/young voters.** Strongest civic-education impact and the clearest design target. (Multilingual and down-ballot depth become stretch features, not the core framing.) |
| D3 | **Explanation depth** | (a) structured deep card; (b) summary only; (c) summary + "how it affects you"; (d) summary + interactive Q&A | **(a) structured deep card.** Depth plus neutrality is the differentiator. Per item: plain-language summary, what YES/NO means, arguments for/against, fiscal impact, supporters/opponents — all cited. (Personalized "how it affects you" risks drifting from neutrality; open Q&A is hardest to keep accurate — both deferred.) |
| D4 | **Personalization** | (a) address→district-level; (b) precinct-accurate full ballot; (c) county selection; (d) statewide only | **(a) address→district-level.** Geocode to county + congressional/state-legislative districts; show statewide props + those district races + county measures. Feels personalized and is realistically accurate; precinct-perfect data across the state is unreliable to source. |
| D5 | **Data + AI architecture** | (a) grounded pipeline over official sources; (b) curated static dataset; (c) live third-party API aggregation | **(a) + (b) hybrid.** Grounding philosophy of (a) applied to a **pre-ingested, election-scoped dataset** like (b). Accurate, neutral by construction, and maintainable. (c) rejected: Google Civic *voterinfo* was deprecated (2025) and live scraping is fragile. |
| D6 | **Platform / stack** | Flask web vs mobile; store choices | **Flask web app.** Python end-to-end, responsive/mobile-friendly web. Details in §6. |
| D7 | **Platform strategy (long-term)** | (a) web-only, forever; (b) API-first core — web ships first, Android/iOS apps + public API added later over the same core; (c) build all clients + APIs in v1 | **(b) API-first core.** MVP scope stays web-only, but every request-time read goes through a transport-agnostic service layer (§6.1), so mobile apps and the public API become thin additions rather than a rewrite. (a) forecloses the platform vision; (c) delays shipping anything. |
| D8 | **Public read API access** | (a) free registered API keys, rate-limited; (b) fully open with per-IP limits; (c) defer the decision | **(a) free API keys.** The norm for civic APIs — abuse control plus visibility into who builds on the data, with minimal friction for integrators. |
| D9 | **Government data intake** | (a) staged through the normal pipeline; (b) direct writes to the live dataset; (c) hybrid — structural facts live immediately, generated prose after the pipeline | **(a) staged through the pipeline.** A govt push is just another ingestion source: staging → grounding → checks → human review → new dataset version. Preserves cite-or-omit and the LLM-at-build-time property at the cost of some freshness. (b) bypasses the trust guarantees; (c) adds complexity for little value now. |
| D10 | **Account model** | (a) accounts required site-wide; (b) optional accounts — anonymous read-only core, accounts only to interact; (c) no accounts ever | **(b) optional accounts.** The civic mission demands zero-friction access to ballot information; interaction (comments, notifications, Q&A, submissions) is opt-in and account-gated. (a) throttles the mission; (c) forecloses community features. |
| D11 | **Community architecture** | (a) two-plane separation inside one codebase; (b) organic integration into the existing app; (c) separate community service, deployed independently | **(c) separate service.** A *physical* trust boundary: own storage, own deploy, own API; consumes ballot data via the public read API; can never write the grounded dataset. Independent scaling and failure isolation for the read-write side; accepted cost: extra ops + cross-service auth. (b) erodes the trust boundary; (a) is weaker than physical separation. |
| D12 | **Comments & neutrality** | (a) separated community zone with post-moderation; (b) pre-moderated comments; (c) structured interactions only, no free-form comments | **(a) separated zone, post-moderation.** Users may be partisan; the platform never is. Comments render in a visually and structurally distinct "Community discussion" zone, governed by a code of conduct with flagging and viewpoint-neutral removal rules. (b) doesn't scale and invites censorship claims; (c) isn't real conversation. |
| D13 | **Community-facts vetting** | (a) editorial review only; (b) pipeline checks + Community-Notes-style bridging consensus + human review; (c) unmoderated with disclaimers | **(b) checks + bridging + review.** Submissions must carry citations (same cite-or-omit bar), then publish only when rated helpful across raters who typically disagree, then a final human gate. Resistant to brigading by construction. (a) doesn't scale and centralizes judgment; (c) breaks the trust promise. |
| D14 | **Search** | (a) filters + full-text in the MVP via a separate search service, semantic later; (b) semantic-first from day one; (c) no search, address lookup only | **(a) filters + FTS in the MVP, behind a separate search service.** Election/date, geo, type, topic/domain, sponsor, and civic-feature filters plus full-text (SQLite FTS5) ship in the MVP behind a **stable service interface**; the implementation evolves (build-time semantic embeddings later) with **no interface change**. (b) is infra-heavy before value is proven; (c) leaves the dataset opaque to browsing and the API less useful. |
| D15 | **Adaptability & instancing** | (a) hard-code California; (b) jurisdiction-agnostic core — California first, adaptable to any state/county, separately hostable instances per entity; (c) multi-tenant national platform from day one | **(b) jurisdiction-agnostic core, California first** (extends D1). Jurisdiction specifics (sources, districts, elections) live in configuration, so the same codebase serves other states/counties later and can be **hosted as a dedicated instance** for a single entity (a state, county, district, or a congressional delegation). (c) reintroduces the breadth problem D1 rejected; (a) blocks the platform vision. |
| D16 | **Target election (MVP)** | (a) most recent completed CA general (Nov 2024) — stable, guaranteed content; (b) the upcoming **Nov 3, 2026 CA general** — live usefulness; (c) both | **(b) the November 3, 2026 California general election.** The MVP should serve a real, upcoming vote. Until official 2026 guide content is published, development and tests run against the 2024 general as a **stable fixture dataset** — (c) in engineering practice, with 2026 as the product target. |
| D17 | **Platform integration (Facebook/Reddit/Discord)** | (a) none — rely on organic visits; (b) "**be the citation, not the destination**": embeds + shareable artifacts + opt-in, neutral, cards-only bots where young voters already talk; (c) live *on* the platforms (social login, cross-posted comments, platform-native community) | **(b) meet the discourse where it happens.** Young voters encounter political information incidentally, in-feed and in-chat; the moment of peak motivation is inside the conversation (Fogg's B=MAP). Grounded, cited cards dropped into live threads act as neutral corrections that persuade bystanders (Bode & Vraga's observational-correction research). Per-platform psychology drives the design: Discord = third-place deliberation among peers (CIRCLE: peers mobilize peers; context collapse keeps this off identified platforms); Reddit = pseudonymous citation culture where receipts win; Facebook/IG = visible civic identity and social proof (Bond et al. 2012). Hard rules: bots are **opt-in per community, clearly labeled, emit grounded cards only, never join arguments**; in-platform lookups are ephemeral (no address retention). (c) rejected — it surrenders the trust boundary and deepens platform dependency; (a) wastes where the audience actually is. Everything rides on the public read API (D7/D8). |

**Naming:** **ThinkBallot** (decided). Earlier candidates: BallotBrief, BallotWise, PlainBallot.

---

## 4. Users & key flows

### 4.1 Primary flow
1. Landing page: one-line value prop + an **address input** (+ a "try a sample address" button).
2. User enters a California address → **district resolver** geocodes it to county + congressional +
   state-legislative districts.
3. Results page: a header ("Your ballot for **[Election]**") + a **list of cards** grouped by section
   (Statewide Propositions → Federal & State Races → County/Local Measures).
4. Each **card** is expandable: summary first; tap to reveal for/against, fiscal impact, and **Sources**.
5. Persistent, visible **"How we stay neutral"** link explaining the methodology.

### 4.2 Secondary flows
- **Sample/guided mode:** a preloaded example address so anyone can explore instantly without entering their
  own address.
- **No/'low coverage' path:** address resolves but the app lacks that county's local measures → still show
  statewide + district items with an honest coverage note.

---

## 5. Feature scope

### 5.1 MVP
- Single **target election**: the **November 3, 2026 California general election** (D16). Until its
  official guide content is published, the **2024 general** serves as the development fixture.
- **Address → district** resolution (Census geocoder).
- **Search & filters** over the grounded dataset — election/date, geography (county/district), item type,
  topic/domain, sponsor, civic feature — plus full-text; served by a separate **search service** behind a
  stable interface that later implementations (semantic) slot into unchanged (D14).
- **All statewide propositions** for that election as full structured cards (this is the richest, most
  reliable data — the state voter guide already provides official summary, yes/no meaning, arguments
  for/against, and the Legislative Analyst's fiscal impact).
- **Federal & state legislative races** for the resolved districts as **neutral candidate cards** (equal,
  sourced treatment).
- **County measures for at least one county** (Santa Clara County as the initial target), extensible to more.
- **Structured, cited cards**; clean responsive UI; "How we stay neutral" page.
- **Embed protocol** (D17): OG/oEmbed metadata on `/item/<id>` and ballot pages so a shared link unfurls
  into the card summary (with YES/NO and sources visible) on Discord, Reddit, Facebook, iMessage, etc.
- **Deployed** to a public URL.

### 5.2 Stretch (post-MVP / v2)
- More counties + city/school-board/special-district measures.
- **Multilingual** explanations (Spanish first) — with translation-accuracy guardrails.
- **Save / share "my ballot"** (shareable link or printable summary).
- **Shareable card & ballot images** (D17): auto-generated images per card and per completed ballot review
  ("I did my ballot homework — 5 props, 3 races, all sourced") for Stories/Groups/feeds — the artifact
  signals *work done*, not a one-click badge (avoids the slacktivism substitution effect).
- Extend beyond California — jurisdiction-agnostic core + separately hosted per-entity instances (D15).

### 5.3 Community layer (post-v2, separate service)
Optional **user accounts** unlock interaction; the read-only core never requires them (D10). All community
features live in a **separate community service** (D11; design in §6.8):
- **Comments / conversations** per ballot item — in a visually and structurally distinct "Community
  discussion" zone, post-moderated with viewpoint-neutral rules (D12).
- **Subscriptions & notifications** — election reminders and key dates, email summaries/digests; mobile
  push once the apps exist (§5.4).
- **Grounded AI Q&A** — runtime chat that answers only from the grounded dataset, with citations
  (cite-or-refuse; §6.8).
- **Community-submitted facts** — cited submissions vetted by automated grounding checks + Community-Notes-
  style bridging consensus + human review; published with attribution in the community zone (D13).

### 5.4 Platform horizon (after the community layer)
- **Public read API** — versioned (`/api/v1/…`), documented, free registered API keys, rate-limited (D8),
  making ThinkBallot civic data infrastructure for journalists, researchers, and civic developers.
- **Government intake API** — authenticated endpoints for election officials to push ballots, measures, and
  race data into the ingestion pipeline (D9). Pushed data is staged and reviewed, never published directly.
- **Native mobile apps** (Android and iOS) consuming the same core API as the web app.
- **Semantic search** — build-time embeddings over grounded summaries (consistent with LLM-at-build-time),
  swapped into the MVP search service without changing its interface (D14).

### 5.5 Platform integrations (D17, staged across the tiers above)
Ordered by psychology-product fit and dependency; every item consumes the public read API:
1. **Embed protocol** *(MVP, §5.1)* — links unfurl into cited card summaries everywhere.
2. **Shareable card/ballot images** *(v2, §5.2)* — the social-proof / civic-identity loop.
3. **Discord app** *(with the community layer, §5.3)* — `/ballot <address>` (ephemeral reply, address never
   stored), `/prop <n>` unfurling full cited cards in-channel, opt-in server election reminders, and a
   "ballot party" mode for group walk-throughs. Discord is where 18–24 deliberation actually happens
   (third places; peer-to-peer mobilization).
4. **Reddit presence** *(timed to an election cycle)* — rich embeds; a transparent, moderator-invited bot
   that expands measure mentions into cited summaries; partnerships with state/city subreddit mods for
   election megathreads built on the API. Reddit's citation culture is where cite-or-omit earns public
   credibility; the bot's restraint *is* the marketing.
5. **Facebook/Instagram share surfaces** *(after the shareable-ballot artifact exists)* — reach and
   visible-norm play (friends' civic behavior measurably moves turnout).
6. **Discourse as signal (inbound):** recurring questions from threads and Q&A reveal what confuses
   voters — feeding card improvements and the community layer's vetted facts (D13). Bots never scrape or
   track users; the signal is what communities ask *us*, not surveillance.

---

## 6. Technical design

### 6.1 High-level architecture
```
                 ┌─────────────────────────── build time (offline) ───────────────────────────┐
Official sources │  State Voter Guide · Legislative Analyst fiscal analyses · races/local data  │
   ─────────────▶│         │                                                                    │
                 │         ▼                                                                    │
                 │   Ingestion & normalization  ──▶  Grounded LLM pass  ──▶  Grounding check    │
                 │   (parsers → raw records)         (plain-language +       (every field has   │
                 │                                    for/against, cited)      a source or omit) │
                 │                                         │                                     │
                 │                                         ▼                                     │
                 │                          Ballot dataset (SQLite/JSON, versioned per election) │
                 └──────────────────────────────────────────┬──────────────────────────────────┘
                                                             │
        request time ─────────────────────────────────────▶ │
  User address ─▶ District resolver (Census geocoder) ─▶ Query dataset by scope ─▶ Render cards
  Search query ─▶ Search service (separate; stable interface — FTS5 now, semantic later) ─▶ ranked items

  (post-MVP) Govt intake API ─▶ staging + provenance ─▶ same ingest → grounding → checks pipeline
  (post-MVP) Public read API (/api/v1) ─▶ same district-resolver + dataset query layer as the web app

  (post-v2)  Community service — separate deploy: accounts · comments · facts vetting · notifications · Q&A
             (reads ballot data via the public read API; own storage; never writes the grounded dataset)
```
**Key property:** the LLM runs at **build time**, not per request. Request time is a fast, deterministic
lookup + render over already-grounded, cited data. (Optional on-demand LLM only for the stretch Q&A feature.)

**Second key property (API-first core):** every request-time read goes through a transport-agnostic service
layer (`districts/` + `dataset/access.py`); the server-rendered web UI is merely that layer's *first
client*. The future public read API and the mobile apps consume the same layer, so new clients are thin
additions — never a rewrite.

**Third key property (anonymous core / isolated community plane):** the content service is stateless and
anonymous — no accounts, no PII. All user state (accounts, comments, subscriptions, submissions) lives in
the **separate community service** (§6.8), which consumes ballot data only through the public read API and
can never write into the grounded dataset.

### 6.2 Components (each independently testable)
1. **`ingest/`** — source-specific parsers that produce **raw normalized records** (no AI yet). One module
   per source (`sos_props.py`, `lao_fiscal.py`, `races.py`). Output: JSON conforming to the raw schema.
2. **`grounding/`** — the LLM layer. Takes a raw record + its official source text, returns the
   plain-language + organized fields, **each annotated with the source it came from**. Strict prompt (§6.5).
3. **`checks/`** — the **grounding validator**: asserts every generated field traces to ≥1 source; drops or
   flags anything ungrounded. This is the neutrality/anti-hallucination safety net.
4. **`dataset/`** — the built, versioned ballot dataset (per election) + a small access layer.
5. **`districts/`** — address → county + districts via the Census Geocoder (with a thin interface so the
   provider can be swapped).
6. **`search/`** — the **search service** (MVP): a *separate service* behind a **stable interface**
   (query + filters in → ranked item ids out). Initial implementation: SQLite FTS5 + structured filter
   columns; semantic (build-time embeddings) swaps in later with **no interface change** (D14).
7. **`web/`** — Flask app: routes, templates, card rendering, the neutrality explainer.
8. **`build.py`** — orchestrates ingest → grounding → checks → dataset for a given election config.
9. **`api/`** *(post-MVP)* — the versioned public read API (`/api/v1/…`): a thin JSON wrapper over
   `districts/` + `dataset/` + `search/`; API-key authenticated, rate-limited. Built (internally) when the
   community service needs it; published publicly in §5.4.
10. **`intake/`** *(post-MVP)* — the government push API: authenticated endpoints whose writes land in a
    **staging area** with provenance recorded (the pushing authority becomes a first-class `source`), then
    flow through the normal ingest → grounding → checks pipeline with human review before publish — never
    directly into the served dataset.
11. **Community service** *(post-v2)* — a **separate deployable** (design in §6.8): accounts/auth,
    comments, community-facts vetting, subscriptions/notifications, grounded Q&A. Consumes the read API
    (item 9); owns its own storage; all PII lives here; nothing here writes to the grounded dataset.

### 6.3 Data model (illustrative JSON)
A **ballot item** is either a `measure` or a `race`.

```jsonc
// measure
{
  "id": "ca-2024-prop-6",
  "election": "2024-11-05-ca-general",
  "type": "measure",
  "scope": { "level": "statewide" },              // statewide | county:<fips> | district:<ocd-id>
  "title": "Proposition 6: Forced Labor …",       // official title
  "plain_summary": "…",                            // grounded, cited
  "yes_means": "…",
  "no_means": "…",
  "arguments_for": [ { "text": "…", "source": "src-3" } ],
  "arguments_against": [ { "text": "…", "source": "src-4" } ],
  "fiscal_impact": { "text": "…", "source": "src-2" },
  "sources": [
    { "id": "src-1", "label": "State Official Voter Information Guide", "url": "https://…" },
    { "id": "src-2", "label": "Legislative Analyst's Office", "url": "https://…" }
  ]
}
```
```jsonc
// race
{
  "id": "ca-2024-us-house-17",
  "election": "2024-11-05-ca-general",
  "type": "race",
  "scope": { "level": "district", "ocd_id": "ocd-division/country:us/state:ca/cd:17" },
  "office": "U.S. House of Representatives, District 17",
  "candidates": [
    { "name": "…", "party": "…", "summary": "…", "sources": ["src-9"] }   // equal, neutral, sourced
  ],
  "sources": [ … ]
}
```
**Rule:** every human-readable, generated field (`plain_summary`, `arguments_*`, `fiscal_impact`,
candidate `summary`) **must** reference a source id present in `sources`. The `checks/` validator enforces
this; ungrounded fields are omitted with a visible "not available" note rather than fabricated.

**Search fields (MVP, D14):** ballot items carry structured `sponsors[]` / `opponents[]`, `topics[]`, and
`civic_features[]` fields — populated at build time through the same grounded pipeline — plus a full-text
index (SQLite FTS5); build-time embeddings for semantic search come later (§5.4).

**Community-plane entities** (users, comments, fact submissions + ratings, subscriptions) belong to the
community service's own store (§6.8) — they are never part of this dataset.

### 6.4 Request-time routes (Flask)
- `GET /` — landing + address form (+ sample address).
- `POST /ballot` (or `GET /ballot?address=…`) — resolve district, fetch items, render results.
- `GET /item/<id>` — deep link to a single card (useful for sharing); carries **OG/oEmbed metadata** so it
  unfurls into a cited card summary on chat and social platforms (D17).
- `GET /methodology` — the "How we stay neutral" page.
- `GET /healthz` — trivial health check for the host.
- *(post-MVP)* `GET /api/v1/…` — public read API: elections, ballot lookup by address, item by id;
  API-key authenticated, rate-limited, versioned.
- `GET /search` — filtered + full-text search over the grounded dataset, backed by the search service
  (D14). (`GET /api/v1/search` joins the public API post-MVP.)
- *(post-MVP)* `POST /intake/v1/…` — government push endpoints (partner-authenticated; writes go to
  staging, not the live dataset — see §6.2 item 10).
- *(post-v2)* the **community service exposes its own API** (auth, comments, subscriptions, Q&A) on a
  separate deployment/base URL — not routes of this app (§6.8).

### 6.5 The grounding/neutrality strategy (the core engineering challenge)
This is the heart of the project. Principles:
1. **The model transforms, it does not author.** The LLM is always given the **official source text** and
   instructed to *rewrite/organize only what is present*, never to add outside facts.
2. **Symmetry by construction.** For measures, `arguments_for`/`arguments_against` are drawn from the
   **official ballot arguments** (which are themselves balanced) and rendered with **equal prominence**. For
   races, every candidate gets the **same fields, same length budget, same neutral tone**.
3. **Cite-or-omit.** Each output field must attach a source; the validator drops anything that can't be
   traced. No citation → not shown.
4. **Neutral-language pass.** A lightweight check for loaded/partisan phrasing; flag for review.
5. **Transparency in the UI.** Every card exposes its sources; `/methodology` explains the pipeline in plain
   terms so users can trust it.
> Prompt/config for the grounding pass lives in `grounding/prompts/`. Keep prompts in version control and
> treat them as code (reviewed, tested against sample records).

### 6.6 Tech stack
- **Language/framework:** Python 3.11+, **Flask**.
- **Ingestion:** `requests` + `BeautifulSoup` (and `pdfplumber` if a source is PDF-only).
- **AI layer:** **Claude API** (Anthropic) for the grounding pass. Latest capable model at build time
  (default to the newest Claude; API key via env var, never committed).
- **Storage:** SQLite (or flat JSON) — the dataset is small and read-mostly.
- **District lookup:** **US Census Geocoder** (free, official) for address → geographies; derive
  congressional + state-legislative districts. (Alt/backup: Google Civic *representatives* endpoint, still
  live, for district/official lookup — abstract behind `districts/` so it's swappable.)
- **Frontend:** server-rendered Flask templates + light vanilla JS; responsive CSS (mobile-first). No heavy
  SPA framework needed for MVP.
- **Deployment:** a free tier (Render / PythonAnywhere / Fly.io). Public URL for the live app.
- **Testing:** `pytest`.
- **Search (MVP):** a separate **search service** behind a stable interface; initial implementation SQLite
  FTS5 + structured filter columns (no heavy infra); semantic embeddings (built at build time) swap in
  later with no interface change (D14).
- **Community service (post-v2):** separate deployable (Python is fine; revisit at its kickoff); its own
  database (e.g., Postgres); a transactional email provider (open item, §11); Claude API **at runtime**
  for grounded Q&A only (the sole exception to LLM-at-build-time).

### 6.7 Suggested repository structure (for the fresh repo)
```
thinkballot/
  README.md                 ← short version of this draft + quickstart
  pyproject.toml / requirements.txt
  .env.example              ← ANTHROPIC_API_KEY=…  (never commit real keys)
  build.py                  ← orchestrates ingest → grounding → checks → dataset
  config/
    elections/<election>.yml← which sources/URLs + scope for a target election
  ingest/
    sos_props.py  lao_fiscal.py  races.py
  grounding/
    __init__.py  prompts/
  checks/
    grounding.py  neutrality.py
  districts/
    resolver.py               (Census geocoder client + interface)
  search/                    search service — stable interface; MVP impl: SQLite FTS5 (D14)
  dataset/
    <election>.json|sqlite   (built artifact) + access.py
  web/
    app.py  routes.py  templates/  static/
  api/                       (post-MVP) public read API blueprint (/api/v1)
  intake/                    (post-MVP) govt push endpoints + staging area
  community/                 (post-v2) separate service — own deploy, possibly own repo (§11)
  tests/
    test_districts.py  test_grounding_check.py  test_dataset_schema.py  test_cards.py
  docs/
    methodology.md          ← source of truth for the "How we stay neutral" page
    PROJECT-DRAFT.md          ← this document (founding spec)
```

### 6.8 Community service design (post-v2)
A **separate deployable service** (D11) that owns every logged-in feature. Hard rules:
1. **Physical trust boundary.** Its own storage; nothing in the community service ever writes into the
   grounded ballot dataset. Community content always renders in a visually and structurally distinct zone.
2. **API-first consumer.** It reads ballot data exclusively through the read API (§6.2 item 9) —
   ThinkBallot is its own first API customer. Building the community service *creates* that API
   internally; §5.4 then publishes it (keys, docs, rate limits).
3. **Privacy by design.** Raw addresses are never stored — even for logged-in users, only derived district
   IDs. All PII (email, auth identifiers) lives here, never in the content service.
4. **Comments (D12).** Code of conduct; **post-moderation** — user flagging plus moderator removal for
   abuse, spam, and demonstrable misinformation, never for viewpoint. The *platform's* voice stays
   neutral; users' need not.
5. **Community facts (D13).** Submissions must carry citations → automated grounding/citation checks →
   **bridging vetting** (published only when rated helpful by raters who typically disagree,
   Community-Notes-style) → human review → shown with attribution in the community zone.
6. **Grounded Q&A.** The one deliberate exception to LLM-at-build-time: a runtime, account-gated chat
   grounded on the dataset — answers only from grounded content, every answer cited, and it refuses what
   it cannot ground (**cite-or-refuse**). Generous per-user usage caps from day one (a cost guardrail, not
   a gate); tighten only if costs demand it.

---

## 7. Data sources (concrete)
- **California Secretary of State — Official Voter Information Guide** (statewide propositions: official
  title, "what your vote means," arguments for/against, rebuttals): <https://voterguide.sos.ca.gov/>
- **Legislative Analyst's Office (LAO)** — nonpartisan fiscal analyses of propositions:
  <https://lao.ca.gov/BallotAnalysis>
- **Ballotpedia** — races, candidates, and local measures (respect its terms of use; prefer official
  county sources where feasible): <https://ballotpedia.org/>
- **US Census Geocoder** — address → geographies/districts (free API):
  <https://geocoding.geo.census.gov/geocoder/>
- **County Registrars of Voters** — authoritative local measures (start with **Santa Clara County**):
  <https://vote.santaclaracounty.gov/>
> Prefer **official** sources (SoS, LAO, county registrars) as the primary grounding; use Ballotpedia to
> fill race/local gaps. Record the exact source URL on every field.

---

## 8. Phased build plan
Ordered so there's always a working, shippable slice. Each phase is a natural PR.

1. **Skeleton & sample data.** Flask app renders **hard-coded sample cards** end-to-end (landing → results
   → card detail → methodology). Locks the UX and card layout before any data plumbing.
2. **District resolver.** Address → county + districts via Census geocoder; unit-tested; a `/ballot` page
   that shows *which* items would apply (even if content is stubbed).
3. **Propositions ingestion (the richest slice).** Parse the state voter guide + LAO for the target election
   → raw records → grounding pass → **grounding check** → dataset. Statewide prop cards go fully live.
4. **Races + county measures.** Add district races and Santa Clara County measures.
5. **Search service.** Stand up the search service (stable interface; SQLite FTS5 implementation), index
   the dataset — including the sponsor/topic/civic-feature fields (§6.3) — and add the `/search` UI.
6. **Neutrality hardening + polish.** `/methodology` page, source display on every card, neutral-language
   check, responsive/mobile pass, accessibility basics.
7. **Deploy.** Public URL, seed a good **sample address**, final QA.

**Beyond MVP**, the roadmap tiers map to future phase groups, each getting its own spec → plan cycle
before build: §5.2 (more counties, multilingual, save/share, shareable images) → v2 phases; §5.3
(community service: accounts, comments, notifications, Q&A, community facts) → v3 phases; §5.4 (publishing
the read API, govt intake, mobile apps, semantic search) follows. Platform integrations (§5.5) ship with
their host tiers — the embed protocol is already in the MVP.

---

## 9. Testing & definition of done
- **Unit:** address→district mapping (known addresses → expected districts); dataset schema validation;
  card rendering snapshots; search-service contract tests (queries + filters → expected item ids, pinned
  to the stable interface so future implementations must pass them unchanged).
- **Grounding test (critical):** for every item in the built dataset, assert **every generated field has a
  resolvable source**; fail the build otherwise.
- **Neutrality checklist (manual):** spot-review a sample of cards for balanced for/against and neutral tone.
- **Definition of done (MVP):** a deployed public URL where entering a real California address returns
  correct, cited, neutral cards for the target election's statewide props + resolved district races +
  Santa Clara County measures; working filtered + full-text search; methodology page live.

---

## 10. Risks & mitigations
- **Data variability / fragile scraping** → target a **fixed, known election** and snapshot source content
  at build time; official sources (SoS/LAO) are stable and structured.
- **AI hallucination / bias** → cite-or-omit + grounding validator + symmetric rendering + transparency
  (this risk is *the* design driver, §6.5).
- **Local-coverage gaps** → be honest in-UI ("statewide + your districts covered; local measures for
  supported counties"); expand counties over time.
- **Election timeliness / content availability** → the app is **election-scoped**, targeting the **Nov
  2026 general** (D16); official guide content lands late in the cycle, so development and tests run
  against the 2024 general as a stable fixture; sources are snapshotted at build time, with a documented
  refresh path (`config/elections/`).
- **Public API abuse / overload** *(post-MVP)* → free registered API keys + rate limiting (D8).
- **Spoofed or unauthorized government pushes** *(post-MVP)* → strong partner authentication + an explicit
  partner allowlist; provenance recorded on every pushed record; staging + human review before anything is
  published (D9).
- **Client/API version drift** (web, Android, iOS all on one API) *(post-MVP)* → versioned API contract
  (`/api/v1`); prefer additive changes; deprecation policy before v2 of the API.
- **Moderation load & disputes** *(post-v2)* → separated community zone, code of conduct, viewpoint-neutral
  removal rules, user flagging; staffing/policy is an open item (§11).
- **Vetting gaming / brigading** *(post-v2)* → bridging consensus by design (cross-perspective agreement
  required), rate limits, human review as the final gate (D13).
- **PII & privacy** *(post-v2)* → all PII isolated in the community service; raw addresses never stored;
  the content service stays stateless (§6.8).
- **Email deliverability / spam complaints** *(post-v2)* → reputable transactional provider, double opt-in,
  one-click unsubscribe.
- **Runtime Q&A hallucination** *(post-v2)* → cite-or-refuse: answers restricted to grounded dataset
  content, every answer cited, refusal otherwise (§6.8).
- **Platform dependency & API volatility** (Reddit's 2023 API repricing, Meta's API lockdowns) → no
  platform is a load-bearing wall: embeds/links/images degrade gracefully; bots are enhancements, not the
  product; everything rides on our own read API (D17).
- **Astroturf / partisanship perception for bots** → opt-in per community, clearly labeled as ThinkBallot,
  emit grounded cards only, never argue, never post uninvited; in-platform lookups are ephemeral and
  addresses are never retained (D17).

---

## 11. Open items to finalize (before/at kickoff)
1. **Deployment host** (Render vs PythonAnywhere vs Fly).
2. **County breadth for MVP** (Santa Clara only vs a few Bay Area counties).
3. **Public API key mechanics** (registration flow, quotas, docs hosting) — decide post-MVP, before the
   API ships.
4. **Government partner authentication standard** (e.g., OAuth2 client-credentials vs mTLS) — decide with
   the first government partner.
5. **Mobile technology choice** (native Kotlin/Swift vs cross-platform) — decide when mobile work starts.
6. **Account auth method** (email magic link vs OAuth providers) — decide before community-service work.
7. **Transactional email provider** — decide alongside subscriptions/notifications.
8. **Bridging-vetting algorithm specifics** (rating model, publish thresholds) — decide before community
   facts ship.
9. **Moderation policy & staffing** (code-of-conduct document, moderator workflow).
10. **Community service hosting & repo layout** (same monorepo vs separate repo).

---

## 12. For coding agents starting this project
- **Read this whole document first**, then start at **Phase 1 (§8)** — build the UX skeleton with sample
  data before any ingestion. Keep each component (§6.2) isolated and independently testable.
- **Never fabricate ballot facts.** The entire value proposition is trust: **cite-or-omit** is a hard rule,
  enforced by `checks/grounding.py`. If a field can't be traced to a source, omit it with a visible note.
- **Keep the LLM at build time**, grounded on official source text only; prompts live in
  `grounding/prompts/` and are reviewed like code.
- **Prefer official sources** (state SoS, LAO, county registrars) over aggregators; store the exact source
  URL on every field.
- **Secrets via env** (`ANTHROPIC_API_KEY`), never committed; provide `.env.example`.
- **Neutrality is a feature, not an afterthought** — symmetric treatment, visible sources, and the
  `/methodology` page ship with the MVP.
- **Build API-first (D7):** route all request-time reads through the service layer (`districts/` +
  `dataset/access.py`), never directly from templates/views — the future public API and mobile apps must be
  able to reuse that layer unchanged.
- **Respect the plane boundary (D11):** community/user content never enters the grounded dataset; the
  community service reads ballot data only via the read API and renders its content in a visually
  distinct zone (§6.8). No accounts or PII in the content service, ever.
- **No hard-coded jurisdiction assumptions (D15):** state/county/election specifics live in `config/`,
  not in code — the same codebase must be hostable as a dedicated instance for any entity.
- Match the conventions in the repo, and write tests alongside features (especially the grounding test).

---

_This draft is intended to be copied into the new project repository as its founding spec. Update §11 as
open items are decided; keep the decisions table (§3) as the record of intent._
