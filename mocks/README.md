# ThinkBallot — Clickable Mock

A **static, dependency-free mock** of the whole ThinkBallot product, per `docs/PROJECT-DRAFT.md` and
`docs/superpowers/specs/2026-07-02-mock-site-design.md`. It exists to lock UX and communicate the vision
before real code is written. **Every proposition, measure, candidate, argument, and number is fictional**
— hence the striped MOCK ribbon on every page.

## How to open

Open `index.html` directly in a browser, or serve the directory:

```
cd mocks && python3 -m http.server 8123
# → http://localhost:8123
```

No build step, no dependencies. (Fonts load from Google Fonts; everything else is local.)

## Page map & flows

| Page | Shows |
|---|---|
| `index.html` | Landing: value prop, address form, sample addresses, product pillars |
| `ballot.html?addr=cupertino` | Full personalized ballot (props → races → county measures) |
| `ballot.html?addr=eureka` | The honest **low-coverage** state (no county measures, no race cards) |
| `item-measure.html?id=prop-61` | Measure card: summary, YES/NO, args, fiscal, sources + community zone |
| `item-race.html?id=us-house-17` | Race card: equal candidate treatment + community zone |
| `search.html` | Working client-side search: full text + filter chips (type/geo/topic/civic feature) |
| `methodology.html` | "How we stay neutral": pipeline diagram + the rules |
| `account.html` | Mock sign-in (localStorage) + subscriptions/notification preferences |
| `qa.html` | Grounded Q&A: canned cited answers + the cite-or-refuse path (signed-in only) |
| `api.html` | Public read API docs mock + free-key signup |
| `gov.html` | Government intake portal: push → staging → review pipeline, submission statuses |
| `instance.html` | Santa Clara-branded **hosted instance** demo (D15 white-label story) |

## Suggested click-through

1. Landing → sample address → ballot → expand Prop 61 → sources.
2. Try the Eureka sample address → see the honest coverage note.
3. Search "housing", toggle the *tax* chip.
4. Open a measure while signed out → community zone is readable but locked → sign in via
   `account.html` → composer and fact-submission unlock; note vetting statuses on community facts.
5. Ask a suggested question in Q&A → cited answer; ask anything else → refusal.
6. Visit `api.html`, `gov.html`, `instance.html` for the platform story.

## What this is not

No real data, no real AI, no persistence beyond the mock-login flag, no framework, not final branding.
The real product's plans live in `docs/PROJECT-DRAFT.md`.
