"""Spanish and Chinese prepared answers: translated only from a checked English answer, stored only after
the number check and the review pass, and served only while the English answer is unchanged."""

import itertools
import json
import logging

import pytest
import requests

from thinkballot import ai, config
from thinkballot.services.ask import app as ask_app
from thinkballot.services.ask import cache, translate
from thinkballot.services.ballot import db
from thinkballot.servicekit import ServiceClient
from thinkballot.suggested import SUGGESTED_QUESTIONS

QUESTION = SUGGESTED_QUESTIONS[0]
_clients = itertools.count(1)
# The stub answer quotes the first official passage of prop-a, its measure type.
EN_QUOTE = "Placeholder initiative statute."
OFFICIAL = {"es": "Ley de iniciativa de ejemplo.", "zh": "範例創制法規。"}


def ask(server, question=QUESTION, lang=None, suggested=None):
    body = {"measure_id": "prop-a", "question": question, "client": f"10.8.{next(_clients)}.1"}
    if lang:
        body.update(lang=lang, suggested=suggested if suggested is not None else SUGGESTED_QUESTIONS.index(question))
    return requests.post(server + "/svc/ask/ask", json=body, headers={"X-TB-Internal": config.INTERNAL_TOKEN}).json()


def translations():
    with cache._connect() as conn:
        return conn.execute("SELECT lang, translate_model, check_model, points FROM translation").fetchall()


def prepare(lang="es"):
    ballot, bias = ServiceClient("ballot"), ServiceClient("bias")
    return ask_app.prepare_translation(ask_app.load_measure(ballot, "prop-a"), QUESTION, lang, bias, ballot)


@pytest.fixture(autouse=True)
def fresh(server, monkeypatch):
    """An empty cache, an English prepared answer for prop-a, and official translations of its measure type."""
    with cache._connect() as conn:
        conn.execute("DELETE FROM answer")
        conn.execute("DELETE FROM translation")
    monkeypatch.setattr(config, "ASK_LIMITS_PER_CLIENT", [(1000, 60)])  # many questions, quickly
    monkeypatch.setattr(config, "ASK_LIMITS_SITEWIDE", [(1000, 60)])
    conn = db.connect()
    with conn:
        for lang, text in OFFICIAL.items():
            conn.execute("INSERT OR REPLACE INTO translation VALUES (?, ?, ?, ?, ?, ?)",
                         ("prop-a", lang, "measure_type", text, f"https://example.invalid/guide-{lang}.pdf",
                          "Placeholder translated guide"))
    assert ask(server)["status"] == "answered"  # the English answer, now prepared
    yield server
    with conn:
        conn.execute("DELETE FROM translation WHERE measure_id = 'prop-a' AND name = 'measure_type'")
    conn.close()


# ---------- the checks ----------

