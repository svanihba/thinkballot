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
ZIP_TABLE_PATH = Path(_env("TB_ZIP_TABLE", str(ROOT / "data" / "zip_districts.json")))

# AI provider: "openrouter" for real calls, "stub" for offline development and tests.
AI_PROVIDER = _env("TB_AI_PROVIDER", "openrouter")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")  # never printed or logged
ANSWER_MODEL = _env("TB_ANSWER_MODEL", "nvidia/nemotron-3.5-lightning:free")
REVIEW_MODEL = _env("TB_REVIEW_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
AI_TIMEOUT_SECONDS = float(_env("TB_AI_TIMEOUT", "45"))
AI_RETRIES = int(_env("TB_AI_RETRIES", "2"))
# Total time one question may take (answer + Bias Buster review); past it the voter gets "try again".
ASK_BUDGET_SECONDS = float(_env("TB_ASK_BUDGET", "85"))

SERVICE_TIMEOUT_SECONDS = float(_env("TB_SERVICE_TIMEOUT", "120"))
# AI questions: per client, and site-wide so one person cannot use up the model quota for everyone.
ASK_LIMITS_PER_CLIENT = [(6, 60), (60, 86400)]
ASK_LIMITS_SITEWIDE = [(40, 60), (int(_env("TB_ASK_DAILY_CAP", "800")), 86400)]
