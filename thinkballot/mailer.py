"""Sends ThinkBallot's few emails (account verification). Plain text only.

Backend from TB_MAIL_BACKEND:
- "smtp": the provider in TB_SMTP_HOST / TB_SMTP_PORT, always encrypted (STARTTLS on 587, TLS on 465),
  signed in with TB_SMTP_USER / TB_SMTP_PASSWORD, sent from TB_MAIL_FROM.
- "file": development only. Each message is written to TB_MAIL_DIR (default instance/mail/) so a
  developer can open the link.
- "none" (default): sends nothing; available() is False, so sign-up stays closed rather than creating
  accounts nobody can verify.

One log line per attempt, with the recipient masked. Message bodies (which carry links and passcodes)
and the SMTP password are never logged.
"""

import logging
import secrets
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import config

log = logging.getLogger("thinkballot.mail")
RETRY_DELAY_SECONDS = 2


def mask(address):
    """"alex@example.com" -> "a***@example.com": enough to tell messages apart, not the address."""
    local, _, domain = (address or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def available():
    """Whether email can be sent at all with the current settings."""
    backend = config.MAIL_BACKEND
    if backend == "smtp":
        return bool(config.SMTP_HOST and config.MAIL_FROM)
    return backend == "file"


def _message(to, subject, body):
    msg = EmailMessage()
    sender = config.MAIL_FROM or "ThinkBallot <noreply@localhost>"
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2].strip("> ") or "localhost")
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body)
    return msg


def _send_smtp(msg):
    timeout = config.MAIL_TIMEOUT_SECONDS
    context = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=timeout)
    with server:
        if config.SMTP_PORT != 465:
            server.starttls(context=context)  # refuses to go on unencrypted if the server can't
        if config.SMTP_USER:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
        server.send_message(msg)


def _send_file(msg):
    config.MAIL_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns()}-{secrets.token_hex(4)}.eml"  # sorts oldest first
    tmp = config.MAIL_DIR / (name + ".part")
    tmp.touch(mode=0o600)
    tmp.write_bytes(bytes(msg))
    tmp.rename(config.MAIL_DIR / name)  # appears whole, never half written


def send(to, subject, body):
    """Send one message now, with one retry. Returns True if it was handed to the backend."""
    backend = config.MAIL_BACKEND
    if not available():
        log.warning("mail backend=%s to=%s not sent: email is not configured", backend, mask(to))
        return False
    msg = _message(to, subject, body)
    deliver = _send_smtp if backend == "smtp" else _send_file
    for attempt in (1, 2):
        started = time.monotonic()
        try:
            deliver(msg)
        except (smtplib.SMTPException, OSError) as exc:
            # The exception type only: SMTP replies can echo account details.
            log.warning("mail backend=%s to=%s attempt=%d failed: %s", backend, mask(to), attempt,
                        type(exc).__name__)
            if attempt == 1:
                time.sleep(RETRY_DELAY_SECONDS)
            continue
        log.info("mail backend=%s to=%s sent in %.0f ms", backend, mask(to),
                 (time.monotonic() - started) * 1000)
        return True
    return False


def send_later(to, subject, body):
    """Send in the background, so the caller answers at once (and in the same time whether or not
    an email goes out)."""
    thread = threading.Thread(target=send, args=(to, subject, body), name="mail", daemon=True)
    thread.start()
    return thread