@pytest.mark.parametrize("english,translated,lang,ok", [
    ("It costs $1.5 billion over 30 years.", "Cuesta $1.5 mil millones durante 30 años.", "es", True),
    ("It costs $1.5 billion over 30 years.", "Cuesta $1,500 millones durante 30 años.", "es", True),
    ("It costs $1.5 billion over 30 years.", "Cuesta $1.5 millones durante 30 años.", "es", False),
    ("It costs $1.5 billion over 30 years.", "Cuesta $1.5 mil millones durante 25 años.", "es", False),
    ("It costs $1.5 billion over 30 years.", "Cuesta $1.5 mil millones.", "es", False),  # a number dropped
    ("It costs $1.5 billion.", "Cuesta $1.5 mil millones durante 30 años.", "es", False),  # a number added
    ("Grants rise to $50,000 per school.", "Las becas suben a $50,000 por escuela.", "es", True),
    ("It costs $1.5 billion over 30 years.", "30 年內花費 15 億美元。", "zh", True),
    ("It costs $1.5 billion over 30 years.", "30 年內花費 1.5 億美元。", "zh", False),
    ("$500 million to $600 million a year.", "每年 5 億美元到 6 億美元。", "zh", True),
    ("$500 million to $600 million a year.", "每年 5 億到 6 億美元。", "zh", False),  # one amount without its unit
    ("$500 million to $600 million a year.", "每年 5 到 6 億美元。", "zh", False),  # "5" alone is not 500 million
    ("Grants rise to $50,000 per school.", "每所學校的補助增加到 5 萬美元。", "zh", True),
    ("Rates rise 12.5% on November 3, 2026.", "2026年11月3日利率上升１２.５％。", "zh", True),  # full-width digits
    ("Two members join the board.", "董事會增加 2 名成員。", "zh", False),  # a number word turned into digits
    # swapped numbers: the same values, counting different things
    ("It costs $500 over 30 years.", "Cuesta $30 durante 500 años.", "es", False),
    ("Rates rise 5% for 10 years.", "Las tasas suben 10% durante 5 años.", "es", False),
    ("It costs $500 over 30 years.", "30 年內花費 500 美元。", "zh", True),  # order may change; kinds don't
    ("Rates rise 12.5%.", "Las tasas suben 12.5 por ciento.", "es", True),
    # numbers written as words
    ("Two thirds of voters must approve.", "Tres cuartos de los votantes deben aprobarla.", "es", False),
    ("Two thirds of voters must approve.", "Dos tercios de los votantes deben aprobarla.", "es", True),
    ("Two thirds of voters must approve.", "需要三分之二的選民批准。", "zh", True),
    ("Two thirds of voters must approve.", "需要四分之三的選民批准。", "zh", False),
    ("It costs $500 million.", "花費五億美元。", "zh", False),  # Chinese numerals for a digit amount
    ("Members serve on the board.", "成員在董事會任職三年。", "zh", False),  # 三 added
    ("Members serve on the board.", "Los miembros sirven tres años en la junta.", "es", False),  # tres added
    ("Members serve a third term.", "Los miembros cumplen un tercer mandato.", "es", True),  # ordinals not counted
    ("It applies in San Francisco.", "適用於三藩市。", "zh", True),  # a place name, not a number
    ("A bipartisan board of 7 members.", "由 7 名成員組成的兩黨委員會。", "zh", True),  # 兩黨 is not "two"
    ("Half of the money goes to schools.", "一半的資金用於學校。", "zh", True),
    # a month becomes a number only in a real date
    ("The vote is on November 3, 2026.", "投票日期是 2026 年 11 月 3 日。", "zh", True),
    ("The board may meet 3 times.", "董事會可能開會 3 次，5 月。", "zh", False),
])
def test_numbers_must_match_by_value(english, translated, lang, ok):
    assert translate.numbers_match(english, translated, lang) is ok


def test_official_quote_only_when_word_for_word():
    field = "Aumento de costos para el estado de entre $500 millones y $600 millones anuales durante aproximadamente 25 años."
    assert translate.official_quote_ok("entre $500 millones y $600 millones anuales durante", field)
    assert translate.official_quote_ok("entre $500 millones y\n $600   millones anuales durante", field)  # whitespace
    assert not translate.official_quote_ok("entre $500 millones y $700 millones anuales durante", field)
    assert not translate.official_quote_ok("entre $500 millones ... anuales durante aproximadamente", field)
    assert not translate.official_quote_ok("Aumento de costos", field)  # too short to support a claim
    assert not translate.official_quote_ok("ento de costos para el estado de entre", field)  # part of a word
    zh = "州政府每年增加 5 到 6 億美元的成本，用於償還住房債券，持續約25 年。"
    assert translate.official_quote_ok("用於償還住房債券，持續約25年。", zh)
    assert not translate.official_quote_ok("用於償還住房的債券，持續約25年。", zh)


# ---------- storing ----------

def test_translation_is_stored_after_both_checks_with_its_models(fresh):
    assert prepare("es") == "translated"
    [(lang, model, check_model, points)] = translations()
    assert (lang, model, check_model) == ("es", config.TRANSLATE_MODEL, config.TRANSLATE_CHECK_MODEL)
    [point] = json.loads(points)
    assert point["claim"].startswith("[es] ") and point["quote"] == OFFICIAL["es"] and point["quote_lang"] == "es"
    assert prepare("es") == "cached"


