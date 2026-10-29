"""Prepare the answers to the suggested questions for every measure, so Ask answers them at once.

    python scripts/warm_ask_cache.py [--env-file /path/to/service.env] [--pause 10] [--lang en,es,zh]

Answers one question at a time, in this process (no HTTP, no rate limits), with the same models,
Bias Buster checks and cache as the site. Questions that already have a valid prepared answer are
skipped, so it can be stopped and run again at any time. Blocked answers and errors are not kept;
the next run tries them again. The API key is read from the environment (the env file), never printed.

--lang es / zh translates the English prepared answers that exist (run --lang en first); it never calls
the answer model. A translation is stored only after its number check and its review pass; rejected
ones are tried again on the next run.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

log = logging.getLogger("thinkballot.warm")
LANGS = ("en", "es", "zh")


def warm(ballot, bias, pause=10, max_errors=5, level=None):
    """Returns the number of questions still without a prepared answer."""
    from werkzeug.exceptions import HTTPException

    from thinkballot.services.ask.app import live_answer, load_measure, prepared_answer
    from thinkballot.suggested import SUGGESTED_QUESTIONS

    missing, errors_in_a_row = 0, 0
    rows = ballot.get("/measures")["measures"]
    for row in (r for r in rows if not level or r["level"] == level):
        for i, question in enumerate(SUGGESTED_QUESTIONS):
            started = time.monotonic()
            try:
                measure = load_measure(ballot, row["id"])
                if prepared_answer(measure, question, bias):
                    log.info("warm measure=%s q=%d status=cached", row["id"], i)
                    continue
                status = live_answer(measure, question, bias, store_refusals=True)["status"]
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


def warm_translations(ballot, bias, lang, pause=10, max_errors=5, level=None):
    """Translate the English prepared answers into lang. Returns the number of English answers still
    without a stored translation (questions with no English answer yet are counted apart, not here)."""
    from werkzeug.exceptions import HTTPException

    from thinkballot import ai
    from thinkballot.services.ask.app import load_measure, prepare_translation
    from thinkballot.suggested import SUGGESTED_QUESTIONS

    missing, no_english, errors_in_a_row = 0, 0, 0
    rows = ballot.get("/measures")["measures"]
    for row in (r for r in rows if not level or r["level"] == level):
        for i, question in enumerate(SUGGESTED_QUESTIONS):
            started = time.monotonic()
            try:
                measure = load_measure(ballot, row["id"])
                status = prepare_translation(measure, question, lang, bias, ballot)
            except ai.AIError as exc:
                status = f"error-{exc}"
            except HTTPException as exc:
                status = f"error-{exc.code}"
            log.info("warm measure=%s q=%d lang=%s status=%s %.1f s", row["id"], i, lang, status,
                     time.monotonic() - started)
            if status in ("cached", "refused", "no-english"):
                no_english += status == "no-english"
                continue  # no AI call was made
            if status != "translated":
                missing += 1
                errors_in_a_row = errors_in_a_row + 1 if status.startswith("error") else 0
                if errors_in_a_row >= max_errors:
                    log.info("warm stopping: %d errors in a row; run again later", errors_in_a_row)
                    return missing
            else:
                errors_in_a_row = 0
            time.sleep(pause)
    if no_english:
        log.info("warm lang=%s: %d question(s) have no English prepared answer yet (run --lang en)", lang, no_english)
    return missing


def parse_langs(values):
    """--lang es --lang zh, or --lang es,zh; English only by default."""
    langs = [code.strip() for v in values or ["en"] for code in v.split(",") if code.strip()]
    bad = [code for code in langs if code not in LANGS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown language: {', '.join(bad)} (choose from {', '.join(LANGS)})")
    return list(dict.fromkeys(langs))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", help="the service's env file, e.g. /path/to/service.env")
    parser.add_argument("--pause", type=float, default=10, help="seconds between AI requests")
    parser.add_argument("--level", choices=["state", "local"], help="only statewide or only local measures")
    parser.add_argument("--lang", action="append",
                        help="en (answer), es or zh (translate the English answers); repeat or comma-separate")
    args = parser.parse_args()
    try:
        langs = parse_langs(args.lang)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.env_file:  # before thinkballot.config is imported, so it sees the same settings as the site
        from dotenv import load_dotenv
        load_dotenv(args.env_file)

    from thinkballot import app, config
    from thinkballot.servicekit import ServiceClient

    app.create_app()  # registers the whole app for in-process calls; also sets up logging
    if config.AI_PROVIDER != "stub" and not config.OPENROUTER_API_KEY:
        log.error("OPENROUTER_API_KEY is not set")
        return 2
    ballot, bias = ServiceClient("ballot", "inproc/svc/ballot"), ServiceClient("bias", "inproc/svc/bias")
    missing = 0
    for lang in langs:
        if lang == "en":
            log.info("warm cache=%s answer=%s review=%s", config.ASK_CACHE_PATH, config.ANSWER_MODEL,
                     config.REVIEW_MODEL)
            missing += warm(ballot, bias, pause=args.pause, level=args.level)
        else:
            log.info("warm cache=%s lang=%s translate=%s check=%s", config.ASK_CACHE_PATH, lang,
                     config.TRANSLATE_MODEL, config.TRANSLATE_CHECK_MODEL)
            missing += warm_translations(ballot, bias, lang, pause=args.pause, level=args.level)
    log.info("warm done: %d question(s) still without a prepared answer", missing)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
