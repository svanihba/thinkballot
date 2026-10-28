"""New accounts stay disabled until the owner opens the emailed link AND enters its passcode."""

import logging
import re
import sqlite3
import time
from email import policy
from email.parser import BytesParser

import pytest
import requests

from thinkballot import config, mailer
from thinkballot.servicekit import ServiceClient, ServiceError
from thinkballot.services.community import db

PASSWORD = "password123"


@pytest.fixture(scope="module")
def svc(server):
    return ServiceClient("community")


def reset_limits():
    """Rate limits are shared by the whole test session; start a test from a clean slate."""
    with sqlite3.connect(config.RATE_DB_PATH) as conn:
        conn.execute("DELETE FROM hit")


def mails_to(address):
    found = []
    for path in sorted(config.MAIL_DIR.glob("*.eml")) if config.MAIL_DIR.exists() else []:
        msg = BytesParser(policy=policy.default).parse(path.open("rb"))
        if msg["To"] == address:
            found.append(msg)
    return found


def wait_for_mail(address, count=1):
    """Message number `count` to this address, once it has arrived (sending runs in the background)."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        found = mails_to(address)
        if len(found) >= count:
            msg = found[count - 1]
            body = msg.get_content()
            token = re.search(r"/verify\?t=([A-Za-z0-9_-]+)", body).group(1)
            code = re.search(r"passcode on that page: ([0-9]{6})", body).group(1)
            return {"msg": msg, "body": body, "token": token, "code": code}
        time.sleep(0.05)
    raise AssertionError(f"no email #{count} to {address}")


def user_row(email):
    with db.connect(config.COMMUNITY_DB_PATH) as conn:
        return conn.execute("SELECT * FROM user WHERE email = ?", (email,)).fetchone()


def csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def confirm_by_email(s, server, email, count=1):
    """Open the newest emailed link in session s and enter its passcode."""
    mail = wait_for_mail(email, count)
    page = s.get(server + "/verify", params={"t": mail["token"]})
    assert page.headers["Referrer-Policy"] == "no-referrer"
    assert f'name="t" value="{mail["token"]}"' in page.text
    r = s.post(server + "/verify", data={"csrf": csrf(page.text), "t": mail["token"], "code": mail["code"]})
    assert "Your email is confirmed" in r.text
    return mail


def signup(svc, name):
    return svc.post("/users", {"email": f"{name}@example.com", "username": name, "password": PASSWORD})


def test_signup_leaves_the_account_disabled(svc):
    assert signup(svc, "newbie") == {"status": "check-email"}
    row = user_row("newbie@example.com")
    assert row["verified"] == 0
    mail = wait_for_mail("newbie@example.com")
    assert mail["msg"]["Subject"] == "Confirm your ThinkBallot account"
    assert "ignore this email" in mail["body"]
    assert svc.post("/login", {"email": "newbie@example.com", "password": PASSWORD})["verified"] is False
    for path, payload in [("/comments", {"measure_id": "prop-a", "text": "hi"}),
                          ("/facts", {"measure_id": "prop-a", "text": "x", "citation_url": "https://a.gov/"}),
                          ("/comments/1/flag", {}),
                          ("/facts/1/rate", {"helpful": True, "leaning": "yes"})]:
        with pytest.raises(ServiceError) as exc:
            svc.post(path, {"user_id": row["id"], **payload})
        assert exc.value.status == 403, path


def test_link_and_passcode_together_verify(svc):
    signup(svc, "both")
    mail = wait_for_mail("both@example.com")
    u = svc.post("/verify", {"token": mail["token"], "code": mail["code"]})
    assert u["username"] == "both"
    assert svc.post("/login", {"email": "both@example.com", "password": PASSWORD})["verified"] is True
    svc.post("/comments", {"user_id": u["id"], "measure_id": "prop-a", "text": "Verified hello"})
    with pytest.raises(ServiceError) as exc:  # the link works once
        svc.post("/verify", {"token": mail["token"], "code": mail["code"]})
    assert exc.value.status == 410


def test_passcode_without_the_links_token_does_nothing(svc):
    signup(svc, "nolink")
    mail = wait_for_mail("nolink@example.com")
    for token in (None, "", "not-the-token", mail["token"][:-1]):
        with pytest.raises(ServiceError) as exc:
            svc.post("/verify", {"token": token, "code": mail["code"]})
        assert exc.value.status == 410
    assert user_row("nolink@example.com")["verified"] == 0


def test_five_wrong_passcodes_kill_the_link(svc):
    signup(svc, "guesser")
    mail = wait_for_mail("guesser@example.com")
    wrong = f"{(int(mail['code']) + 1) % 10 ** 6:06d}"
    for _ in range(4):
        with pytest.raises(ServiceError) as exc:
            svc.post("/verify", {"token": mail["token"], "code": wrong})
        assert exc.value.status == 400
    with pytest.raises(ServiceError) as exc:
        svc.post("/verify", {"token": mail["token"], "code": "abc"})  # the fifth wrong try
    assert exc.value.status == 410 and "Too many wrong passcodes" in exc.value.detail
    with pytest.raises(ServiceError) as exc:  # even the right passcode is too late now
        svc.post("/verify", {"token": mail["token"], "code": mail["code"]})
    assert exc.value.status == 410
    assert user_row("guesser@example.com")["verified"] == 0


def test_expired_link_fails(svc):
    signup(svc, "slowpoke")
    mail = wait_for_mail("slowpoke@example.com")
    with db.connect(config.COMMUNITY_DB_PATH) as conn:
        conn.execute("UPDATE email_token SET expires_at = datetime('now', '-1 minute')")
    with pytest.raises(ServiceError) as exc:
        svc.post("/verify", {"token": mail["token"], "code": mail["code"]})
    assert exc.value.status == 410
    assert user_row("slowpoke@example.com")["verified"] == 0


def test_unverified_sign_in_offers_a_new_email_which_is_rate_limited(server, svc):
    reset_limits()
    signup(svc, "resender")  # email 1 of 3 this hour for this account
    wait_for_mail("resender@example.com")
    s = requests.Session()
    page = s.get(server + "/signin").text
    r = s.post(server + "/signin", data={"csrf": csrf(page), "action": "signin",
                                         "email": "resender@example.com", "password": PASSWORD})
    assert "Please confirm your email" in r.text and "Send a new verification email" in r.text
    assert "sign out" not in r.text
    r = s.post(server + "/signin", data={"csrf": csrf(r.text), "action": "resend"})
    assert "We&#39;ve sent a new email" in r.text
    old = wait_for_mail("resender@example.com", 1)
    new = wait_for_mail("resender@example.com", 2)
    assert new["token"] != old["token"]
    with pytest.raises(ServiceError):  # a new email replaces the old link
        svc.post("/verify", {"token": old["token"], "code": old["code"]})
    r = s.post(server + "/signin", data={"csrf": csrf(r.text), "action": "resend"})  # email 3
    wait_for_mail("resender@example.com", 3)
    r = s.post(server + "/signin", data={"csrf": csrf(r.text), "action": "resend"})
    assert "Too many emails" in r.text
    time.sleep(0.3)
    assert len(mails_to("resender@example.com")) == 3
    confirm_by_email(s, server, "resender@example.com", 3)
    assert "@resender · sign out" in s.get(server + "/prop/prop-a").text


def test_resend_needs_a_recent_correct_password(server):
    reset_limits()
    s = requests.Session()
    page = s.get(server + "/signin").text
    r = s.post(server + "/signin", data={"csrf": csrf(page), "action": "resend"})
    assert "Please sign in again" in r.text


def test_signup_answers_the_same_for_an_email_that_already_has_an_account(server, svc):
    reset_limits()
    make = lambda name, email: svc.post("/users", {"email": email, "username": name, "password": PASSWORD})  # noqa
    assert make("dup1", "dup@example.com") == make("dup2", "DUP@example.com")
    with db.connect(config.COMMUNITY_DB_PATH) as conn:
        conn.execute("UPDATE user SET verified = 1 WHERE email = 'dup@example.com'")
    assert make("dup3", "dup@example.com") == {"status": "check-email"}
    time.sleep(0.3)
    assert len(mails_to("dup@example.com")) == 1  # nothing sent for the repeats
    assert user_row("dup@example.com")["username"] == "dup1"

    pages = []
    for i, email in enumerate(["webnew@example.com", "dup@example.com"]):
        s = requests.Session()
        page = s.get(server + "/signin").text
        r = s.post(server + "/signin", data={"csrf": csrf(page), "action": "signup", "email": email,
                                             "username": f"webdup{i}", "password": PASSWORD})
        pages.append((r.status_code, [h.url for h in r.history], r.text.replace(csrf(r.text), "")))
    assert pages[0] == pages[1]
    assert "we&#39;ve emailed you a link and a passcode" in pages[0][2]


def test_none_backend_keeps_sign_up_closed(server, svc, monkeypatch):
    reset_limits()
    monkeypatch.setattr(config, "MAIL_BACKEND", "none")
    with pytest.raises(ServiceError) as exc:
        signup(svc, "nomail")
    assert exc.value.status == 503
    assert user_row("nomail@example.com") is None
    s = requests.Session()
    page = s.get(server + "/signin").text
    r = s.post(server + "/signin", data={"csrf": csrf(page), "action": "signup", "email": "nomail@example.com",
                                         "username": "nomail", "password": PASSWORD})
    assert "Sign-up is temporarily unavailable" in r.text
    assert user_row("nomail@example.com") is None


def test_secrets_never_reach_the_logs(server, svc, caplog):
    caplog.set_level(logging.DEBUG)
    reset_limits()
    s = requests.Session()
    page = s.get(server + "/signin").text
    s.post(server + "/signin", data={"csrf": csrf(page), "action": "signup", "email": "quiet@example.com",
                                     "username": "quiet", "password": PASSWORD})
    mail = confirm_by_email(s, server, "quiet@example.com")
    deadline = time.monotonic() + 5
    while "q***@example.com" not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "mail backend=file to=q***@example.com sent" in caplog.text
    # Everything the site logs; urllib3 is only this test's own browser stand-in printing its URLs.
    site_log = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("urllib3"))
    assert "svc community POST /verify" in site_log
    for secret in (mail["token"], mail["code"], "quiet@example.com", PASSWORD):
        assert secret not in site_log


def test_existing_accounts_are_migrated_as_verified(tmp_path):
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE user (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE, pw_hash TEXT NOT NULL,
            is_mod INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO user (email, username, pw_hash, is_mod) VALUES ('mod@example.com', 'mod', 'x', 1);
        INSERT INTO user (email, username, pw_hash) VALUES ('member@example.com', 'member', 'x');
    """)
    old.commit()
    old.close()
    conn = db.connect(path)
    assert [r["verified"] for r in conn.execute("SELECT verified FROM user ORDER BY id")] == [1, 1]
    conn.execute("INSERT INTO user (email, username, pw_hash) VALUES ('new@example.com', 'new', 'x')")
    conn.commit()
    conn.close()
    conn = db.connect(path)  # connecting again changes nothing
    assert [r["verified"] for r in conn.execute("SELECT verified FROM user ORDER BY id")] == [1, 1, 0]


