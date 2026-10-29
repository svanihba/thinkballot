"""Spanish and Chinese: official text from the Secretary of State's official translations, verified word
for word; interface text from the catalogs; English pages unchanged."""

import ast
import json
import re
import string
from pathlib import Path

import pytest
import requests
from jinja2 import Environment, nodes

from pipeline.extract import ca_sos_guide_translated as translated
from pipeline.extract import pdf_cid
from thinkballot.services.bias import checks
from thinkballot.services.web import i18n

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
WEB = ROOT / "thinkballot" / "services" / "web"
QRG = {"es": FIXTURES / "sos_quick_reference_guide_es_2026-11.pdf",  # the Secretary of State's PDFs,
       "zh": FIXTURES / "sos_quick_reference_guide_zh_2026-11.pdf"}  # byte for byte as crawled
NUMBERS = ["1", "2", "3", "4", "5", "37", "38", "39", "40", "41", "42", "43", "44", "45"]
SHORT_FIELDS = ["summary", "yes_means", "no_means", "fiscal_effect", "argument_for", "argument_against",
                "supporters", "opponents"]


# ---------- official translations: extraction and word-for-word verification ----------

@pytest.fixture(scope="module", params=["es", "zh"])
def guide(request):
    lang = request.param
    body = QRG[lang].read_bytes()
    url = f"{translated.CDN}/{translated.LAYOUTS[lang]['folder']}/pdf/{translated.QRG}"
    records = translated.extract({url: {"body": body}},
                                 lambda text, src, label: {"text": text, "source_url": src, "source_label": label})
    return lang, records, pdf_cid.pdf_text(body)


def test_every_proposition_has_every_short_field(guide):
    lang, records, _ = guide
    assert [r["translation_of"] for r in records] == [f"prop-{n}" for n in NUMBERS]
    for r in records:
        assert r["language"] == lang
        assert set(r["fields"]) == set(SHORT_FIELDS) | {"measure_type"}
        for name, f in [("title", r["title"])] + list(r["fields"].items()):
            assert f["text"].strip(), (r["translation_of"], name)
            assert pdf_cid.UNKNOWN not in f["text"], (r["translation_of"], name)
        yes, no = r["fields"]["yes_means"]["text"], r["fields"]["no_means"]["text"]
        if lang == "es":
            assert yes.startswith("Un voto por SÍ en esta medida significa:")
            assert no.startswith("Un voto por NO en esta medida significa:")
        else:
            assert yes.startswith("投票贊成本議案表示：") and no.startswith("投票反對本議案表示：")
            assert re.search(r"[一-鿿]", r["title"]["text"])


def test_every_field_is_found_word_for_word_in_the_saved_reading(guide):
    """What scripts/seed.py does: each field must appear word for word in the saved text of its PDF."""
    _, records, page = guide
    for r in records:
        for name, f in [("title", r["title"])] + list(r["fields"].items()):
            assert checks.text_on_page(f["text"], page), (r["translation_of"], name)


def test_a_changed_character_fails_verification(guide):
    lang, records, page = guide
    text = records[0]["fields"]["fiscal_effect"]["text"]
    for tampered in (text.replace("5", "7", 1), text[:-2] + ("x" if lang == "es" else "月") + text[-1]):
        assert tampered != text and not checks.text_on_page(tampered, page)


def test_known_fields_of_proposition_1():
    """Checked against the printed pages (and, for Chinese, against an independent OCR reading)."""
    def first(lang):
        url = f"{translated.CDN}/{translated.LAYOUTS[lang]['folder']}/pdf/{translated.QRG}"
        return translated.extract({url: {"body": QRG[lang].read_bytes()}}, lambda t, s, l: {"text": t})[0]
    es, zh = first("es"), first("zh")
    assert es["title"]["text"] == "AUTORIZA BONOS PARA PROGRAMAS DE VIVIENDA ASEQUIBLE."
    assert es["fields"]["measure_type"]["text"] == "LEY APROBADA POR LA LEGISLATURA."
    assert es["fields"]["fiscal_effect"]["text"] == (
        "Aumento de costos para el estado de entre $500 millones y $600 millones anuales durante "
        "aproximadamente 25 años para reembolsar los bonos destinados a la vivienda.")
    assert es["fields"]["opponents"]["text"] == "Ninguno enviado"
    assert zh["title"]["text"] == "授權發行用於住房負擔能力方案的債券。"
    assert zh["fields"]["measure_type"]["text"] == "立法法規。"
    assert zh["fields"]["fiscal_effect"]["text"] == "州政府每年增加 5 到 6 億美元的成本，用於償還住房債券，持續約25 年。"
    assert zh["fields"]["opponents"]["text"] == "未提交"


