"""Prepare the answers to the suggested questions for every measure, so Ask answers them at once.

    python scripts/warm_ask_cache.py [--env-file /path/to/service.env] [--pause 10]

Answers one question at a time, in this process (no HTTP, no rate limits), with the same models,
Bias Buster checks and cache as the site. Questions that already have a valid prepared answer are
skipped, so it can be stopped and run again at any time. Blocked answers and errors are not kept;
the next run tries them again. The API key is read from the environment (the env file), never printed.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

log = logging.getLogger("thinkballot.warm")


def warm(ballot, bias, pause=10, max_errors=5):
    """Returns the number of questions still without a prepared answer."""
    from werkzeug.exceptions import HTTPException

    from thinkballot.services.ask.app import live_answer, load_measure, prepared_answer
    from thinkballot.suggested import SUGGESTED_QUESTIONS

    missing, errors_in_a_row = 0, 0
    for row in ballot.get("/measures")["measures"]:
        measure = load_measure(ballot, row["id"])
        for i, question in enumerate(SUGGESTED_QUESTIONS):
            if prepared_answer(measure, question, bias):
                log.info("warm measure=%s q=%d status=cached", row["id"], i)
                continue
            started = time.monotonic()
            try:
                status = live_answer(measure, question, bias)["status"]
            except HTTPException as exc:
                status = f"error-{exc.code}"
            log.info("warm measure=%s q=%d status=%s %.1f s", row["id"], i, status, time.monotonic() - started)
            if status not in ("answered", "refused"):
                missing += 1
                errors_in_a_row = errors_in_a_row + 1 if status.startswith("error") else 0
                if errors_in_a_row >= max_errors:
                    log.info("warm stopping: %d errors in a row; run again later", errors_in_a_row)
                    return missing
            else:
                errors_in_a_row = 0
            time.sleep(pause)
    return missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", help="the service's env file, e.g. /path/to/service.env")
    parser.add_argument("--pause", type=float, default=10, help="seconds between AI requests")
    args = parser.parse_args()
    if args.env_file:  # before thinkballot.config is imported, so it sees the same settings as the site
        from dotenv import load_dotenv
        load_dotenv(args.env_file)

    from thinkballot import app, config
    from thinkballot.servicekit import ServiceClient

    app.create_app()  # registers the whole app for in-process calls; also sets up logging
    if config.AI_PROVIDER != "stub" and not config.OPENROUTER_API_KEY:
        log.error("OPENROUTER_API_KEY is not set")
        return 2
    log.info("warm cache=%s answer=%s review=%s", config.ASK_CACHE_PATH, config.ANSWER_MODEL, config.REVIEW_MODEL)
    missing = warm(ServiceClient("ballot", "inproc/svc/ballot"), ServiceClient("bias", "inproc/svc/bias"),
                   pause=args.pause)
    log.info("warm done: %d question(s) still without a prepared answer", missing)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
