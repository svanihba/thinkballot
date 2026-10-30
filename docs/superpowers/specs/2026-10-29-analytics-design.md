# Visitor analytics: design

Status: draft for approval, 29 Oct 2026.

## Why

Outreach starts 30 Oct and runs to election day (3 Nov). The owners want to know, from our own data:

- which outreach channels bring visitors (and which of those visitors go on to use the site);
- the funnel: home -> ZIP -> ballot -> measure -> tabs / Ask / share;
- usage density per ZIP code and by time of day;
- interest per measure (views, reads, stars, questions);
- common paths through the site;
- latency and performance, to find what to speed up.

## Goals

1. Log every navigation and interaction event on www.thinkballot.com, each with the visitor's cookie ID and a
   timestamp, to append-only log files on our own server's disk.
2. Keep each event at most 60 days; never anything older than 63 days.
3. Keep the main site's job to logging only. A separate analytics system (built later, not part of this work)
   copies the log files, runs the pipelines that slice and aggregate them by dimension, and shows the results on
   its own site at a separate address. No analytics code beyond logging lives in the main site.

## Non-goals

- No report pages, dashboards, queries, export endpoints or aggregation in thinkballot.com.
- No third-party analytics, tag manager or pixel. No data leaves our server.
- No tracking on the demo/staging site or local copies: only the production copy (`config.IS_PRODUCTION`).
- No fingerprinting, and no link between analytics and accounts (email, username, user id).

## Anti-goals (a failure even if it works)

- Analytics slowing a page, breaking a page, or causing an error a visitor sees.
- Storing what someone typed into Ask, or storing an IP address.
- Tracking a browser that asked not to be tracked.
- The privacy text saying something the site does not do.

## Decisions taken by the owners

| Decision | Ruling |
|---|---|
| Hosting | On our own server, as append-only log files on disk. |
| Separation | The main site only logs (server and client events). Copying, pipelines, aggregation and display belong to a separate analytics system and site. |
| Identifier | The existing site cookie, not a new one. |
| Location | Store the ZIP code as entered (not reduced to county). |
| Do-not-track | Browsers sending Global Privacy Control (`Sec-GPC: 1`) or Do Not Track (`DNT: 1`) are not tracked at all. |
| Reports | None on this site; a separate analytics site later. |
| Retention | 60 days; never above 63 days. |
| Scope | www only. |
| Order | Phase 1 (by 30 Oct midday): page views, source tags, referrer, ZIP, visitor counts, timing. Phase 2 (a day later): element interactions and everything else below. |

## Calls made by the lead (owners can overturn)

- **Reusing the cookie.** The site cookie is Flask's signed session cookie. Today it ends when the browser
  closes and is set only once a page with a form renders. To count returning visitors it becomes a
  persistent cookie lasting 60 days, and every tracked page view ensures it holds a random analytics ID
  (`aid`, 16 random bytes, url-safe). Events store only `aid`, never `session["user"]`. Signing out clears
  the session but keeps `aid`. The ID's creation time is kept in the cookie beside it; after 60 days a new ID
  replaces it, so one ID never lives longer than 60 days even though the cookie is renewed on each visit.
  Side effect: a signed-in user also stays signed in up to 60 days instead of
  until the browser closes (the community is closed today, so this affects no one now).
- **Typed text.** The text of Ask questions is not stored, because the privacy section promises it. The event
  records that a question was asked, for which measure, its length, whether it was a suggested question
  (and which one), and the outcome (prepared / live / refused / error) with latency. Search queries
  are stored (truncated to 100 characters), since they are short interest signals and not covered by that
  promise; the privacy text says so.
- **No IP address.** The existing 24-hour IP hash for rate limits is unchanged and not joined to analytics.
- **Bots.** Page views from obvious bot user agents are stored with `bot = 1` rather than dropped, so they
  can be filtered later. Interaction events come only from the page's script, which most bots do not run.

## What is recorded

Every event is one line of JSON (schema version field `v: 1`) with:

| Field | Notes |
|---|---|
| `ts` | Server UTC time, milliseconds. Also `client_ts` for client events. |
| `aid` | Analytics ID from the cookie. |
| `rid` | Per-page-load id, joining a page view to its timing and interaction events. |
| `type` | Event type (list below). |
| `path` | Path without query string; language prefix kept as a field `lang` (en/es/zh). |
| `props` | Object, per event type; the whole line stays under 4 KB. |
| `device` | phone / tablet / desktop, from viewport width; browser family and OS family from the user agent. |
| `bot` | 0/1. |

Event types (phase in brackets):

- `pageview` [1]: path, measure id when on a measure page, the 5-digit ZIP when the page is a ballot page, referrer host (host only, not full URL), the
  `src` / `utm_source` / `utm_medium` / `utm_campaign` query values (each at most 64 characters), whether it is
  the visit's landing page, viewport size, language.
- `zip_submit` [1]: the extracted 5-digit ZIP and whether it was accepted (nothing else from the box is stored;
  a non-ZIP entry is recorded as rejected with no value).
- `timing` [1]: from the browser's Navigation Timing: time to first byte, DOM ready, load; plus the server's
  own handling time for the page (logged server-side, joined by a per-request id).
- `click` [2]: any element carrying a `data-track` name (tabs, Ask button, suggested questions, stars, share,
  language switch, read-more, links to official sources, ZIP list choices, results). Props: the name, measure id,
  and the element's label where useful.