def test_number_mismatch_is_rejected(fresh, monkeypatch):
    monkeypatch.setattr(translate, "_stub_translate",
                        lambda user: {"points": [{"claim": "Cuesta 7 dólares.", "quote": ""}]})
    assert prepare("es") == "rejected-number"
    assert translations() == []


def test_reviewer_failure_is_rejected(fresh, monkeypatch):
    monkeypatch.setattr(translate, "_stub_check",
                        lambda user: {"points": [{"ok": False, "problem": "adds a judgement"}]})
    assert prepare("zh") == "rejected-review"
    assert translations() == []


def test_reviewer_without_a_clear_pass_is_rejected(fresh, monkeypatch):
    monkeypatch.setattr(translate, "_stub_check", lambda user: {"points": [{"ok": "yes"}]})
    assert prepare("es") == "rejected-review"
    monkeypatch.setattr(translate, "_stub_check", lambda user: {"points": []})
    assert prepare("es") == "rejected-review"
    assert translations() == []


def test_altered_official_quote_falls_back_to_the_english_quote(fresh, monkeypatch):
    real = translate._stub_translate
    monkeypatch.setattr(translate, "_stub_translate", lambda user: {"points": [
        dict(p, quote=p["quote"].replace("ejemplo", "muestra")) for p in real(user)["points"]]})
    assert prepare("es") == "translated"
    [point] = json.loads(translations()[0][3])
    assert point["quote"] == EN_QUOTE and point["quote_lang"] == "en"


def test_without_an_english_answer_nothing_is_translated(fresh, monkeypatch):
    with cache._connect() as conn:
        conn.execute("DELETE FROM answer")
    calls = []
    monkeypatch.setattr(ai, "chat_json", lambda *a, **k: calls.append(a[0]))
    assert prepare("es") == "no-english" and calls == [] and translations() == []


# ---------- serving ----------

def test_suggested_question_on_a_spanish_page_gets_the_spanish_answer(fresh):
    prepare("es")
    r = requests.post(fresh + "/es/api/ask", json={"measure_id": "prop-a", "question": QUESTION, "suggested": 0}).json()
    assert r["status"] == "answered" and r["translated"] is True and r["lang"] == "es" and r["prepared"]
    [point] = r["points"]
    assert point["claim"].startswith("[es] The official text says")
    assert point["quote"] == OFFICIAL["es"] and point["quote_lang"] == "es"
    assert point["source_url"] == "https://example.invalid/guide-es.pdf"


def test_button_number_finds_the_answer_whatever_text_is_sent(fresh):
    prepare("zh")
    r = ask(fresh, question="這項議案通過後會有什麼改變？", lang="zh", suggested=0)
    assert r["translated"] is True and r["points"][0]["claim"].startswith("[zh] ")


def test_english_answer_when_there_is_no_translation(fresh):
    r = ask(fresh, lang="es")
    assert r["status"] == "answered" and r["translated"] is False and r["points"][0]["quote"] == EN_QUOTE


def test_typed_question_is_unchanged(fresh):
    prepare("es")
    r = requests.post(fresh + "/es/api/ask", json={"measure_id": "prop-a", "question": QUESTION}).json()
    assert "translated" not in r and r["points"][0]["claim"].startswith("The official text says")
    typed = requests.post(fresh + "/es/api/ask", json={"measure_id": "prop-a", "question": "What does it do?"}).json()
    assert "translated" not in typed and "prepared" not in typed


def test_stale_translation_is_ignored(fresh):
    prepare("es")
    with cache._connect() as conn:
        conn.execute("UPDATE translation SET english_hash = 'made-from-an-older-answer'")
    assert ask(fresh, lang="es")["translated"] is False


def test_translation_of_a_replaced_english_answer_is_ignored(fresh):
    prepare("es")
    with cache._connect() as conn:  # the English answer changed after the translation was made
        result = json.loads(conn.execute("SELECT result FROM answer").fetchone()[0])
        result["points"][0]["claim"] = "A different English claim."
        conn.execute("UPDATE answer SET result = ?", (json.dumps(result),))
    assert ask(fresh, lang="es")["translated"] is False


