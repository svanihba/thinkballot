"""Accounts, post-moderated comments, and bridging consensus for community facts."""

import re

import pytest
import requests

from thinkballot import config
from thinkballot.servicekit import ServiceClient, ServiceError


@pytest.fixture(scope="module")
def svc(server):
    return ServiceClient("community")


def make_user(svc, name, established=True):
    u = svc.post("/users", {"email": f"{name}@example.com", "username": name, "password": "password123"})
    if established:  # flags and ratings count only from accounts older than an hour
        from thinkballot import config
        from thinkballot.services.community import db
        with db.connect(config.COMMUNITY_DB_PATH) as conn:
            conn.execute("UPDATE user SET created_at = datetime('now', '-2 hours') WHERE id = ?", (u["id"],))
    return u


def test_community_service_rejects_outside_callers(server):
    r = requests.post(server + "/svc/community/comments", json={"user_id": 1, "measure_id": "prop-a", "text": "x"})
    assert r.status_code == 403


def test_signup_login_and_email_is_never_shown(svc, server):
    u = make_user(svc, "alex")
    assert svc.post("/login", {"email": "ALEX@example.com", "password": "password123"})["id"] == u["id"]
    with pytest.raises(ServiceError) as exc:
        svc.post("/login", {"email": "alex@example.com", "password": "wrong-password"})
    assert exc.value.status == 401
    svc.post("/comments", {"user_id": u["id"], "measure_id": "prop-a", "text": "Hello"})
    assert "alex@example.com" not in requests.get(server + "/prop/prop-a").text


def test_new_accounts_cannot_flag(svc):
    author, fresh = make_user(svc, "author0"), make_user(svc, "fresh0", established=False)
    cid = svc.post("/comments", {"user_id": author["id"], "measure_id": "prop-a", "text": "Hi"})["id"]
    with pytest.raises(ServiceError) as exc:
        svc.post(f"/comments/{cid}/flag", {"user_id": fresh["id"]})
    assert exc.value.status == 403


def test_five_flags_hide_a_comment_until_a_moderator_restores_it(svc):
    author = make_user(svc, "author1")
    flaggers = [make_user(svc, f"flagger{i}") for i in range(5)]
    cid = svc.post("/comments", {"user_id": author["id"], "measure_id": "prop-b", "text": "Hot take"})["id"]
    visible = lambda: [c["id"] for c in svc.get("/measures/prop-b")["comments"]]  # noqa: E731
    for f in flaggers[:4]:
        svc.post(f"/comments/{cid}/flag", {"user_id": f["id"]})
    assert cid in visible()
    svc.post(f"/comments/{cid}/flag", {"user_id": flaggers[4]["id"]})
    assert cid not in visible()

    from thinkballot import config
    from thinkballot.services.community import db
    with db.connect(config.COMMUNITY_DB_PATH) as conn:
        conn.execute("UPDATE user SET is_mod = 1 WHERE id = ?", (author["id"],))
    with pytest.raises(ServiceError):  # moderation needs a moderator
        svc.post(f"/moderation/comments/{cid}", {"user_id": flaggers[0]["id"], "action": "restore"})
    svc.post(f"/moderation/comments/{cid}", {"user_id": author["id"], "action": "restore"})
    assert cid in visible()


def test_fact_needs_https_source_and_neutral_wording(svc):
    u = make_user(svc, "facter")
    base = {"user_id": u["id"], "measure_id": "prop-a"}
    with pytest.raises(ServiceError, match="https"):
        svc.post("/facts", {**base, "text": "The grant is $50.", "citation_url": "ftp://x"})
    with pytest.raises(ServiceError, match="Bias Buster"):
        svc.post("/facts", {**base, "text": "This disastrous plan costs $50.", "citation_url": "https://lao.ca.gov/x"})
    svc.post("/facts", {**base, "text": "The grant is $50.", "citation_url": "https://example.com/news"})
    facts = svc.get("/measures/prop-a")["facts"]
    assert [f["official_source"] for f in facts if f["text"] == "The grant is $50."] == [False]


def test_bridging_needs_helpful_ratings_from_both_leanings(svc):
    author, mod = make_user(svc, "factauthor"), make_user(svc, "factmod")
    yes1, yes2, no1 = (make_user(svc, n) for n in ("ryes1", "ryes2", "rno1"))
    fid = svc.post("/facts", {"user_id": author["id"], "measure_id": "prop-b",
                              "text": "The bonds total $1.5 billion.",
                              "citation_url": "https://lao.ca.gov/ballot"})["id"]
    rate = lambda u, leaning: svc.post(f"/facts/{fid}/rate",  # noqa: E731
                                       {"user_id": u["id"], "helpful": True, "leaning": leaning})["status"]
    assert rate(yes1, "yes") == "pending"
    assert rate(yes2, "yes") == "pending"  # same side twice is not bridging
    assert rate(no1, "no") == "bridged"

    from thinkballot import config
    from thinkballot.services.community import db
    with db.connect(config.COMMUNITY_DB_PATH) as conn:
        conn.execute("UPDATE user SET is_mod = 1 WHERE id = ?", (mod["id"],))
    assert svc.post(f"/moderation/facts/{fid}", {"user_id": mod["id"], "action": "publish"})["status"] == "vetted"
    fact = next(f for f in svc.get("/measures/prop-b")["facts"] if f["id"] == fid)
    assert fact["status"] == "vetted" and fact["official_source"] is True


def test_community_closed_by_default_hides_accounts_and_posting(server, monkeypatch):
    monkeypatch.setattr(config, "COMMUNITY_OPEN", False)
    page = requests.get(server + "/signin").text
    assert "opens after the election" in page and 'name="password"' not in page
    assert requests.post(server + "/signin", data={"action": "signup"}, allow_redirects=False).status_code == 404
    assert requests.post(server + "/prop/prop-a/comment", data={"text": "hi"}, allow_redirects=False).status_code == 404
    html = requests.get(server + "/prop/prop-a").text
    assert "Community discussion opens after the election." in html and "sign in</a>" not in html


def test_web_sign_in_flow_and_csrf(server, monkeypatch):
    monkeypatch.setattr(config, "COMMUNITY_OPEN", True)
    s = requests.Session()
    page = s.get(server + "/signin").text
    token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    assert s.post(server + "/signin", data={"csrf": token, "action": "signup", "email": "web@example.com",
                                            "username": "webuser", "password": "password123"}).status_code == 200
    assert s.post(server + "/signin", data={"action": "signup"}, allow_redirects=False).status_code == 400  # no token
    html = s.get(server + "/prop/prop-a").text
    assert "@webuser · sign out" in html
    token = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    s.post(server + "/prop/prop-a/comment", data={"csrf": token, "text": "First real comment"})
    assert "First real comment" in s.get(server + "/prop/prop-a").text