- `ask` [2]: as described above, never the question text.
- `search` [2]: the query (truncated), number of results, and which result was clicked.
- `scroll` [2]: deepest 25/50/75/100% reached on a page, sent once per threshold.
- `engaged` [2]: time the page was visible, sent when the page is hidden or closed.
- `star`, `read`, `share` [2]: measure id, on/off, share method.
- `error` [2]: JavaScript errors and failed fetches (message and source, truncated), for the performance goal.
- `ai` [1] (server-internal, added 29 Oct at the owner's request): one per AI request attempt, from every process that
  calls the model (the site and the prepared-answer script): purpose (answer / review / translate / translate_check),
  model, provider OpenRouter chose, attempt number, HTTP status or error kind, latency, input tokens, output tokens,
  cached input tokens, cost in USD as reported by OpenRouter, measure id and language when known, and the page-load
  `rid` of the visitor request that caused it (so cost and latency per question can be joined to the `ask` event).
  It never carries `aid`, the prompt or the reply. It is logged even when the visitor sends GPC/DNT, but then
  without `rid`, since it is the site's own operating record, not the visitor's.

## How it works

- **Collection endpoint:** `POST /api/e`, accepting a small JSON batch (at most 20 events, 16 KB). Same-origin
  check as the other JSON calls; no CSRF token needed. Answers 204 quickly; it never surfaces errors to
  the page. The server stamps time, `aid`, device and bot flag; the client cannot set `aid`.
- **Signed event tokens (owner request, 29 Oct):** every tracked page carries a token the server signed:
  `<rid>.<issued unix seconds>.<HMAC-SHA256 of rid|aid|issued with the app's secret key, base64url, 22 chars>`.
  `/api/e` logs a batch only if the token verifies, its `aid` is the session's, and it is under 12 hours old;
  otherwise 204 and nothing logged. The `rid` in every logged event comes from the token, not the batch. Limits
  (shared by both workers, through the existing rate-limit store): 60 batches per token (= 1,200 events per page
  load) and 600 batches per hour per client network (hashed, as for Ask). A browser cannot hold a secret, so this
  does not prove a real person sent the events; it means every event belongs to a page load the server served to
  that cookie, forged IDs are impossible, and one page load or one network can add only a bounded amount.
- **Page views** are written by the server when it renders a page (so they are counted even without
  JavaScript), together with the server's handling time; the browser then sends `timing` and later events.
- **Browser script:** a small addition to `static/app.js`: queues events, flushes every 5 s and on page hide via
  `navigator.sendBeacon`, drops events if the endpoint fails. Fits the existing CSP (`connect-src 'self'`);
  no new third-party origins.
- **GPC/DNT:** the server checks the headers on each request; when either is set it logs nothing and adds no
  `aid`. The script checks `navigator.globalPrivacyControl` / `doNotTrack` and sends nothing.
- **Log files:** directory from `TB_EVENT_LOG_DIR` (default: an `events/` folder beside the other data files). Each worker
  process writes its own file per UTC hour, and starts a new file after 10,000 lines:
  `events-YYYY-MM-DD-HH-<pid>-<seq>.jsonl` (`seq` from 0). Lines are only ever appended (opened with `O_APPEND`,
  one `write` per line, line under 4 KB); a file is never rewritten. A file is complete when its hour ended more
  than 10 minutes ago or a later `seq` exists for the same hour and process; the analytics system copies complete
  files. Files are mode 0640; giving the analytics system read access (a shared group) is part of setting up that
  system, not this work.
- **Compression:** a job run at most every 10 minutes by each worker gzips every complete file (`.jsonl` -> `.jsonl.gz`, written to a
  temporary name, then renamed; the original removed only after the gzip is verified). Measured on a synthetic
  sample: 235 bytes per event raw, 38 bytes gzipped. At 100,000 events a day, 61 days is about 1.4 GB raw or
  0.23 GB compressed. Structure is kept by the `v` schema version and a schema check in the tests.
- **Disk guard:** if free space on the data disk falls below 5 GB, logging pauses (events dropped, warning logged)
  until space returns, so analytics can never fill the disk the site needs.
- **Processes:** the site may run several worker processes, each with several threads, without preloading. Per-process files mean no two
  processes write the same file; a per-process lock serialises its threads. No state is held in memory across
  requests. Visits (sessions) and each visitor's ZIP are worked out later by the pipelines from `aid`, `ts` and the
  ZIP events.
- **Failure:** if a write fails (disk full, permissions), the event is dropped and a warning is logged at most once
  a minute; the page is unaffected.
- **Retention:** the same job deletes event files whose date is more than 60 days ago (deleting a file
  twice is harmless). So no line on the main site is older than 61 days. The event directory is not included in the
  nightly or pre-deploy backups, so no copy outlives the limit (losing it in a disk failure is accepted). Copies
  taken by the analytics system must follow the same rule for anything carrying `aid` (its design; aggregates
  without `aid` may be kept longer if the owners decide so).
- **Only production:** everything is off unless `config.IS_PRODUCTION`, plus a switch `TB_ANALYTICS=0` to turn it
  off (needs a restart).

## Privacy text

The Privacy section (English, Spanish, Chinese) is rewritten before tracking goes live, to say: the cookie also
holds a random visitor ID that lasts 60 days; which pages and buttons are used, with ZIP code, device type and the
referring site, is recorded on ThinkBallot's own server, kept 60 days and shared with no one; what is never stored
(typed questions, IP addresses); search terms are stored; and that browsers sending Global Privacy Control or Do Not
Track are not tracked. One text covering both phases goes live with phase 1 (it never under-states what is
recorded); Spanish and Chinese through the existing translation flow, checked by the second model. The comment in `app.js` that says nothing is sent to the server is corrected (stars and read
ticks still live in the browser; the analytics event that a star was clicked is sent).

## Testing

- Unit tests: GPC/DNT means no row and no `aid`; non-production records nothing; batch and size limits; client
  cannot set `aid`; Ask events never contain question text; retention deletes files dated over 60 days ago;
  concurrent writers from several threads and two processes produce only whole, valid JSON lines.
- Load: 100 events per second for a minute on a laptop with no page slower than before (p95 within 5 ms).
- Browser check on staging with the switch forced on, then on www after deploy: events appear for a full
  journey (home -> ZIP -> ballot -> measure -> Ask -> share).

## Left to the builder

Exact props per event beyond the fields above, the bot pattern list, exact `data-track` names, batching details, and
how the per-request id joins server timing to client timing.
