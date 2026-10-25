# Contributing to ThinkBallot

Thank you for helping. Please send changes as pull requests to the main repository,
https://github.com/svanihba/thinkballot, so everyone benefits from them.

Before you open a pull request:

1. Run the tests: `.venv/bin/python -m pytest`.
2. Keep the neutrality rules (see `/neutral` in the app): official sources only, official text shown
   word for word, YES before NO in the same layout, and no text that tells anyone how to vote.
3. Any text ThinkBallot itself shows about a measure must pass Bias Buster (`scripts/seed.py` checks it).

By contributing you agree that your contribution is licensed under the GNU AGPL v3 (see `LICENSE`).
If you run a modified version of ThinkBallot for others, the AGPL requires you to offer them its source.