@pytest.mark.parametrize("setting", ["TRANSLATE_MODEL", "TRANSLATE_CHECK_MODEL"])
def test_changed_translation_model_is_not_served(fresh, monkeypatch, setting):
    prepare("es")
    monkeypatch.setattr(config, setting, "another/model")
    assert ask(fresh, lang="es")["translated"] is False


def test_changed_official_translation_falls_back_to_the_english_quote(fresh):
    prepare("es")
    conn = db.connect()
    with conn:
        conn.execute("UPDATE translation SET text = 'Otra ley.' WHERE measure_id = 'prop-a' AND name = 'measure_type' "
                     "AND lang = 'es'")
    conn.close()
    point = ask(fresh, lang="es")["points"][0]
    assert point["claim"].startswith("[es] ") and point["quote"] == EN_QUOTE and point["quote_lang"] == "en"


def test_fixed_refusal_is_shown_from_the_catalog(fresh, monkeypatch):
    with cache._connect() as conn:
        conn.execute("DELETE FROM answer")
    monkeypatch.setattr(ask_app, "_stub_answer", lambda user: {"refused": True, "reason": "x"})
    measure = ask_app.load_measure(ServiceClient("ballot"), "prop-a")
    ask_app.live_answer(measure, QUESTION, ServiceClient("bias"), store_refusals=True)  # as the warm script does
    r = requests.post(fresh + "/zh/api/ask", json={"measure_id": "prop-a", "question": QUESTION, "suggested": 0}).json()
    assert r["status"] == "refused" and r["reason"].startswith("官方指南沒有回答這個問題")
    assert prepare("zh") == "refused" and translations() == []


# ---------- warm script ----------

