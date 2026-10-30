"""Settings for every ThinkBallot service, read from environment variables (and .env)."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name, default):
    return os.environ.get(name, default)


# The site's public address (share links, preview cards, secure cookies).
PUBLIC_BASE = _env("TB_PUBLIC_URL", "http://127.0.0.1:8000")
# The production address. Every copy names it as the canonical page; any other copy (the demo/staging
# site, a laptop) says it is a test site and asks search engines not to index it.
CANONICAL_BASE = _env("TB_CANONICAL_URL", "https://www.thinkballot.com")
IS_PRODUCTION = PUBLIC_BASE.rstrip("/") == CANONICAL_BASE.rstrip("/")
# Where the services find each other: "inproc" (HTTP requests handed straight to this process's
# WSGI app, used on the server), http://host:port, or unix:/path.sock. Each service can later move
# to its own process or host by changing only its URL.
INTERNAL_BASE = _env("TB_INTERNAL_URL", PUBLIC_BASE)
SERVICE_URLS = {
    "ballot": _env("TB_BALLOT_URL", INTERNAL_BASE + "/svc/ballot"),
    "geo": _env("TB_GEO_URL", INTERNAL_BASE + "/svc/geo"),
    "ask": _env("TB_ASK_URL", INTERNAL_BASE + "/svc/ask"),
    "bias": _env("TB_BIAS_URL", INTERNAL_BASE + "/svc/bias"),
    "search": _env("TB_SEARCH_URL", INTERNAL_BASE + "/svc/search"),
    "community": _env("TB_COMMUNITY_URL", INTERNAL_BASE + "/svc/community"),
    "results": _env("TB_RESULTS_URL", INTERNAL_BASE + "/svc/results"),
}

# Services that only other ThinkBallot services may call (they need this shared token).
INTERNAL_TOKEN = os.environ.get("TB_INTERNAL_TOKEN") or secrets.token_hex(32)
SECRET_KEY = os.environ.get("TB_SECRET_KEY") or secrets.token_hex(32)  # signs sign-in cookies

# Official data: rebuilt from the release's own files on every deploy, so it lives with the release.
DB_PATH = Path(_env("TB_DB_PATH", str(ROOT / "instance" / "thinkballot.sqlite3")))
REPORT_PATH = Path(_env("TB_REPORT_PATH", str(ROOT / "reports" / "bias-report.json")))
RATE_DB_PATH = Path(_env("TB_RATE_DB_PATH", str(ROOT / "instance" / "ratelimit.sqlite3")))
# The community service keeps its own database, so it can never change the official data.
COMMUNITY_DB_PATH = Path(_env("TB_COMMUNITY_DB_PATH", str(ROOT / "instance" / "community.sqlite3")))
# Answers to the suggested questions, prepared in advance (never typed questions). Writable state,
# so it lives next to the community database.
ASK_CACHE_PATH = Path(_env("TB_ASK_CACHE_PATH", str(COMMUNITY_DB_PATH.parent / "ask_cache.sqlite3")))
# Accounts, sign-in and the community zone. Closed by default: they open only when there are people to
# moderate them (set TB_COMMUNITY_OPEN=1). Closing hides them; no community data is deleted.
COMMUNITY_OPEN = _env("TB_COMMUNITY_OPEN", "0") == "1"
ZIP_TABLE_PATH = Path(_env("TB_ZIP_TABLE", str(ROOT / "data" / "zip_districts.json")))

# AI provider: "openrouter" for real calls, "stub" for offline development and tests.
AI_PROVIDER = _env("TB_AI_PROVIDER", "openrouter")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")  # never printed or logged
# Paid models: no free-tier daily cap or queueing (owner's choice, 28-Oct-2026).
ANSWER_MODEL = _env("TB_ANSWER_MODEL", "nvidia/nemotron-3.5-super-vl")
REVIEW_MODEL = _env("TB_REVIEW_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
AI_PROVIDER_SORT = _env("TB_AI_PROVIDER_SORT", "throughput")  # OpenRouter provider routing: fastest first
# Spanish and Chinese versions of the prepared answers (scripts/warm_ask_cache.py --lang): one model
# translates the checked English answer, a second checks each translated sentence against the English.
TRANSLATE_MODEL = _env("TB_TRANSLATE_MODEL", "nvidia/nemotron-3.5-super-vl")
TRANSLATE_CHECK_MODEL = _env("TB_TRANSLATE_CHECK_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
AI_TIMEOUT_SECONDS = float(_env("TB_AI_TIMEOUT", "60"))
AI_RETRIES = int(_env("TB_AI_RETRIES", "2"))
# Total time one question may take (answer + Bias Buster review); past it the voter gets "try again".
ASK_BUDGET_SECONDS = float(_env("TB_ASK_BUDGET", "100"))

SERVICE_TIMEOUT_SECONDS = float(_env("TB_SERVICE_TIMEOUT", "120"))
# AI questions: per client, and site-wide so one person cannot use up the model quota for everyone.
ASK_LIMITS_PER_CLIENT = [(6, 60), (60, 86400)]
ASK_LIMITS_SITEWIDE = [(40, 60), (int(_env("TB_ASK_DAILY_CAP", "800")), 86400)]

# Election results from the Secretary of State's official feed (thinkballot/services/results).
# The last good copy lives next to the other writable state.
RESULTS_DB_PATH = Path(_env("TB_RESULTS_DB_PATH", str(RATE_DB_PATH.parent / "results.sqlite3")))

# Visitor analytics: append-only event files (thinkballot/eventlog.py). "1" logs on the production copy only,
# "0" turns it off, "force" logs anywhere (local checks).
ANALYTICS = _env("TB_ANALYTICS", "1")
EVENT_LOG_DIR = Path(_env("TB_EVENT_LOG_DIR", str(RATE_DB_PATH.parent / "events")))
SESSION_DAYS = 60  # the site cookie, and the visitor number inside it, last at most this long
RESULTS_MAX_AGE_SECONDS = 300  # fetch the feed at most once every five minutes
# Set to 1 only after the Secretary of State certifies the results; until then they say "Unofficial".
RESULTS_CERTIFIED = _env("TB_RESULTS_CERTIFIED", "") == "1"
# Local preview only: serve a recorded feed file instead of fetching (labelled as test data on the page).
RESULTS_FIXTURE = _env("TB_RESULTS_FIXTURE", "")
# Email (account verification). "none" (default) sends nothing, so sign-up stays closed;
# "smtp" sends through the provider below; "file" (development only) writes each message to MAIL_DIR.
MAIL_BACKEND = _env("TB_MAIL_BACKEND", "none")
SMTP_HOST = os.environ.get("TB_SMTP_HOST", "")
SMTP_PORT = int(_env("TB_SMTP_PORT", "587"))  # 587: STARTTLS (required); 465: TLS from the start
SMTP_USER = os.environ.get("TB_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("TB_SMTP_PASSWORD")  # never printed or logged
MAIL_FROM = os.environ.get("TB_MAIL_FROM", "")
MAIL_TIMEOUT_SECONDS = float(_env("TB_MAIL_TIMEOUT", "15"))
MAIL_DIR = Path(_env("TB_MAIL_DIR", str(ROOT / "instance" / "mail")))
# Verification emails the whole site may send per hour (protects the provider's sending quota).
MAIL_HOURLY_CAP = int(_env("TB_MAIL_HOURLY_CAP", "100"))
