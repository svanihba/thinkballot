# Visitor Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** www.thinkballot.com appends every navigation and interaction event, with the visitor's cookie ID and a
timestamp, to hourly (or 10,000-line) gzip-rotated JSON-lines files on its own disk; nothing else.

**Architecture:** A small, framework-free `thinkballot/eventlog.py` owns files (append, per-process hourly files
of at most 10,000 lines, gzip of complete files, 60-day deletion, disk guard). `thinkballot/services/web/analytics.py` wires it into Flask
(visitor ID in the existing session cookie, GPC/DNT, server-side page views, `POST /api/e` for browser events).
`static/app.js` gets a small queue that sends browser events. Phase 1 = Tasks 1–4, phase 2 = Tasks 5–6.

**Tech Stack:** Python 3 stdlib (`os`, `gzip`, `json`, `shutil`, `threading`), Flask session, vanilla JS
(`fetch`/`sendBeacon`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-29-analytics-design.md`

## Global Constraints

- Logging only on the production copy: `config.IS_PRODUCTION` and `config.ANALYTICS == "1"`, or `config.ANALYTICS == "force"` (local checks only); `TB_ANALYTICS=0` turns it off.
- Browsers sending `Sec-GPC: 1` or `DNT: 1` (server) / `navigator.globalPrivacyControl` or `navigator.doNotTrack == "1"` (client): no event, no visitor ID.
- Never stored: Ask question text, IP address, the user's account id/username/email, anything from the ZIP box except the extracted 5-digit ZIP.
- Search query stored truncated to 100 characters; `src`/`utm_*` values to 64 characters; referrer as host only.
- Every line is one JSON object, `v: 1`, under 4096 bytes including newline; lines over the limit are dropped.
- Files: `events-YYYY-MM-DD-HH-<pid>-<seq>.jsonl` (UTC date and hour; new `seq` after 10,000 lines), mode 0640, directory mode 0750; complete files become `.jsonl.gz`.
- Retention: files dated more than 60 days before today (UTC) are deleted; nothing older than 63 days ever.
- Disk guard: below 5 GB free on the log directory's filesystem, events are dropped.
- Analytics never raises into a request, never changes a page's status, never delays a page by more than a file append.
- Visitor ID `aid` = `secrets.token_urlsafe(16)`, its creation time `aid_t` (epoch seconds) beside it in the session; replaced after 60 days; session cookie lasts 60 days.
- The site's `/api/health` does not touch analytics.
- No AI attribution in files or commits; no hosting/server details in the public repo.

## Review Focus

- A page that is publicly cached (`/api/zips`, static files, robots, sitemap) must never get a `Set-Cookie` with a visitor ID — test in Task 2.
- Two worker processes and many threads writing the same day must produce only whole JSON lines — test in Task 1.
- A crash mid-gzip (stale `.gz.tmp`) or both workers gzipping the same file at once must lose no data and not loop — test in Task 1.
- A request arriving just before the hour that writes just after it must not land in a file being gzipped — handled by the 10-minute grace in Task 1, tested there.
- A malformed or hostile browser batch (wrong types, huge strings, unknown event types, client-sent `aid`/`ts`) is cleaned or dropped, never stored as sent — test in Task 2.

---

### Task 1: Event log files (`thinkballot/eventlog.py`)

**Files:**
- Create: `thinkballot/eventlog.py`
- Test: `tests/test_eventlog.py`

**Interfaces:**
- Produces:
  - `class EventLog(directory: pathlib.Path, min_free_bytes: int = 5 * 10**9, keep_days: int = 60, max_lines: int = 10_000)`
  - `EventLog.write(event: dict, now: float | None = None) -> bool` — adds `v: 1` if absent, serialises compactly (`separators=(",", ":")`, `ensure_ascii=False`), appends one line to `events-<UTC YYYY-MM-DD-HH of now>-<os.getpid()>-<seq>.jsonl` (the instance counts lines written to its current file; at `max_lines` it moves to `seq + 1`; a new hour starts at `seq` 0; a new instance starts after the highest existing `seq` for its pid and hour) with a single `os.write` on an `O_WRONLY|O_APPEND|O_CREAT` fd (mode 0o640), under a per-instance `threading.Lock`. Returns False (no raise) when: line ≥ 4096 bytes, disk guard tripped, or any `OSError`. Creates the directory (0o750) on first use. Runs `maintain(now)` at most once per 10 minutes per instance (first call included), after the write, catching all exceptions.
  - `EventLog.maintain(now: float | None = None) -> None` — (1) delete `events-*.jsonl` and `events-*.jsonl.gz` whose date is older than `today - keep_days`; (2) for each `.jsonl` that is complete — its hour ended more than 10 minutes before `now`, or a higher `seq` exists for the same hour and pid — and has no `.jsonl.gz`: create `<name>.gz.tmp` with `O_CREAT|O_EXCL` (skip on `FileExistsError` unless the tmp is older than 1 hour, then remove it and skip this round), gzip into it, re-read and compare decompressed bytes, `os.replace` to `.jsonl.gz`, then unlink the `.jsonl`.
  - `EventLog.free_ok() -> bool` — `shutil.disk_usage(directory).free >= min_free_bytes`, result cached 60 s.
  - `get_log(directory: pathlib.Path) -> EventLog` — one instance per directory per process (module dict + lock).
  - Warnings via `logging.getLogger("thinkballot.eventlog")`, at most once per minute per kind ("disk low", "write failed").

- [ ] **Step 1: Write the failing tests** in `tests/test_eventlog.py` (use `tmp_path`, fixed `now` values):
  - `test_write_appends_one_json_line_per_event`: two writes → file `events-2026-10-30-14-<pid>-0.jsonl` has 2 lines, each `json.loads` with `v == 1` and the given fields, non-ASCII (`"é"`, `"中"`) kept.
  - `test_file_name_uses_utc_hour`: `now` = 2026-10-31 06:30 UTC writes to `events-2026-10-31-06-<pid>-0.jsonl`; 07:00 starts `…-07-<pid>-0.jsonl`.
  - `test_new_file_after_max_lines`: `max_lines=3`, 7 writes in one hour → seq 0, 1, 2 with 3, 3, 1 lines.
  - `test_oversize_line_is_dropped`: event with a 5000-char value → `write` returns False, no file content.
  - `test_disk_guard_drops_events`: `EventLog(tmp_path, min_free_bytes=10**18).write(...)` is False and writes nothing.
  - `test_write_never_raises_on_unwritable_dir`: directory path is an existing *file* → returns False.
  - `test_threads_and_processes_write_whole_lines`: 2 `multiprocessing` processes × 8 threads × 500 writes of ~1 KB events into one directory → every line in every file parses; total line count 8000.
  - `test_maintain_gzips_complete_files_only`: files for hours 13 and 14 of 2026-10-30; `now` = 14:05 UTC → nothing gzipped (grace); `now` = 14:11 → hour 13 becomes `.jsonl.gz` whose decompressed content equals the original, `.jsonl` gone, hour 14 untouched; with `max_lines=3`, a seq-0 file of the current hour is gzipped once seq 1 exists, seq 1 untouched.
  - `test_maintain_skips_fresh_tmp_and_clears_stale_tmp`: a `.gz.tmp` with mtime now → file left as `.jsonl`; mtime 2 h ago → tmp removed, `.jsonl` still present; next `maintain` gzips it.
  - `test_retention_deletes_files_older_than_60_days`: files dated today-61 (`.jsonl.gz`), today-60, today-1 → only today-61 deleted.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_eventlog.py -q` — expect failures (module missing).
- [ ] **Step 3: Implement** `thinkballot/eventlog.py` per the Interfaces block. Module docstring in the style of the other modules (one paragraph on what the files are and why they are append-only).
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_eventlog.py -q` — all pass; run it 5 times to show the concurrency test is stable.
- [ ] **Step 5: Commit** `git add thinkballot/eventlog.py tests/test_eventlog.py && git commit -m "Event log: hourly append-only JSON-lines files per process (new file after 10,000 lines), gzip of complete files, 60-day deletion, disk guard"`

### Task 2: Server wiring (visitor ID, page views, ZIP, `/api/e`)

**Files:**
- Modify: `thinkballot/config.py` (add `ANALYTICS`, `EVENT_LOG_DIR`, `SESSION_DAYS`)
- Create: `thinkballot/services/web/analytics.py`
- Modify: `thinkballot/services/web/app.py` (call `init_analytics(app)`; `ballot_page` hands the ZIP result to analytics; `signout` keeps the visitor ID)
- Modify: `thinkballot/services/web/templates/base.html` (body gets `data-et` = the signed token when tracking)
- Test: `tests/test_analytics.py`

**Interfaces:**
- Consumes: `get_log(dir).write(event)` from Task 1.
- Produces:
  - config: `ANALYTICS = _env("TB_ANALYTICS", "1")` (`"0"`, `"1"`, `"force"`); `EVENT_LOG_DIR = Path(_env("TB_EVENT_LOG_DIR", str(RATE_DB_PATH.parent / "events")))`; `SESSION_DAYS = 60`.
  - `analytics.tracking() -> bool` — per request (cached on `g`): on per Global Constraints and no GPC/DNT header.
  - `analytics.log(type_: str, props: dict | None = None) -> None` — server-side event with the common fields (`ts` ms, `aid`, `rid`, `type`, `path`, `lang`, `browser`, `os`, `bot`, `props`); no-op when not tracking or no `aid`.
  - `analytics.note_zip(zip_code: str | None, accepted: bool) -> None` — logs `zip_submit` and stores the ZIP on `g` for this request's page view.
  - `analytics.init_analytics(app) -> None` — registers: `app.permanent_session_lifetime = timedelta(days=config.SESSION_DAYS)`; `before_request` that, for GET requests to `PAGE_ENDPOINTS = {"landing", "ballot_page", "measure_page", "search_page", "ask_page", "neutral", "about"}` and POST `ballot_page`, ensures `session["aid"]`/`session["aid_t"]` (new when missing or older than 60 days), sets `session.permanent = True`, sets `g.rid = secrets.token_urlsafe(8)` and `g.t0`; `after_request` that logs `pageview` for those endpoints with status 200 (props: `measure` from view args, `zip` from `note_zip`, `ref` = referrer host if not our own host, `src`, `utm_source`, `utm_medium`, `utm_campaign`, `server_ms`); route `POST /api/e`; a context processor giving templates `analytics_token` (None when not tracking).
  - `analytics.sign_token(rid: str, aid: str, issued: int) -> str` and `analytics.verify_token(token: str, aid: str, now: int) -> str | None` (returns the rid): format `<rid>.<issued>.<22-char base64url HMAC-SHA256(config.SECRET_KEY, f"{rid}|{aid}|{issued}")>`, valid for 12 hours, `hmac.compare_digest`.
  - `POST /api/e`: JSON `{"t": token, "events": [{"type": str, "ts": int, "props": dict}]}`, ≤ 20 events, body ≤ 16 KB, else 400; no `aid` in session, bad/expired token, or over limits (`ratelimit.allow("events", "t:" + rid, [(60, 43200)])`, `ratelimit.allow("events", ratelimit.client_key(request.remote_addr), [(600, 3600)])`) → 204 and nothing logged. Event `rid` comes from the token. Each event passes `clean_client_event(raw) -> dict | None`: type must be in `CLIENT_EVENTS` (dict type → allowed prop names → `int`/`bool`/`str` with max length); unknown props dropped; strings truncated; client `ts` kept as `client_ts`; server sets everything else. Always 204.
  - `CLIENT_EVENTS` phase 1: `timing` {`ttfb`,`dom`,`load`: int; `vw`,`vh`: int}. (Task 5 adds the phase-2 types.)
  - Device: `browser`/`os` families from the User-Agent by a small ordered pattern list; `bot = 1` when the UA matches `bot|crawl|spider|slurp|preview|monitor|curl|python-requests|headless` (case-insensitive) or is empty.
- [ ] **Step 1: Write the failing tests** in `tests/test_analytics.py`, using the `server` fixture plus a fixture that sets `config.ANALYTICS = "force"` and `config.EVENT_LOG_DIR = tmp_path`, restoring both after; helper `events()` reads all lines in the directory:
  - `test_page_view_is_logged_with_cookie_id`: GET `/prop/prop-a?src=ig&utm_campaign=launch` with a `requests.Session` → one `pageview` with `aid` (22 chars), `rid`, `props.measure == "prop-a"`, `props.src == "ig"`, `props.server_ms` int; a second page in the same session has the same `aid`.
  - `test_session_cookie_lasts_60_days`: the `Set-Cookie` for `session` has `Expires` ~60 days ahead.
  - `test_zip_is_logged_but_nothing_else_from_the_box`: POST `/ballot` with `zip="94087"` → `zip_submit` `{zip:"94087", accepted:true}` and the `pageview` has `props.zip == "94087"`; POST with `zip="1 Main St 94087"` logs `zip: "94087"` and no line contains `"Main St"`; POST `zip="hello"` logs `zip_submit` with `zip` null, `accepted: false`.
  - `test_gpc_and_dnt_mean_nothing_logged_and_no_id`: GET `/` with `Sec-GPC: 1`, then with `DNT: 1` → no lines; response has no `aid` in the session (decode with the app's serializer) — and `POST /api/e` from that client logs nothing.
  - `test_not_production_logs_nothing`: `config.ANALYTICS = "1"` with the test server (not production) → no lines.
  - `test_public_cached_responses_set_no_cookie`: fresh client GET `/api/zips`, `/robots.txt`, `/sitemap.xml`, `/static/app.js` → no `Set-Cookie`.
  - `test_client_events_are_cleaned`: after a page view, POST `/api/e` with: a valid `timing`; an unknown type; a `timing` with an extra prop `aid:"x"` and a 10 000-char string prop; 21 events → the 21-event batch is 400 and logs nothing; for the valid batch, only known types/props are stored, `aid` is the session's, never `"x"`.
  - `test_api_e_without_page_view_logs_nothing`: fresh client POST `/api/e` → 204, no lines.
  - `test_event_token_must_verify`: a token with a changed rid, a token signed for another `aid`, a token issued 13 h ago, and a missing token → 204 and nothing logged; the page's own token logs.
  - `test_event_batches_capped_per_page_load`: 61 batches with one token → the 61st logs nothing.
  - `test_signout_keeps_visitor_id`: sign in (existing test helpers in `test_community.py`), sign out, next page view has the same `aid`.
  - `test_visitor_id_renewed_after_60_days`: a session with `aid_t` 61 days ago gets a new `aid` on the next page.
  - `test_logging_failure_does_not_break_pages`: `config.EVENT_LOG_DIR` pointed at a file → pages still 200.
  - `test_events_lines_follow_schema`: every line in the run has `v == 1`, `ts` int, `type` str, `aid` str, `props` dict, and no key named `question`, `ip`, `user`, `email`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_analytics.py -q` — fails.
- [ ] **Step 3: Implement** config, `analytics.py`, the `app.py` changes (`ballot_page` calls `analytics.note_zip(geo-extracted zip or None, place found)` — use `extract_zip` semantics: the 5-digit ZIP the geo service returned in `place["zip"]`; `signout` saves `aid`/`aid_t`, clears, restores) and `base.html` (`{% if analytics_token %} data-et="{{ analytics_token }}"{% endif %}` on `<body>`).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` (whole suite) — all pass, including `test_no_language_cookie`.
- [ ] **Step 5: Commit** `git commit -m "Analytics: visitor ID in the site cookie (60 days), page views, ZIP and browser events logged on www only; nothing for GPC/DNT"`

### Task 2b: AI call events (owner request, 29 Oct)

**Files:**
- Modify: `thinkballot/eventlog.py` (add `enabled() -> bool`, `log_event(event: dict) -> bool`, `current_rid: contextvars.ContextVar[str | None]`)
- Modify: `thinkballot/ai.py` (`chat_json(..., purpose: str | None = None, meta: dict | None = None)`; request `"usage": {"include": True}`; one `ai` event per attempt)
- Modify: `thinkballot/servicekit.py` (ServiceClient sends `X-TB-Rid` from `current_rid`; `make_service` sets `current_rid` from that header)
- Modify: callers in `services/ask/app.py` (purpose `answer`), `services/ask/translate.py` (`translate`, `translate_check`), `services/bias/engine.py` (`review`), passing `meta={"measure": ..., "lang": ...}` where known
- Modify: `services/web/analytics.py` (sets `current_rid` only when the visitor is tracked)
- Test: `tests/test_analytics.py`

**Interfaces:**
- `eventlog.enabled()`: `config.ANALYTICS == "force"` or (`config.ANALYTICS == "1"` and `config.IS_PRODUCTION`). Task 2's `tracking()` uses it.
- `eventlog.log_event(event)`: no-op False when not enabled; else stamps `ts` (ms) if missing and writes to `get_log(config.EVENT_LOG_DIR)`.
- `ai` event fields: `type:"ai"`, `purpose`, `model`, `provider` (response `provider`), `attempt`, `status` (int HTTP or error class name), `ms`, `in_tok`, `out_tok`, `cached_tok` (`usage.prompt_tokens_details.cached_tokens`), `cost` (`usage.cost`, float USD), `measure`, `lang`, `rid` (from `current_rid`, may be null). Stub provider logs nothing.
- [ ] **Step 1: Failing tests:** `test_ai_event_per_attempt` (monkeypatch `ai._post` to return a fake 200 with `usage` `{prompt_tokens: 1200, completion_tokens: 300, cost: 0.0042, prompt_tokens_details: {cached_tokens: 1000}}` and `provider: "X"`, `config.AI_PROVIDER="openrouter"`, a dummy key, `config.ANALYTICS="force"` → one `ai` line with those numbers, `purpose`, no `aid`, no prompt text); `test_ai_event_on_error_status` (fake 503 then 200 → two lines, statuses 503 and 200); `test_ai_event_carries_rid_of_tracked_visitor` (typed question through the test server with tracking forced and the stub replaced by the fake `_post` → `ai` lines' `rid` equals the `ask` page view's `rid`); `test_ai_event_has_no_rid_for_gpc_visitor`.
- [ ] **Step 2: Run** — fail. **Step 3: Implement.** **Step 4: Run** whole suite — pass.
- [ ] **Step 5: Commit** `git commit -m "Log each AI request: purpose, model, provider, latency, tokens and cost (no prompts, no visitor ID)"`

### Task 3: Browser queue (phase 1), privacy text, comment fix

**Files:**
- Modify: `thinkballot/services/web/static/app.js`
- Modify: `thinkballot/services/web/templates/neutral.html` (Privacy section)
- Modify: `thinkballot/services/web/catalogs/es.json`, `zh.json` (inside `"strings"`)
- Test: `tests/test_i18n.py` (existing catalog tests cover the new strings), `tests/test_analytics.py`

**Interfaces:**
- Consumes: body `data-et` (Task 2), `POST {PREFIX}/api/e` with `{"t": data-et, "events": [...]}`.
- Produces (JS): `track(type, props)` — no-op unless `document.body.dataset.et` and not GPC/DNT; queues `{type, ts: Date.now(), props}`; flushes when 20 queued, every 5 s, and on `pagehide`/`visibilitychange` (hidden) with `navigator.sendBeacon(PREFIX + "/api/e", new Blob([json], {type: "application/json"}))`, otherwise `fetch` with `keepalive: true`; failures ignored. On `load`, `track("timing", {ttfb, dom, load, vw, vh})` from `performance.getEntriesByType("navigation")[0]` (rounded ms).
- [ ] **Step 1: Write the failing test** `test_privacy_text_describes_analytics` in `tests/test_analytics.py`: `/neutral` contains "60 days", "Global Privacy Control" and "typed questions"; `/es/neutral` and `/zh/neutral` render the translated section (no English fallback note).
- [ ] **Step 2: Run** it — fails.
- [ ] **Step 3: Write the English Privacy text** (replace the current paragraph; keep facts already there):

  "The site sets one cookie. It protects the site's forms, keeps you signed in if you sign in, and holds a random visitor number that is replaced every 60 days. With that number, ThinkBallot records on its own server which pages you open and which buttons and links you use, with the time, the ZIP code you enter, your device type, browser, the website that sent you and any campaign tag in the link. Search terms are recorded; typed questions are not. These records are kept for 60 days and shared with no one; they are never linked to an account. If your browser sends Global Privacy Control or Do Not Track, nothing is recorded and no visitor number is set. Stars and read ticks stay in your browser. An account stores your email address, your username and a one-way hash of your password. To limit how many questions one visitor can ask, the site keeps a one-way hash of the visitor's IP address for 24 hours; the address itself is not stored. When you type a question, the question and the measure's official text are sent to an AI provider (OpenRouter, which passes them to a model host) to write the answer. Page fonts are loaded from Google Fonts, which receives your IP address when the page loads."

  Spanish and Chinese: draft with `config.TRANSLATE_MODEL` and review with `config.TRANSLATE_CHECK_MODEL` through `thinkballot.ai` from a scratch script (not committed; key read in-process); put the reviewed text into the catalogs.
- [ ] **Step 4: Implement** `track` and timing in `app.js`; fix the header comment to: "Stars and "read" ticks live only in this browser (localStorage). On www, page and button use is sent to ThinkBallot's own server (see Privacy on the methodology page), unless the browser sends Global Privacy Control or Do Not Track."
- [ ] **Step 5: Run** `.venv/bin/pytest -q` — all pass. Local browser check with `TB_ANALYTICS=force`: open home → ballot (94087) → a measure; the event directory shows `pageview`, `zip_submit`, `timing` lines with one `aid`; with GPC on (Chrome flag or header override) nothing appears.
- [ ] **Step 6: Commit** `git commit -m "Browser events queue (timing); privacy text describes visitor analytics (es and zh too)"`

### Task 4: Review and deploy phase 1

- [ ] **Step 1:** Independent review of Tasks 1–3 (fresh reviewer, given the spec and this plan, not the implementer's summary); fix; scoped re-review.
- [ ] **Step 2:** Package and deploy per the private ops runbook (staging, then the same tarball to production), health checks before and after, registry entry. Staging must log nothing (check its data directory has no `events/`).
- [ ] **Step 3:** On www, walk home → ZIP → ballot → measure in the browser with `?src=test`; confirm the lines on the server (as the service account) and that a GPC browser adds none. Then delete those test lines' file only if it holds nothing else (or leave them; they carry `src=test`).
- [ ] **Step 4:** Update the ops handoff with: the event directory, file naming, retention, and that analytics-system read access is a future sitting item.

### Task 5: Phase 2 events (revised 30 Oct: every control, not only tagged ones)

Owner ruling (30 Oct): clicks on all visual controls — buttons, links, dropdowns, tabs, expandable sections,
checkboxes — are logged automatically; `data-track` only gives stable names to the important ones.

**Files:** `services/web/analytics.py` (CLIENT_EVENTS, server `ask`/`search` events), `services/web/app.py`
(`api_ask`, `search_page`), `static/app.js`, templates (`data-track`, `data-rank`), `tests/test_analytics.py`, a JS
harness test in `tests/test_analytics.py` (Node, like the Ask harness).

**Interfaces:**
- Browser `click` (capture-phase listener on `document`) for the closest `a, button, summary, select, label,
  input[type=checkbox], input[type=radio], [role=button], [role=tab], [data-track]` of the target; text inputs and
  textareas are never logged. Props: `name` (≤40: `data-track`, else id, else first class, else tag), `kind` (≤16: tag
  or input type), `label` (≤80: `data-track-label`, `aria-label`, or trimmed text; never an input's value), `measure`
  (≤40: closest `[data-measure]`, else `/prop/<id>` in the href, else the page's), `href` (≤120: same-site path
  without query and language prefix, or the host only for other sites), `rank` (int ≤1000, from `data-rank` or
  `data-index`), `on` (bool: checkbox state or `aria-pressed` after the click, `open` for a summary).
- Browser `select` on `change` of a `<select>`: `name`, `value` (≤80, the option value), `label` (≤80, option text), `measure`.
- `scroll` {`depth` ∈ {25, 50, 75, 100}} once per threshold per page; `engaged` {`ms` int ≤ 86,400,000} visible time,
  sent when hidden; `error` {`message` ≤200, `source` ≤120, `line` int ≤10^7}, at most 5 per page.
- Server `ask` (from `api_ask`, every return path): `measure`, `suggested` (int|null), `length` (typed question
  length, 0 for suggested), `outcome` (`prepared`/`answered`/`refused`/`held`/`error`/`limited`/`bad_request`),
  `status` (HTTP), `server_ms`, `translated` (bool), `verdict` (Bias Buster verdict or null). Never the text.
- Server `search` (from `search_page`): `q` (≤100), `topic` (≤40), `results` (int).
- `data-track` names: `zip-submit`, `zip-sample`, `ask-submit`, `suggest`, `star`, `share`, `measure-select`,
  `local-more`, `analysis-more`, `lang-<code>`, `search-result` (+ `data-rank`).
- [ ] Tests first: server-side cleaning of every new type (valid/invalid props; `scroll` depth 33 dropped);
  `test_ask_event_never_has_question_text`; `test_suggested_ask_event`; `test_ask_event_on_rate_limit`;
  `test_search_event_truncates_query`; `test_track_names_present`; Node harness: a click on a button, a link to
  another site, a select change and a checkbox produce the expected queued events; typing in a text box queues nothing.
- [ ] Implement; whole suite; local browser journey; commit.

### Task 6: Review and deploy phase 2

- [ ] **Step 1:** Independent review of Task 5; fix; scoped re-review.
- [ ] **Step 2:** Deploy as in Task 4 Step 2.
- [ ] **Step 3:** Repeat the www journey including Ask (suggested and typed), search, star, share; confirm lines; confirm the gzip of the previous day's files after 00:10 UTC.
