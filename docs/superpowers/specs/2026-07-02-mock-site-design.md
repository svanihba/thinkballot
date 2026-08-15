# ThinkBallot Mock Site — Design

**Goal:** a clickable, static mock in `mocks/` that demonstrates the *whole* ThinkBallot product
(per `docs/PROJECT-DRAFT.md`) with placeholder data — used to lock UX and communicate the vision
before any real code is written. It precedes and informs Phase 1 (§8).

## Decisions

- **Static HTML/CSS/vanilla JS.** No server, no build step, no dependencies. Open
  `mocks/index.html` directly (or via any static file server) and click through every flow.
- **All four product tiers are mocked:** anonymous core (MVP), community layer, platform
  surfaces (API docs, government intake), and a hosted-instance demo (D15).
- **Fictional placeholder data,** realistic in shape but invented (fictional propositions,
  candidates, measures) framed as the Nov 3, 2026 CA general election. Every page carries a
  persistent "MOCK — placeholder data, not real ballot information" banner. This is a hard
  requirement: the real product's value is trust, so the mock must be unmistakably fake.
- **Mock login is a localStorage flag** toggled by a fake sign-in; it unlocks the community
  features (comments, Q&A, subscriptions) to demonstrate the D10 account model: read
  everything anonymous, interact logged-in.

## Structure

```
mocks/
  README.md          — what this is, how to open it, page map, what is/isn't real
  index.html         — landing: value prop, address input, sample-address button
  ballot.html        — personalized ballot: grouped cards (props → races → county measures);
                       low-coverage variant reachable via a second sample address
  item-measure.html  — measure card detail: summary, YES/NO, for/against, fiscal, sources;
                       community discussion zone (visually separated; login-gated posting)
  item-race.html     — race card detail: equal candidate cards, sources; community zone
  search.html        — search + filters (election, geography, type, topic, sponsor,
                       civic feature) working client-side over the mock dataset
  methodology.html   — "How we stay neutral" page incl. the pipeline explanation
  account.html       — mock sign-in + subscriptions/notification preferences (login-gated)
  qa.html            — grounded AI Q&A chat with canned, citation-bearing answers and a
                       cite-or-refuse example (login-gated)
  api.html           — public read API docs mock: endpoints, sample responses, key signup
  gov.html           — government intake portal mock: push → staging → review pipeline status
  instance.html      — Santa Clara County-branded instance demo (D15 white-label story)
  assets/
    style.css        — one shared stylesheet, responsive/mobile-first
    data.js          — the placeholder dataset (measures, races, sources) as a JS object
    app.js           — shared behavior: mock-login state, card expansion, search filtering,
                       banner injection
```

## Clickable flows demonstrated

1. **Voter flow:** landing → enter/sample address → ballot → expand card → detail → sources.
2. **Low-coverage flow:** second sample address → ballot with honest coverage note.
3. **Search flow:** query + filter chips → results → card detail.
4. **Community flow:** logged-out (read comments, locked composer) → mock sign-in →
   comment composer, vetting states on community facts (proposed / vetted / rejected).
5. **Q&A flow:** ask canned questions → cited answers; off-dataset question → refusal.
6. **Platform flows:** API docs with sample request/response; gov portal showing a pushed
   measure sitting in staging with provenance and review status.
7. **Instance flow:** county-branded variant of landing/ballot proving the config-driven story.

## Non-goals

No real data, no real AI calls, no persistence beyond localStorage, no framework, and no
attempt to be pixel-final — it locks flows and information architecture, not final branding.

## Testing

Manual click-through of the seven flows above; every internal link resolves; pages render
sensibly at mobile width (390px) and desktop; mock banner present on every page.
