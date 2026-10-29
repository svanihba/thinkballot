"""community service: accounts, discussion and community-submitted facts.

- Comments are post-moderated: they appear at once; FLAGS_TO_HIDE flags hide one until a moderator
  reviews it. Rules are viewpoint-neutral (see the code of conduct on the site).
- Facts must cite an https source (government pages get a "verified official source" mark), pass Bias Buster's wording check, and then reach
  bridging consensus: rated helpful by at least one person leaning YES and one leaning NO on that
  measure. A moderator then publishes ("vetted") or rejects them.
- New accounts stay disabled until the owner confirms the email: one email carries a link (a random
  token) and a 6-digit passcode, and both are needed, within 30 minutes, with at most 5 wrong passcodes.
Only the web service may call this service (internal token); it vouches for who is signed in.
"""

import hashlib
import hmac
import re
import secrets
import sqlite3
from urllib.parse import urlparse

from flask import abort, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from ... import config, mailer, ratelimit
from ...servicekit import ServiceClient, ServiceError, make_service
from . import db

FLAGS_TO_HIDE = 5
# Flags and fact ratings count only from accounts at least this old, so a burst of throwaway
# accounts can't hide a comment or fake bridging consensus.
MIN_ACCOUNT_AGE = "-1 hour"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,24}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_COMMENT = 1000
MAX_FACT = 400
# Citations from these government domains are marked as official sources.
OFFICIAL_SUFFIXES = (".gov", ".ca.gov", ".ca.us")
LEANINGS = {"yes", "no", "undecided"}
VERIFY_MINUTES = 30
VERIFY_MAX_TRIES = 5
# Accounts never verified are removed after this long, so an unconfirmed sign-up can't hold an
# email address or display name for good.
UNVERIFIED_KEEP = "-2 days"
# Verification emails per account (sign-up and resends together).
MAILS_PER_ACCOUNT = [(3, 3600), (10, 86400)]
CODE_RE = re.compile(r"^[0-9]{6}$")
LINK_DEAD = "This link has expired or was already used. Sign in to get a new email."


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def code_hash(token, code):
    # Keyed with the link's token, which is never stored: a copy of the database alone can't be used
    # to try all million passcodes.
    return hmac.new(token.encode(), code.encode(), hashlib.sha256).hexdigest()


def verification_email(token, code):
    link = f"{config.PUBLIC_BASE}/verify?t={token}"
    return ("Confirm your ThinkBallot account",
            "Someone, hopefully you, created a ThinkBallot account with this email address.\n\n"
            f"To confirm it, open this link:\n{link}\n\n"
            f"Then enter this passcode on that page: {code}\n\n"
            f"The link and passcode work together, once, for {VERIFY_MINUTES} minutes.\n\n"
            "If this wasn't you, you can ignore this email. The account stays disabled and is removed "
            "in two days.\n\n"
            f"ThinkBallot\n{config.PUBLIC_BASE}\n")


def is_https_url(url):
    try:
        parts = urlparse(url)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname)


def is_official_url(url):
    host = (urlparse(url).hostname or "").lower() if is_https_url(url) else ""
    return any(host.endswith(s) for s in OFFICIAL_SUFFIXES)


def _with_official(rows):
    return [dict(r, official_source=is_official_url(r["citation_url"])) for r in rows]


