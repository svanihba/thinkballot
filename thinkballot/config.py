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
# Where the services find each other. Either http://host:port or, on the server, the process's own
# unix socket as unix:/run/thinkballot/app.sock. Each service can later move by changing only its URL.
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
# The community service keeps its own database, so it can never change the official data.
COMMUNITY_DB_PATH = Path(_env("TB_COMMUNITY_DB_PATH", str(ROOT / "instance" / "community.sqlite3")))
ZIP_TABLE_PATH = Path(_env("TB_ZIP_TABLE", str(ROOT / "data" / "zip_districts.json")))

# AI provider: "openrouter" for real calls, "stub" for offline development and tests.
AI_PROVIDER = _env("TB_AI_PROVIDER", "openrouter")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")  # never printed or logged
ANSWER_MODEL = _env("TB_ANSWER_MODEL", "nvidia/nemotron-3.5-lightning:free")
REVIEW_MODEL = _env("TB_REVIEW_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
AI_TIMEOUT_SECONDS = float(_env("TB_AI_TIMEOUT", "45"))
AI_RETRIES = int(_env("TB_AI_RETRIES", "2"))

SERVICE_TIMEOUT_SECONDS = float(_env("TB_SERVICE_TIMEOUT", "120"))
ASK_RATE_LIMIT_PER_MINUTE = int(_env("TB_ASK_RATE_LIMIT", "6"))
