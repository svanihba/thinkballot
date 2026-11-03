"""Report an error, security.txt, and fonts served from the site itself."""

import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

from thinkballot import config
from thinkballot.services.web import reports


@pytest.fixture
def fresh(server, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROBLEM_REPORTS_DB_PATH", tmp_path / "reports.sqlite3")
    from thinkballot import ratelimit
    ratelimit.allow("report", "warm-up", [(1, 1)])  # creates the table on a fresh database
    from test_verification import reset_limits
    reset_limits()
    return server


def form(server, path="/report?page=/prop-a"):
    s = requests.Session()
    page = s.get(server + path)
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    return s, page, csrf


def rows():
    with sqlite3.connect(config.PROBLEM_REPORTS_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM report ORDER BY id")]


def test_footer_links_to_the_report_form_with_the_current_page(server):
    html = requests.get(server + "/prop-a").text
    assert 'href="/report?page=/prop-a"' in html
    es = requests.get(server + "/es/prop-a").text
    assert 'href="/es/report?page=/es/prop-a"' in es


def test_report_form_prefills_the_page_and_saves_a_report(fresh):
    s, page, csrf = form(fresh)
    assert page.status_code == 200 and 'value="/prop-a"' in page.text
    r = s.post(fresh + "/report", data={"csrf": csrf, "kind": "error", "page": "/prop-a",
                                        "message": "The fiscal effect figure looks wrong.", "contact": ""})
    assert r.status_code == 200 and "Thank you" in r.text
    [row] = rows()
    assert (row["kind"], row["page"], row["message"], row["contact"], row["lang"]) == \
        ("error", "/prop-a", "The fiscal effect figure looks wrong.", "", "en")
    assert datetime.fromisoformat(row["created"]) > datetime.now(timezone.utc) - timedelta(minutes=1)


def test_report_form_works_in_spanish(fresh):
    s, page, csrf = form(fresh, "/es/report?page=/es/prop-a")
    assert page.status_code == 200 and 'lang="es"' in page.text
    r = s.post(fresh + "/es/report", data={"csrf": csrf, "kind": "other", "page": "/es/prop-a",
                                           "message": "Falta una traducción aquí."})
    assert r.status_code == 200
    assert rows()[0]["lang"] == "es"


def test_security_kind_is_preselected_from_the_link(fresh):
    _, page, _ = form(fresh, "/report?kind=security")
    assert re.search(r'<option value="security" selected', page.text)


@pytest.mark.parametrize("data,reason", [
    ({"kind": "error", "page": "/prop-a", "message": "short"}, "too short"),
    ({"kind": "error", "page": "/prop-a", "message": "x" * 2001}, "too long"),
    ({"kind": "nope", "page": "/prop-a", "message": "A real sentence about a problem."}, "bad kind"),
    ({"kind": "error", "page": "/prop-a", "message": "A real sentence about a problem.",
      "contact": "y" * 201}, "contact too long"),
])
def test_bad_reports_are_not_saved(fresh, data, reason):
    s, _, csrf = form(fresh)
    r = s.post(fresh + "/report", data={"csrf": csrf, **data})
    assert r.status_code == 400, reason
    assert not config.PROBLEM_REPORTS_DB_PATH.exists() or rows() == []


def test_page_field_keeps_only_a_path_on_this_site(fresh):
    s, page, csrf = form(fresh, "/report?page=https://evil.example/x")
    assert re.search(r'name="page" value=""', page.text)  # the language links may keep the query; the form may not
    s.post(fresh + "/report", data={"csrf": csrf, "kind": "error", "page": "//evil.example/x",
                                    "message": "A real sentence about a problem."})
    assert rows()[0]["page"] == ""


def test_filled_honeypot_is_thanked_but_not_saved(fresh):
    s, _, csrf = form(fresh)
    r = s.post(fresh + "/report", data={"csrf": csrf, "kind": "error", "page": "/", "website": "http://spam",
                                        "message": "Buy things at my shop today please."})
    assert r.status_code == 200 and "Thank you" in r.text
    assert not config.PROBLEM_REPORTS_DB_PATH.exists() or rows() == []


def test_reports_without_the_form_token_are_refused(fresh):
    r = requests.post(fresh + "/report", data={"kind": "error", "page": "/", "message": "A real problem here."})
    assert r.status_code == 400


def test_reports_are_limited_per_network(fresh):
    s, _, csrf = form(fresh)
    codes = [s.post(fresh + "/report", data={"csrf": csrf, "kind": "error", "page": "/",
                                             "message": f"Problem number {i} on the page."}).status_code
             for i in range(reports.PER_NETWORK_HOUR + 1)]
    assert codes[:-1] == [200] * reports.PER_NETWORK_HOUR and codes[-1] == 429
    assert len(rows()) == reports.PER_NETWORK_HOUR


def test_reports_older_than_60_days_are_deleted(fresh):
    reports.save("error", "/", "An old report about something.", "", "en",
                 now=datetime.now(timezone.utc) - timedelta(days=61))
    reports.save("error", "/", "A recent report about something.", "", "en")
    assert [r["message"] for r in rows()] == ["A recent report about something."]


def test_report_file_is_private(fresh):
    reports.save("error", "/", "A report about something.", "", "en")
    assert config.PROBLEM_REPORTS_DB_PATH.stat().st_mode & 0o077 == 0


def test_security_txt(server):
    r = requests.get(server + "/.well-known/security.txt")
    assert r.status_code == 200 and r.headers["Content-Type"].startswith("text/plain")
    fields = dict(line.split(": ", 1) for line in r.text.splitlines() if line and not line.startswith("#")
                  and line.split(": ", 1)[0] != "Contact")
    contacts = [line.split(": ", 1)[1] for line in r.text.splitlines() if line.startswith("Contact: ")]
    assert contacts == [server + "/report?kind=security"]
    expires = datetime.fromisoformat(fields["Expires"].replace("Z", "+00:00"))
    assert timedelta(days=30) < expires - datetime.now(timezone.utc) < timedelta(days=366)
    assert fields["Preferred-Languages"] == "en, es, zh"
    assert fields["Canonical"] == server + "/.well-known/security.txt"


def test_fonts_come_from_the_site_itself(server):
    r = requests.get(server + "/")
    assert "googleapis" not in r.text and "gstatic" not in r.text
    csp = r.headers["Content-Security-Policy"]
    assert "font-src 'self'" in csp and "google" not in csp
    css = requests.get(server + "/static/fonts.css")
    assert css.status_code == 200
    files = set(re.findall(r"url\(fonts/([a-z0-9-]+\.woff2)\)", css.text))
    assert len(files) == 10
    for name in files:
        font = requests.get(server + "/static/fonts/" + name)
        assert font.status_code == 200 and font.content[:4] == b"wOF2", name
    for family in ("Fraunces", "Public Sans", "IBM Plex Mono"):
        assert f"font-family: '{family}'" in css.text