def create_app(db_path=None):
    app = make_service("community")
    bias = ServiceClient("bias")

    def conn():
        if "conn" not in g:
            g.conn = db.connect(db_path)
        return g.conn

    @app.teardown_appcontext
    def close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    def body():
        return request.get_json(silent=True) or {}

    def user(user_id):
        row = conn().execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
        if not row:
            abort(401, "Please sign in.")
        if not row["verified"]:
            abort(403, "Please confirm your email first.")
        return row

    def established(u):
        old = conn().execute("SELECT created_at <= datetime('now', ?) FROM user WHERE id = ?",
                             (MIN_ACCOUNT_AGE, u["id"])).fetchone()[0]
        if not old:
            abort(403, "New accounts can flag and rate after their first hour.")

    def moderator(user_id):
        u = user(user_id)
        if not u["is_mod"]:
            abort(403, "Moderators only.")
        return u

    def text_field(b, name, limit):
        t = b.get(name)
        if not isinstance(t, str) or not t.strip():
            abort(400, f"{name} is required")
        if len(t) > limit:
            abort(400, f"Please keep it under {limit} characters.")
        return t.strip()

    # ---------- accounts ----------
    def clean_up():
        """Drop expired links, and accounts never verified (they can't have posted anything)."""
        with conn():
            conn().execute("DELETE FROM email_token WHERE expires_at < datetime('now')")
            conn().execute(
                "DELETE FROM user WHERE verified = 0 AND created_at < datetime('now', ?) "
                "AND id NOT IN (SELECT user_id FROM comment) AND id NOT IN (SELECT user_id FROM fact) "
                "AND id NOT IN (SELECT user_id FROM flag) AND id NOT IN (SELECT user_id FROM rating)",
                (UNVERIFIED_KEEP,))

    def send_verification(user_id, email):
        """Replace the account's link with a new one and email it. False if over a limit."""
        if not ratelimit.allow("verify-mail", f"user:{user_id}", MAILS_PER_ACCOUNT):
            return False
        if not ratelimit.allow("verify-mail", None, [(config.MAIL_HOURLY_CAP, 3600)]):
            return False
        token = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(10 ** 6):06d}"
        with conn():
            conn().execute("DELETE FROM email_token WHERE user_id = ?", (user_id,))
            conn().execute(
                "INSERT INTO email_token (user_id, token_hash, code_hash, expires_at) "
                "VALUES (?, ?, ?, datetime('now', ?))",
                (user_id, token_hash(token), code_hash(token, code), f"+{VERIFY_MINUTES} minutes"))
        mailer.send_later(email, *verification_email(token, code))
        return True

    @app.post("/users")
    def create_user():
        b = body()
        email = (b.get("email") or "").strip().lower()
        username, password = b.get("username") or "", b.get("password") or ""
        if not EMAIL_RE.match(email) or len(email) > 254:
            abort(400, "Please enter a valid email address.")
        if not USERNAME_RE.match(username):
            abort(400, "Display names are 3 to 24 letters, numbers or underscores.")
        if len(password) < 8:
            abort(400, "Passwords need at least 8 characters.")
        if not mailer.available():
            abort(503, "Sign-up is temporarily unavailable. Please try again later.")
        clean_up()
        pw_hash = generate_password_hash(password)  # always, so both paths below take as long
        if conn().execute("SELECT 1 FROM user WHERE username = ?", (username,)).fetchone():
            abort(409, "That display name is taken. Please choose another.")  # public anyway
        try:
            with conn():
                cur = conn().execute("INSERT INTO user (email, username, pw_hash) VALUES (?, ?, ?)",
                                     (email, username, pw_hash))
        except sqlite3.IntegrityError as exc:
            if "username" in str(exc):
                abort(409, "That display name is taken. Please choose another.")
            # The email already has an account. Answer exactly as for a new one, and send nothing:
            # no mail to people who didn't ask for it, and nothing an outsider can use to probe.
            return jsonify(status="check-email"), 202
        send_verification(cur.lastrowid, email)
        return jsonify(status="check-email"), 202

    @app.post("/users/resend")
    def resend_verification():
        """A new link and passcode for an unverified account (the web service checked the password)."""
        if not mailer.available():
            abort(503, "Email is temporarily unavailable. Please try again later.")
        clean_up()
        row = conn().execute("SELECT * FROM user WHERE id = ?", (body().get("user_id"),)).fetchone()
        if row and not row["verified"] and not send_verification(row["id"], row["email"]):
            abort(429, "Too many emails for this account. Please wait an hour and try again.")
        return jsonify(status="check-email")

    def live_token(token):
        if not isinstance(token, str) or not token:
            return None
        return conn().execute("SELECT * FROM email_token WHERE token_hash = ? AND expires_at >= datetime('now') "
                              "AND tries < ?", (token_hash(token), VERIFY_MAX_TRIES)).fetchone()

    @app.post("/verify/check")
    def check_link():
        return jsonify(valid=live_token(body().get("token")) is not None)

    @app.post("/verify")
    def verify():
        b = body()
        clean_up()
        token, code = b.get("token"), b.get("code")
        code = code.strip() if isinstance(code, str) else ""
        row = live_token(token)
        if not row:
            abort(410, LINK_DEAD)
        if not hmac.compare_digest(code_hash(token, code), row["code_hash"]) or not CODE_RE.match(code):
            with conn():
                conn().execute("UPDATE email_token SET tries = tries + 1 WHERE id = ?", (row["id"],))
                tries = conn().execute("SELECT tries FROM email_token WHERE id = ?", (row["id"],)).fetchone()
                dead = tries is None or tries[0] >= VERIFY_MAX_TRIES
                if dead:
                    conn().execute("DELETE FROM email_token WHERE id = ?", (row["id"],))
            if dead:
                abort(410, "Too many wrong passcodes, so this link no longer works. "
                           "Sign in to get a new email.")
            abort(400, "That passcode isn't right. Please check the email and try again.")
        with conn():
            # Only one request can use the link: whoever deletes it goes on.
            if conn().execute("DELETE FROM email_token WHERE user_id = ?", (row["user_id"],)).rowcount == 0:
                abort(410, LINK_DEAD)
            conn().execute("UPDATE user SET verified = 1 WHERE id = ?", (row["user_id"],))
        u = conn().execute("SELECT * FROM user WHERE id = ?", (row["user_id"],)).fetchone()
        return jsonify(id=u["id"], username=u["username"], is_mod=bool(u["is_mod"]))

    @app.post("/login")
    def login():
        b = body()
        email = (b.get("email") or "").strip().lower()
        row = conn().execute("SELECT * FROM user WHERE email = ?", (email,)).fetchone()
        if not row or not check_password_hash(row["pw_hash"], b.get("password") or ""):
            abort(401, "Wrong email or password.")
        return jsonify(id=row["id"], username=row["username"], is_mod=bool(row["is_mod"]),
                       verified=bool(row["verified"]))

    # ---------- reading ----------
    @app.get("/measures/<measure_id>")
    def zone(measure_id):
        viewer = request.args.get("viewer", type=int)
        comments = conn().execute(
            "SELECT c.id, c.text, c.created_at, u.username, "
            "EXISTS(SELECT 1 FROM flag f WHERE f.comment_id = c.id AND f.user_id = ?) AS flagged_by_me "
            "FROM comment c JOIN user u ON u.id = c.user_id "
            "WHERE c.measure_id = ? AND c.hidden = 0 ORDER BY c.id", (viewer, measure_id)).fetchall()
        facts = conn().execute(
            "SELECT f.id, f.text, f.citation_url, f.status, f.created_at, u.username, "
            "(SELECT COUNT(*) FROM rating r WHERE r.fact_id = f.id AND r.helpful = 1) AS helpful, "
            "(SELECT COUNT(*) FROM rating r WHERE r.fact_id = f.id AND r.helpful = 0) AS not_helpful, "
            "EXISTS(SELECT 1 FROM rating r WHERE r.fact_id = f.id AND r.user_id = ?) AS rated_by_me "
            "FROM fact f JOIN user u ON u.id = f.user_id "
            "WHERE f.measure_id = ? AND f.status != 'rejected' "
            "ORDER BY CASE f.status WHEN 'vetted' THEN 0 WHEN 'bridged' THEN 1 ELSE 2 END, f.id",
            (viewer, measure_id)).fetchall()
        return jsonify(comments=[dict(r) for r in comments], facts=_with_official(facts))

    # ---------- comments ----------
    @app.post("/comments")
    def post_comment():
        b = body()
        u = user(b.get("user_id"))
        text = text_field(b, "text", MAX_COMMENT)
        measure_id = text_field(b, "measure_id", 64)
        with conn():
            cur = conn().execute("INSERT INTO comment (measure_id, user_id, text) VALUES (?, ?, ?)",
                                 (measure_id, u["id"], text))
        return jsonify(id=cur.lastrowid), 201

    @app.post("/comments/<int:comment_id>/flag")
    def flag_comment(comment_id):
        u = user(body().get("user_id"))
        established(u)
        c = conn().execute("SELECT * FROM comment WHERE id = ?", (comment_id,)).fetchone()
        if not c:
            abort(404, "No such comment.")
        with conn():
            conn().execute("INSERT OR IGNORE INTO flag (comment_id, user_id) VALUES (?, ?)", (comment_id, u["id"]))
            n = conn().execute("SELECT COUNT(*) FROM flag WHERE comment_id = ?", (comment_id,)).fetchone()[0]
            if n >= FLAGS_TO_HIDE and not c["reviewed"]:
                conn().execute("UPDATE comment SET hidden = 1 WHERE id = ?", (comment_id,))
        return jsonify(flags=n)

    # ---------- facts ----------
    @app.post("/facts")
    def submit_fact():
        b = body()
        u = user(b.get("user_id"))
        text = text_field(b, "text", MAX_FACT)
        measure_id = text_field(b, "measure_id", 64)
        url = text_field(b, "citation_url", 500)
        if not is_https_url(url):
            abort(400, "The citation must be a full https:// link.")
        try:
            check = bias.post("/check/text", {"text": text, "sources": [], "mode": "wording"})
        except ServiceError:
            abort(503, "Bias Buster is unavailable, so facts can't be submitted right now.")
        if check["verdict"] != "pass":
            words = "; ".join(f["detail"] for f in check["findings"])
            abort(400, f"Bias Buster: please state the fact neutrally ({words}).")
        with conn():
            cur = conn().execute(
                "INSERT INTO fact (measure_id, user_id, text, citation_url) VALUES (?, ?, ?, ?)",
                (measure_id, u["id"], text, url))
        return jsonify(id=cur.lastrowid, status="pending"), 201

    @app.post("/facts/<int:fact_id>/rate")
    def rate_fact(fact_id):
        b = body()
        u = user(b.get("user_id"))
        established(u)
        leaning = b.get("leaning")
        if leaning not in LEANINGS or b.get("helpful") not in (True, False):
            abort(400, "helpful (true/false) and leaning (yes/no/undecided) are required")
        f = conn().execute("SELECT * FROM fact WHERE id = ?", (fact_id,)).fetchone()
        if not f:
            abort(404, "No such fact.")
        if f["user_id"] == u["id"]:
            abort(400, "You can't rate your own fact.")
        with conn():
            conn().execute("INSERT OR REPLACE INTO rating (fact_id, user_id, helpful, leaning) VALUES (?, ?, ?, ?)",
                           (fact_id, u["id"], int(b["helpful"]), leaning))
            # Bridging consensus: found helpful by people who lean opposite ways on this measure.
            sides = {r[0] for r in conn().execute(
                "SELECT DISTINCT leaning FROM rating WHERE fact_id = ? AND helpful = 1", (fact_id,))}
            if f["status"] == "pending" and {"yes", "no"} <= sides:
                conn().execute("UPDATE fact SET status = 'bridged' WHERE id = ?", (fact_id,))
        status = conn().execute("SELECT status FROM fact WHERE id = ?", (fact_id,)).fetchone()[0]
        return jsonify(status=status)

    # ---------- moderation ----------
    @app.get("/moderation")
    def queue():
        moderator(request.args.get("user_id", type=int))
        comments = conn().execute(
            "SELECT c.id, c.measure_id, c.text, c.hidden, u.username, "
            "(SELECT COUNT(*) FROM flag f WHERE f.comment_id = c.id) AS flags "
            "FROM comment c JOIN user u ON u.id = c.user_id "
            "WHERE c.reviewed = 0 AND (SELECT COUNT(*) FROM flag f WHERE f.comment_id = c.id) > 0 "
            "ORDER BY flags DESC").fetchall()
        facts = conn().execute(
            "SELECT f.id, f.measure_id, f.text, f.citation_url, f.status, u.username FROM fact f "
            "JOIN user u ON u.id = f.user_id WHERE f.status IN ('bridged', 'pending') "
            "ORDER BY f.status = 'bridged' DESC, f.id").fetchall()
        return jsonify(comments=[dict(r) for r in comments], facts=_with_official(facts))

    @app.post("/moderation/comments/<int:comment_id>")
    def moderate_comment(comment_id):
        b = body()
        moderator(b.get("user_id"))
        action = {"hide": (1, 1), "restore": (0, 1)}.get(b.get("action"))
        if not action:
            abort(400, "action must be hide or restore")
        with conn():
            conn().execute("UPDATE comment SET hidden = ?, reviewed = ? WHERE id = ?", (*action, comment_id))
        return jsonify(ok=True)

    @app.post("/moderation/facts/<int:fact_id>")
    def moderate_fact(fact_id):
        b = body()
        moderator(b.get("user_id"))
        new = {"publish": "vetted", "reject": "rejected"}.get(b.get("action"))
        if not new:
            abort(400, "action must be publish or reject")
        f = conn().execute("SELECT status FROM fact WHERE id = ?", (fact_id,)).fetchone()
        if not f:
            abort(404, "No such fact.")
        if new == "vetted" and f["status"] != "bridged":
            abort(400, "Only facts with bridging consensus can be published.")
        with conn():
            conn().execute("UPDATE fact SET status = ? WHERE id = ?", (new, fact_id))
        return jsonify(status=new)

    return app
