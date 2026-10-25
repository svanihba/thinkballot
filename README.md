# ThinkBallot

**ThinkBallot turns a 100-page voter guide into a link you can trust: plain English, both sides equally,
straight from the official source.**

California's November 3, 2026 ballot has 14 statewide propositions. The official voter guide explains them
all, but it runs to well over a hundred pages. ThinkBallot gives every proposition one clear card and its own
shareable link, so young voters (and everyone else) can understand what they're voting on and drop a neutral,
sourced link into the group chat or neighborhood thread where opinions form.

Built by Abhinav Shirbhate in Sunnyvale, California.

![A proposition card](docs/screenshot-measure.png)

## What it does

- **Your ballot:** enter an address or ZIP code to see your likely districts and all 14 statewide
  propositions. Star the ones you care about, and track how many you've read until your ballot is ready.
- **One card per proposition:** official summary, what a YES vote means and what a NO vote means side by
  side, the official arguments for and against side by side, supporters and opponents, the fiscal effect,
  and the Legislative Analyst's full analysis. Every field links to the exact official page.
- **Ask:** ask a question about a proposition. Answers come only from its official text, quote it, and are
  checked by **Bias Buster** before you see them. "How should I vote?" always gets the same answer: that's
  your call.
- **Search:** full-text search over the official text, with topic filters.
- **Community:** sign in to discuss a proposition (post-moderated, viewpoint-neutral rules) or submit a
  fact with a source link. Facts are published only after people who lean YES and people who lean NO both
  rate them helpful, and a moderator reviews them. The community zone is visibly separate and can never
  change the official card.

## How it stays neutral

1. **Official sources only:** the California Secretary of State's Official Voter Information Guide and the
   Legislative Analyst's Office.
2. **Their words, not ours:** `scripts/fetch_guide.py` copies each field out of the official page by code.
   No AI writes the cards.
3. **Verified before publishing:** `scripts/seed.py --live` refuses to load the data unless every field
   appears word for word on its live official page (154 of 154 fields pass).
4. **Both sides, equally:** YES always before NO, same layout, same styling, no partisan colours.
5. **Bias Buster** checks every AI answer and every label ThinkBallot writes: quote check (every point must
   quote the official text), number check, loaded-word check, YES/NO balance check, then an AI neutrality
   review whose edits go through the same checks again. If the review can't run, the answer is held back.
6. **Privacy:** only the ZIP code is used for districts; addresses and questions are never stored or logged.

## How it's built

Seven small services in one Python process. They talk to each other only over HTTP, so any of them can move
to its own server later.

| Service | Job |
|---|---|
| `web` | The pages (Flask templates, a little JavaScript) |
| `ballot` | Proposition data from SQLite |
| `geo` | ZIP code to likely districts |
| `search` | Full-text search and topic filters |
| `ask` | Grounded Q&A through OpenRouter |
| `bias` | Bias Buster |
| `community` | Accounts, discussion and community facts, with its own separate database |

```
Browser → web ─┬→ ballot → SQLite (official data, verified)
               ├→ geo, search
               ├→ ask → ballot, OpenRouter, bias
               └→ community → its own SQLite, bias
```

## Run it

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "OPENROUTER_API_KEY=your-key" > .env      # for Ask; use TB_AI_PROVIDER=stub to run without AI
.venv/bin/python scripts/fetch_guide.py         # copy the propositions from the official guide
.venv/bin/python scripts/seed.py --live         # verify every field, then load it
.venv/bin/python run.py                          # http://127.0.0.1:8000
.venv/bin/python -m pytest                       # tests
```

To make an account a moderator: `.venv/bin/python scripts/make_moderator.py <email>`.

## Data sources

- California Secretary of State, Official Voter Information Guide, November 3, 2026:
  https://voterguide.sos.ca.gov/propositions/
- Analyses by the Legislative Analyst's Office, published in the same guide.
- Saved copies of every source page used are in `data/sources/2026-11-03/`.

## What I learned

*(Abhinav: rewrite this in your own words.)*

## What's next

- County, city and school district measures, starting with Santa Clara County.
- Candidate races with equal, sourced candidate cards.
- Exact districts from an official address lookup instead of ZIP codes.
- Email verification and notifications for starred propositions.
- More languages: the official guide is published in ten.

## License

GNU Affero General Public License v3. Copyright © 2026 Abhinav Shirbhate. See `LICENSE` and `NOTICE`;
contributions are welcome through pull requests (see `CONTRIBUTING.md`).