def test_spanish_numbers_match_the_english_guide_field_by_field():
    """Catches text cut from the wrong box or the wrong proposition: the Spanish guide prints the same
    figures as the English one ($11.25 mil millones / $11.25 billion)."""
    english = {m["id"]: m for m in json.loads((ROOT / "data" / "measures.json").read_text())["measures"]}
    url = f"{translated.CDN}/es/pdf/{translated.QRG}"
    records = translated.extract({url: {"body": QRG["es"].read_bytes()}}, lambda t, s, l: {"text": t})
    numbers = lambda text: {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", text)}  # noqa: E731
    for r in records:
        for name in ("summary", "yes_means", "no_means", "fiscal_effect"):
            assert numbers(r["fields"][name]["text"]) == numbers(english[r["translation_of"]]["fields"][name]["text"]), \
                (r["translation_of"], name)


def test_chinese_font_is_decoded_through_its_cmap_including_brackets():
    # pdftotext prints these CIDs as "䱇奚涮遤"; the font's CMap says they draw 授權發行.
    table = pdf_cid.cid_table("UniSourceHanSansTW-UTF16-H")
    assert "".join(table[ord(c)] for c in "䱇奚涮遤") == "授權發行"
    assert table[9] + table[10] == "()"  # CIDs below 32: lost by text tools, kept here
    assert table[36964] == "行"  # the ordinary character, not the Kangxi radical ⾏
    page = pdf_cid.pdf_text(QRG["zh"].read_bytes())
    assert "(除不動產外的所有個人財產)" in re.sub(r"\s", "", page)


# ---------- Bias Buster with CJK text ----------

def test_cjk_comparison_ignores_line_breaks_and_word_boundaries():
    page = "摘要\n授權發行 112.5 億美元的州政府一般責任債券，用於住房負\n擔能力方案。財政影響：州政府每\n年增加"
    assert checks.text_on_page("用於住房負擔能力方案。", page)
    assert checks.text_on_page("州政府每年增加", page)
    assert not checks.text_on_page("用於住房負擔能力計畫。", page)
    # English keeps its whole-word rule
    assert checks.text_on_page("the measure", "Shall the measure pass?")
    assert not checks.text_on_page("he measure", "Shall the measure pass?")
    assert checks.normalize("A  YES\nvote") == "a yes vote"


# ---------- interface catalogs ----------

def _template_strings():
    env, out = Environment(), set()
    for path in (WEB / "templates").glob("*.html"):
        for call in env.parse(path.read_text()).find_all(nodes.Call):
            if isinstance(call.node, nodes.Name) and call.node.name in ("_", "_a") and call.args \
                    and isinstance(call.args[0], nodes.Const):
                out.add(call.args[0].value)
    for node in ast.walk(ast.parse((WEB / "app.py").read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "T") \
                and node.args and isinstance(node.args[0], ast.Constant):
            out.add(node.args[0].value)
    return out


def _all_strings():
    from thinkballot.services.ask.app import HOW_TO_VOTE_REPLY, NOT_COVERED_REPLY
    from thinkballot.services.web.app import FIELD_HEADINGS, JS_STRINGS
    from thinkballot.suggested import SUGGESTED_QUESTIONS
    from pipeline.extract.ca_sos_guide import TOPICS
    dummy = json.loads((ROOT / "data" / "dummy" / "measures.json").read_text())
    return (_template_strings() | set(JS_STRINGS.values()) | set(FIELD_HEADINGS.values())
            | set(SUGGESTED_QUESTIONS) | {t for ts in TOPICS.values() for t in ts}
            | {HOW_TO_VOTE_REPLY, NOT_COVERED_REPLY}  # fixed Ask replies, shown translated
            | {t for m in dummy["measures"] for t in m.get("topics", [])}
            | {dummy["election"]["name"], "California Secretary of State"})


def _fields(s):
    return sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)


@pytest.mark.parametrize("lang", ["es", "zh"])
def test_catalog_translates_every_interface_string(lang):
    catalog = i18n.CATALOGS[lang]
    missing = sorted(s for s in _all_strings() if not catalog.get(s))
    assert not missing, missing


@pytest.mark.parametrize("lang", ["es", "zh"])
def test_translations_keep_placeholders_and_tags(lang):
    for en, tr in i18n.CATALOGS[lang].items():
        assert _fields(en) == _fields(tr), en
        assert sorted(re.findall(r"</?[a-z]+", en)) == sorted(re.findall(r"</?[a-z]+", tr)), en


def test_catalog_values_are_escaped_but_markup_is_kept():
    out = i18n.gettext("es", "Try a sample ZIP code: {zip}", zip="<b>x</b>")
    assert str(out) == "Prueba un código postal de ejemplo: &lt;b&gt;x&lt;/b&gt;"
    assert i18n.gettext("fr", "Search") == "Search" and i18n.gettext("en", "Search") == "Search"
    assert i18n.lang_path("es", "/") == "/es/" and i18n.lang_path("zh", "/prop/prop-1") == "/zh/prop/prop-1"
    assert i18n.lang_path("en", "/ballot") == "/ballot"


# ---------- pages ----------

@pytest.fixture(scope="module")
def with_translations(server):
    """Official-translation rows for the dummy proposition A (placeholder text, like the dummy data)."""
    from thinkballot.services.ballot import db
    conn = db.connect()
    src = "https://example.invalid/placeholder/prop-a-es.pdf"
    with conn:
        for lang, title, yes in (("es", "Medida de ejemplo para bibliotecas", "Texto de ejemplo: un voto por SÍ."),
                                 ("zh", "圖書館經費範例議案", "範例文字：投票贊成。")):
            for name, text in (("title", title), ("yes_means", yes)):
                conn.execute("INSERT OR REPLACE INTO translation VALUES (?, ?, ?, ?, ?, ?)",
                             ("prop-a", lang, name, text, src.replace("-es", "-" + lang), "Placeholder translated guide"))
            conn.execute("INSERT OR REPLACE INTO translation_doc VALUES (?, ?, ?, ?)",
                         ("prop-a", lang, "arguments", src.replace("-es", "-args-" + lang)))
    conn.close()
    return server


def _html_lang(html):
    return re.search(r'<html lang="([^"]+)"', html).group(1)


@pytest.mark.parametrize("prefix,lang", [("", "en"), ("/es", "es"), ("/zh", "zh-Hant")])
@pytest.mark.parametrize("path", ["/", "/ballot", "/prop/prop-a", "/search?q=library", "/ask", "/neutral", "/about"])
def test_pages_render_in_each_language_with_switcher(with_translations, prefix, lang, path):
    resp = requests.get(with_translations + prefix + (path if path != "/" or not prefix else "/"))
    assert resp.status_code == 200
    html = resp.text
    assert _html_lang(html) == lang
    switch = re.search(r'<nav class="lang-switch" aria-label="[^"]+">(.*?)</nav>', html, re.S).group(1)
    links = re.findall(r'<a href="([^"]+)" hreflang="([^"]+)" lang="([^"]+)"( aria-current="true")? aria-label="([^"]+)">'
                       r'<span class="lang-full">\5</span>', switch)
    assert [(h, n) for _, h, _, _, n in links] == [("en", "English"), ("es", "Español"), ("zh-Hant", "中文")]
    assert [bool(c) for _, _, _, c, _ in links] == [lang == "en", lang == "es", lang == "zh-Hant"]
    bare = path.split("?")[0]
    assert links[1][0].startswith("/es" + (bare if bare != "/" else "/")) and links[2][0].startswith("/zh")
    for hreflang in ("en", "es", "zh-Hant", "x-default"):
        assert f'hreflang="{hreflang}" href="' in html
    assert "style=" not in html and "<script>" not in html  # strict CSP: no inline styles or scripts
    if prefix:  # navigation stays in the language
        assert f'href="{prefix}/ballot"' in html and f'href="{prefix}/neutral"' in html
        assert "translated by ThinkBallot" not in html or lang == "en"
        assert json.loads(re.search(r"data-i18n='([^']*)'", html).group(1))["star"] != "☆ Star"


def test_english_pages_have_no_language_notes(with_translations):
    html = requests.get(with_translations + "/prop/prop-a").text
    assert "lang-note" not in html and "lang-flag" not in html and 'lang="en"' in html[:200]
    assert "Sample Library Funding Measure" in html
    assert 'href="/ballot"' in html


@pytest.mark.parametrize("prefix,title,yes,note", [
    ("/es", "Medida de ejemplo para bibliotecas", "Texto de ejemplo: un voto por SÍ.", "texto oficial en inglés"),
    ("/zh", "圖書館經費範例議案", "範例文字：投票贊成。", "官方英文原文"),
])
def test_translated_fields_replace_english_and_the_rest_is_marked_english(with_translations, prefix, title,
                                                                          yes, note):
    html = requests.get(with_translations + prefix + "/prop/prop-a").text
    assert title in html and yes in html
    assert "A YES vote on this placeholder measure" not in html
    # NO stays English (no official translation in this data): shown as the original, marked and labelled
    assert re.search(r'<p lang="en">A NO vote on this placeholder measure', html)
    assert note in html
    assert "example.invalid/placeholder/prop-a-args-" in html  # full arguments: the translated guide's PDF
    # YES still comes before NO, in the same layout
    assert html.index('class="yesno"') < html.index(yes) < html.index("A NO vote")


def test_ballot_list_uses_translated_titles(with_translations):
    assert "Medida de ejemplo para bibliotecas" in requests.get(with_translations + "/es/ballot").text
    assert "圖書館經費範例議案" in requests.get(with_translations + "/zh/ballot").text
    assert "Sample Library Funding Measure" in requests.get(with_translations + "/ballot").text


def test_ask_box_says_answers_are_in_english(with_translations):
    html = requests.get(with_translations + "/es/prop/prop-a").text
    assert "Las demás respuestas están en inglés" in html
    # suggested questions are sent in English (their answers are prepared in advance)
    assert 'data-question="What does it cost the state?"' in html and "¿Cuánto le cuesta al estado?" in html


def test_ask_api_errors_come_in_the_page_language(with_translations):
    r = requests.post(with_translations + "/es/api/ask", json={"measure_id": "nope"})
    assert r.status_code == 400 and r.json()["reason"] == "Propuesta desconocida."
    r = requests.post(with_translations + "/api/ask", json={"measure_id": "nope"})
    assert r.json()["reason"] == "Unknown proposition."


def test_unknown_language_prefix_is_not_a_page(with_translations):
    assert requests.get(with_translations + "/fr/ballot").status_code == 404
    assert requests.get(with_translations + "/es/nope").status_code == 404
    assert _html_lang(requests.get(with_translations + "/es/nope").text) == "es"


def test_titles_are_escaped_once(server):
    """Titles with an apostrophe or an ampersand, in titles, attributes and option labels."""
    from thinkballot.services.web.app import create_app
    app = create_app()
    with app.test_request_context("/"):
        from flask import render_template_string
        out = render_template_string(
            "<x title=\"{{ _a('{label}: {title}', label='Prop 2', title=t) }}\">{{ _('{label}: {title}', label='Prop 2', title=t) }}</x>"
            "{{ _d(t) }}", t="State's Fund & <b>Parks</b>")
    assert out == ('<x title="Prop 2: State&#39;s Fund &amp; &lt;b&gt;Parks&lt;/b&gt;">Prop 2: State&#39;s Fund &amp; '
                   '&lt;b&gt;Parks&lt;/b&gt;</x>State&#39;s Fund &amp; &lt;b&gt;Parks&lt;/b&gt;')


def test_account_pages_are_english_only(with_translations):
    resp = requests.get(with_translations + "/es/signin?next=/es/ballot", allow_redirects=False)
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/signin?next=/es/ballot")


def test_no_language_cookie(with_translations):
    resp = requests.get(with_translations + "/zh/ballot")
    assert "lang" not in resp.headers.get("Set-Cookie", "").lower()