def test_unverified_accounts_are_removed_after_two_days(svc):
    signup(svc, "ghost")
    wait_for_mail("ghost@example.com")
    with db.connect(config.COMMUNITY_DB_PATH) as conn:
        conn.execute("UPDATE user SET created_at = datetime('now', '-3 days') WHERE username = 'ghost'")
    signup(svc, "ghostbuster")  # any sign-up tidies up
    assert user_row("ghost@example.com") is None
    with db.connect(config.COMMUNITY_DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM email_token WHERE expires_at < datetime('now')").fetchone()[0] == 0


class FakeSMTP:
    instances = []
    fail_first = True

    def __init__(self, host, port, timeout):
        self.calls = [("connect", host, port, timeout)]
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, msg):
        if FakeSMTP.fail_first:
            FakeSMTP.fail_first = False
            raise OSError("connection reset")
        self.calls.append(("send", msg["To"]))


def test_smtp_backend_uses_starttls_retries_once_and_logs_no_secrets(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer, "RETRY_DELAY_SECONDS", 0)
    for name, value in [("MAIL_BACKEND", "smtp"), ("SMTP_HOST", "smtp.invalid"), ("SMTP_PORT", 587),
                        ("SMTP_USER", "apikey"), ("SMTP_PASSWORD", "s3cret-pw"),
                        ("MAIL_FROM", "ThinkBallot <noreply@example.org>")]:
        monkeypatch.setattr(config, name, value)
    assert mailer.send("reader@example.com", "Hello", "passcode 123456")
    assert [c[0] for c in FakeSMTP.instances[-1].calls] == ["connect", "starttls", "login", "send"]
    assert len(FakeSMTP.instances) == 2  # one retry after the first failure
    assert "attempt=1 failed: OSError" in caplog.text and "r***@example.com sent" in caplog.text
    for secret in ("s3cret-pw", "123456", "reader@example.com"):
        assert secret not in caplog.text
    monkeypatch.setattr(config, "SMTP_HOST", "")
    assert not mailer.available() and not mailer.send("reader@example.com", "Hello", "x")
