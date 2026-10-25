"""Settings for every ThinkBallot service, read from environment variables (and .env)."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name, default):
    return os.environ.get(name, default)


# Where this process is reachable; the services find each other through these base URLs.
# Each service can later move to its own host by changing only its URL.
PUBLIC_BASE = _env("TB_BASE_URL", "http://127.0.0.1:8000")
SERVICE_URLS = {
    "ballot": _env("TB_BALLOT_URL", PUBLIC_BASE + "/svc/ballot"),
    "geo": _env("TB_GEO_URL", PUBLIC_BASE + "/svc/geo"),
    "ask": _env("TB_ASK_URL", PUBLIC_BASE + "/svc/ask"),
    "bias": _env("TB_BIAS_URL", PUBLIC_BASE + "/svc/bias"),
    "search": _env("TB_SEARCH_URL", PUBLIC_BASE + "/svc/search"),
    "community": _env("TB_COMMUNITY_URL", PUBLIC_BASE + "/svc/community"),
}

# Services that only other ThinkBallot services may call (they need this shared token).
INTERNAL_TOKEN = os.environ.get("TB_INTERNAL_TOKEN") or secrets.token_hex(32)
SECRET_KEY = os.environ.get("TB_SECRET_KEY") or secrets.token_hex(32)  # signs sign-in cookies

DB_PATH = Path(_env("TB_DB_PATH", str(ROOT / "instance" / "thinkballot.sqlite3")))
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
