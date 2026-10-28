"""Languages of the web pages: English (default), Spanish and Traditional Chinese.

The language is part of the URL (/es/..., /zh/...), so a shared link opens in the language it was
shared in and each language has its own address for search engines. Nothing is stored about the
choice: no cookie, no header sniffing.

Two kinds of text, kept apart:
- official measure text comes word for word from the Secretary of State's official translations
  (pipeline/extract/ca_sos_guide_translated.py, verified by scripts/seed.py), or stays English;
- interface text (navigation, headings, notices, explanations) is ThinkBallot's own, translated in
  one catalog per language: catalogs/<lang>.json maps each English source string to its translation.
  A string missing from a catalog shows in English (tests/test_i18n.py checks that none is missing).
"""

import json
import re
from pathlib import Path

from markupsafe import Markup

LANGS = {
    "en": {"html": "en", "name": "English", "short": "EN", "og": "en_US", "hreflang": "en"},
    "es": {"html": "es", "name": "Español", "short": "ES", "og": "es_US", "hreflang": "es"},
    "zh": {"html": "zh-Hant", "name": "中文", "short": "中文", "og": "zh_TW", "hreflang": "zh-Hant"},
}
DEFAULT = "en"
PREFIX_RE = re.compile(r"^/(es|zh)(/.*)?$")
CATALOG_DIR = Path(__file__).with_name("catalogs")
CATALOGS = {code: json.loads((CATALOG_DIR / f"{code}.json").read_text(encoding="utf-8"))["strings"]
            for code in LANGS if code != DEFAULT}


def gettext(lang, text, **values):
    """The interface string in lang (English if not translated), as markup. Catalog strings are
    ThinkBallot's own and may contain simple HTML; values filled in are escaped."""
    translated = CATALOGS.get(lang, {}).get(text) or text
    return Markup(translated).format(**values) if values else Markup(translated)


def lang_path(lang, path):
    """The address of a page (path without a language prefix) in lang."""
    if lang == DEFAULT:
        return path
    return f"/{lang}/" if path == "/" else f"/{lang}{path}"


class LanguagePrefix:
    """WSGI middleware: /es/prop/prop-1 is served by the same view as /prop/prop-1, with
    environ["tb.lang"] = "es". Requests without a prefix are English."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        m = PREFIX_RE.match(environ.get("PATH_INFO", ""))
        if m:
            environ["tb.lang"] = m.group(1)
            environ["PATH_INFO"] = m.group(2) or "/"
        else:
            environ["tb.lang"] = DEFAULT
        return self.app(environ, start_response)