def test_warm_script_translates_and_then_skips(fresh, monkeypatch, caplog):
    from test_ask_cache import _load_warm_script
    script = _load_warm_script()
    assert script.parse_langs(["es,zh", "es"]) == ["es", "zh"] and script.parse_langs(None) == ["en"]
    ballot, bias = ServiceClient("ballot"), ServiceClient("bias")
    calls = []
    real = ai.chat_json
    monkeypatch.setattr(ai, "chat_json", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    with caplog.at_level(logging.INFO, logger="thinkballot.warm"):
        assert script.warm_translations(ballot, bias, "es", pause=0) == 0
    # one translation and one review, for the only English answer there is; the answer model is never asked
    assert [c.split("\n")[0] for c in calls] == [s.split("\n")[0] for s in (translate.TRANSLATE_SYSTEM,
                                                                             translate.CHECK_SYSTEM)]
    assert "measure=prop-a q=0 lang=es status=translated" in caplog.text
    assert "status=no-english" in caplog.text
    calls.clear()
    assert script.warm_translations(ballot, bias, "es", pause=0) == 0
    assert calls == []


# ---------- review fixes ----------

def post(server, **body):
    body = dict({"measure_id": "prop-a", "question": QUESTION, "client": f"10.7.{next(_clients)}.1"}, **body)
    return requests.post(server + "/svc/ask/ask", json=body, headers={"X-TB-Internal": config.INTERNAL_TOKEN}).json()


@pytest.mark.parametrize("suggested", [3, -1, True, False, "0", 0.0, None])
def test_invalid_suggested_number_is_a_typed_question(fresh, suggested):
    prepare("es")
    r = post(fresh, lang="es", suggested=suggested)
    assert r["status"] == "answered" and "translated" not in r


@pytest.mark.parametrize("lang", ["en", "fr", ["es"], None, 1])
def test_other_languages_get_no_translation(fresh, lang):
    prepare("es")
    r = post(fresh, lang=lang, suggested=0)
    assert r["status"] == "answered" and "translated" not in r


def test_official_quote_with_other_numbers_falls_back_to_english(fresh):
    conn = db.connect()
    with conn:  # the stub copies the whole official field: here it has a number the English quote lacks
        conn.execute("UPDATE translation SET text = 'Ley de iniciativa de ejemplo con 5 artículos.' "
                     "WHERE measure_id = 'prop-a' AND name = 'measure_type' AND lang = 'es'")
    conn.close()
    assert prepare("es") == "translated"
    [point] = json.loads(translations()[0][3])
    assert point["quote"] == EN_QUOTE and point["quote_lang"] == "en"


def test_official_quote_of_a_different_passage_falls_back_to_english(fresh, monkeypatch):
    seen = []

    def check(user):
        seen.extend(json.loads(user)["points"])  # the reviewer gets both quotes
        return {"points": [{"ok": True, "quote_ok": False}]}
    monkeypatch.setattr(translate, "_stub_check", check)
    assert prepare("es") == "translated"  # the claim passed; only the quote is not used
    assert seen[0]["english_quote"] == EN_QUOTE and seen[0]["official_quote"] == OFFICIAL["es"]
    [point] = json.loads(translations()[0][3])
    assert point["quote"] == EN_QUOTE and point["quote_lang"] == "en"


def test_english_quote_source_is_named_in_the_page_language(fresh, monkeypatch):
    monkeypatch.setattr(translate, "_stub_check", lambda user: {"points": [{"ok": True, "quote_ok": False}]})
    prepare("es")
    r = requests.post(fresh + "/es/api/ask", json={"measure_id": "prop-a", "question": QUESTION, "suggested": 0}).json()
    [point] = r["points"]
    assert point["quote_lang"] == "en" and point["source_label"] == "Tipo de medida"


def test_changed_rules_retire_stored_translations(fresh, monkeypatch):
    prepare("es")
    assert ask(fresh, lang="es")["translated"] is True
    monkeypatch.setattr(translate, "RULES", "next-rules")
    assert ask(fresh, lang="es")["translated"] is False
    assert prepare("es") == "translated"


def test_stub_answers_never_share_keys_with_real_ones(fresh, monkeypatch):
    stub_key = cache.make_key("prop-a", QUESTION, "text")
    monkeypatch.setattr(config, "AI_PROVIDER", "openrouter")
    assert cache.make_key("prop-a", QUESTION, "text") != stub_key


def test_warm_translations_stop_after_errors_in_a_row(fresh, monkeypatch):
    from test_ask_cache import _load_warm_script
    warm_translations = _load_warm_script().warm_translations
    ballot, bias = ServiceClient("ballot"), ServiceClient("bias")

    def run(statuses, max_errors):
        calls = iter(statuses)

        def fake(*_args):
            status = next(calls)
            if status == "error":
                raise ai.AIError("HTTP 503")
            return status
        monkeypatch.setattr(ask_app, "prepare_translation", fake)
        missing = warm_translations(ballot, bias, "es", pause=0, max_errors=max_errors)
        return missing, len(statuses) - len(list(calls))

    assert run(["error"] * 6, 3) == (3, 3)  # stops after three errors in a row
    # a rejected translation is an answer from the models, not an error: the count starts again
    assert run(["error", "error", "rejected-review", "error", "error", "error"], 3) == (6, 6)
    # skipped items make no AI call, so they neither count nor reset the count
    assert run(["error", "translated", "error", "cached", "error", "translated"], 2) == (3, 5)


def test_warm_logs_a_measure_that_cannot_be_loaded(fresh, monkeypatch, caplog):
    from werkzeug.exceptions import ServiceUnavailable

    from test_ask_cache import _load_warm_script
    script = _load_warm_script()

    def unavailable(*_args):
        raise ServiceUnavailable()
    monkeypatch.setattr(ask_app, "load_measure", unavailable)
    with caplog.at_level(logging.INFO, logger="thinkballot.warm"):
        assert script.warm_translations(ServiceClient("ballot"), ServiceClient("bias"), "es", pause=0,
                                        max_errors=2) == 2
        assert script.warm(ServiceClient("ballot"), ServiceClient("bias"), pause=0, max_errors=2) == 2
    assert caplog.text.count("status=error-503") == 4


# ---------- the Ask box (static/app.js, run in Node with a small stand-in for the page) ----------

JS_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
function el(extra) {
  const listeners = {};
  return Object.assign({
    dataset: {}, style: {}, innerHTML: "", value: "", disabled: false, hidden: false,
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    fire(type, ev) { (listeners[type] || []).forEach((fn) => fn(ev || { preventDefault() {} })); },
    setAttribute() {}, removeAttribute() {}, blur() {}, scrollIntoView() {},
    getBoundingClientRect() { return { top: 0 }; },
    querySelector() { return el(); }, querySelectorAll() { return []; },
  }, extra || {});
}
// esc() relies on the browser's textContent -> innerHTML escaping of &, < and >
const document = {
  body: el({ dataset: { prefix: "/es", i18n: JSON.stringify({ translated: "TRADUCIDO", in_english: "EN INGLES" }) } }),
  documentElement: { lang: "es" },
  createElement() {
    let t = "";
    return { set textContent(v) { t = v; },
             get innerHTML() { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); } };
  },
  addEventListener() {},
};
const question = el();
const form = el({ dataset: { measure: "prop-a" }, question, button: el() });
form.querySelector = () => form.button;
form.requestSubmit = () => form.fire("submit");
const buttons = [0, 1, 2].map((i) => el({ dataset: { index: String(i), question: "Q" + i } }));
const out = el();
document.querySelector = (sel) => ({ ".ask-form": form, ".ask-result": out }[sel] || null);
document.querySelectorAll = (sel) => (sel === ".suggest" ? buttons : []);
const bodies = [];
const ctx = {
  document, console, JSON, setTimeout, clearTimeout, setInterval, clearInterval, AbortController,
  window: { matchMedia: () => ({ matches: true }), innerHeight: 800 }, localStorage: { getItem() {}, setItem() {} },
  fetch: async (_url, opts) => { bodies.push(JSON.parse(opts.body)); return { json: async () => ({ status: "refused", reason: "x" }) }; },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const tick = () => new Promise((r) => setTimeout(r, 0));
(async () => {
  const evil = '<script>alert(1)</script> "quoted" \'single\'';
  const html = vm.runInContext("renderAnswer", ctx)({
    status: "answered", verdict: "pass", findings: [], translated: true, prepared: null,
    points: [{ claim: evil, quote: evil, quote_lang: "en", source_url: 'https://x.invalid/"><b>', source_label: evil }],
  }, true);
  vm.runInContext("initAsk", ctx)();
  buttons[1].fire("click");  // asks at once, with the button's number
  await tick(); await tick();
  question.value = "a typed question";
  question.fire("input");
  form.fire("submit");
  await tick(); await tick();
  form.requestSubmit = () => {};  // a click that has not been sent yet, then typing in the box
  buttons[2].fire("click");
  question.value = "Q2 and more";
  question.fire("input");
  form.fire("submit");
  await tick(); await tick();
  console.log(JSON.stringify({ html, bodies }));
})();
"""


@pytest.fixture(scope="module")
def ask_box(tmp_path_factory):
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed")
    harness = tmp_path_factory.mktemp("js") / "harness.js"
    harness.write_text(JS_HARNESS)
    app_js = config.ROOT / "thinkballot" / "services" / "web" / "static" / "app.js"
    run = subprocess.run(["node", str(harness), str(app_js)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_translated_answer_is_escaped(ask_box):
    html = ask_box["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert '"quoted"' not in html and "&quot;quoted&quot;" in html and "&#39;single&#39;" in html
    assert 'href="https://x.invalid/&quot;&gt;&lt;b&gt;"' in html
    assert '<blockquote lang="en">' in html and "TRADUCIDO" in html  # English quote marked; the label


def test_suggested_number_is_sent_only_for_the_button(ask_box):
    first, typed, edited = ask_box["bodies"]
    assert first == {"measure_id": "prop-a", "question": "Q1", "suggested": 1}
    assert typed == {"measure_id": "prop-a", "question": "a typed question"}
    assert edited == {"measure_id": "prop-a", "question": "Q2 and more"}  # typing cleared the number
