"""Spanish and Chinese versions of the prepared answers to the suggested questions.

Only an English answer that already passed Bias Buster is translated, never a new one written. One model
translates its claims (and, where the Secretary of State has an official translation of the quoted field,
copies the matching passage of it); then two checks, both required before anything is stored:
  1. numbers: every number in the English claim, and no other, appears in the translation (by value and
     kind, so "$1.5 billion" may be "$1.5 mil millones" or "15 億美元"; number words must match too);
  2. a second model compares each translated claim with the English one: same meaning, each number
     referring to the same thing, nothing added or dropped, no persuasive wording, no hint how to vote.
A translated quote is kept only if it occurs word for word in the official translated field, has the
English quote's numbers, and the second model confirms it says what the English quote says; otherwise
the point keeps its English quote. Any other failure means no translation: the page shows the English
answer. Stored translations carry RULES, so a change to these prompts or checks retires them.
"""

import hashlib
import json
import re
import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from ... import ai, config

LANG_NAMES = {"es": "Spanish (as used in California)",
              "zh": "Traditional Chinese (繁體中文, as read by Chinese-speaking Californians)"}

TRANSLATE_SYSTEM = """You translate one short answer about a California ballot measure from English into
{language} for ThinkBallot, a nonpartisan voter guide.

Rules:
- Translate each English "claim" faithfully: the same meaning, nothing added, nothing left out, no
  stronger or weaker words, no persuasive or emotional wording, no hint how to vote.
- Plain words a 16-year-old understands.
- Keep every number in Arabic digits exactly as the English claim writes it (2026, 12.5%, $500).
  Never spell a number out, and never turn an English number word ("two", "half") into digits.
  {numbers}
- Names of places, districts, organisations and laws may stay in English.
- Some points have "official_translation": the Secretary of State's official {language} text of the
  passage the English "quote" comes from. Copy from it, character for character, the part that says
  what the English quote says, as "quote". If no part matches, or there is no official_translation,
  give "quote": "".

Reply with JSON only, one entry per input point, in the same order:
{{"points": [{{"claim": "<translated claim>", "quote": "<exact passage of official_translation, or empty>"}}]}}"""

NUMBER_RULES = {
    "es": 'Scale words: "$5 billion" -> "$5 mil millones", "$600 million" -> "$600 millones". '
          "Keep the English decimal point and thousands commas.",
    "zh": 'Write money with 萬 or 億 right after the digits: "$1.5 billion" -> "15 億美元", '
          '"$600 million" -> "6 億美元", "$50,000" -> "5 萬美元" or "50,000 美元". Every amount needs its own '
          'unit: "$500 million to $600 million" -> "5 億美元到 6 億美元", never "5 到 6 億美元".',
}

CHECK_SYSTEM = """You check translations for ThinkBallot, a nonpartisan California voter guide. For each
point, compare the {language} "translation" with the English "english" sentence. Judge only the
translation: the English sentences were already checked, so never judge whether the English is right,
complete or consistent with the other points.

A program has already checked the VALUES of the numbers only: an amount written with a {language} scale
word is the same value ("$11.25 billion" = "$11.25 mil millones" = "112.5 億美元"; "$50,000" = "5 萬美元"),
so never flag such a conversion. It did NOT check which number goes where: confirm that each number
refers to the same thing as in the English (the same cost, count, rate, year or period).

A point passes ("ok": true) only if ALL of these hold:
- it means the same thing as the English;
- nothing is added and nothing is left out;
- each number, amount and date refers to the same thing, and names are the same;
- no loaded, emotional or persuasive wording the English does not have;
- no hint how to vote.
Small differences of style or word order are fine.

Some points also have "english_quote" (from the official English text) and "official_quote" (from the
Secretary of State's official {language} translation). For those, also give "quote_ok": true only if the
official quote says the same thing as the English quote: the same facts and numbers, nothing that
contradicts it. (One may be a little longer than the other.) Otherwise "quote_ok": false.

Reply with JSON only: a "points" list with exactly one entry per input point, in the same order, e.g.
for three points: {{"points": [{{"ok": true}}, {{"ok": false, "problem": "<short reason in English>"}},
{{"ok": true, "quote_ok": true}}]}}"""

# Change when the checks below change, so translations made under the old rules are not served.
RULES_VERSION = "2"
RULES = hashlib.sha256(json.dumps([RULES_VERSION, TRANSLATE_SYSTEM, NUMBER_RULES, CHECK_SYSTEM, LANG_NAMES],
                                  ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


class Rejected(Exception):
    """A translation that failed a check; `reason` is "format", "number" or "review"."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


# ---------- numbers ----------

_SCALE = {"thousand": 3, "million": 6, "billion": 9, "trillion": 12,
          "mil millones": 9, "millones": 6, "millón": 6, "mil": 3, "billones": 12, "billón": 12,
          "兆": 12, "億": 8, "亿": 8, "千萬": 7, "百萬": 6, "萬": 4, "万": 4, "千": 3}
_UNITS = {"en": r"\s*(thousand|million|billion|trillion)\b",
          "es": r"\s*(mil millones|millones|millón|mil|billones|billón)\b",
          "zh": r"\s*(兆|億|亿|千萬|百萬|萬|万|千)"}
# What a number counts, so swapped numbers are caught: "$30 for 500 years" is not "$500 for 30 years".
_MONEY_AFTER = {"en": r"\s*dollars?\b", "es": r"\s*d[óo]lares\b", "zh": r"\s*(?:美元|元)"}
_PERCENT_AFTER = {"en": r"\s*(?:%|percent\b)", "es": r"\s*(?:%|por ciento\b)", "zh": r"\s*%"}
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]
_NUMBER_RE = r"(\$\s*)?(?<![\d.])(\d+(?:\.\d+)?)(?:{units})?"


def _normalize(text):
    text = unicodedata.normalize("NFKC", text or "")  # full-width digits and ％ -> ASCII
    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)  # thousands commas (not "3, 2026")


def numbers_in(text, lang):
    """The numbers written in digits, as (kind, value) with kind "money", "percent" or "number" and scale
    words included: "$1.5 billion" and "15 億美元" -> ("money", 1500000000). A Counter: order may differ
    between languages, but each value must count the same thing."""
    text = _normalize(text)
    out = Counter()
    for m in re.finditer(_NUMBER_RE.format(units=_UNITS[lang]), text, re.IGNORECASE):
        try:
            value = Decimal(m.group(2))
        except InvalidOperation:
            continue
        if m.group(3):
            value = value.scaleb(_SCALE[m.group(3).lower()])
        rest = text[m.end():]
        if m.group(1) or re.match(_MONEY_AFTER[lang], rest, re.IGNORECASE):
            kind = "money"
        elif re.match(_PERCENT_AFTER[lang], rest, re.IGNORECASE):
            kind = "percent"
        else:
            kind = "number"
        out[(kind, value.normalize())] += 1
    return out


# Numbers written as words. Translations must keep digits as digits and words as words, and the words on
# both sides must have the same values ("two thirds" is not "tres cuartos"). Words that are also ordinary
# words ("un", "medio" as in "medio ambiente", 一 as in 一般) are not counted.
_THIRD = Fraction(1, 3)
_WORDS = {
    "en": {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
           "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9, "half": Fraction(1, 2),
           "quarter": Fraction(1, 4), "quarters": Fraction(1, 4), "twice": 2, "double": 2,
           "triple": 3},
    "es": {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
           "once": 11, "doce": 12, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "cien": 100,
           "ciento": 100, "cientos": 100, "mil": 1000, "millón": 10 ** 6, "millones": 10 ** 6, "mitad": Fraction(1, 2),
           "tercio": _THIRD, "tercios": _THIRD, "cuarto": Fraction(1, 4), "cuartos": Fraction(1, 4),
           "doble": 2, "triple": 3},
    "zh": {"二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
           "百": 100, "千": 1000, "萬": 10 ** 4, "万": 10 ** 4, "億": 10 ** 8, "亿": 10 ** 8, "半": Fraction(1, 2),
           "倍": None},
}
_ZH_NOT_NUMBERS = ["三藩市", "十分", "百姓", "萬一", "千萬不", "四處", "四周", "兩者", "兩邊", "兩方", "第"]
# "two thirds", "a third of": fractions; "a third term": an ordinal
_ENGLISH_FRACTION = (r"\b(?:(?:two|three|four|five|six|seven|eight|nine|ten)[\s-]+(third|fourth)s\b"
                     r"|(?:a|one)[\s-]+(third|fourth)\s+of\b)")


def number_words(text, lang):
    """Values of the numbers written as words (digits and their scale words left out), as a Counter."""
    text = re.sub(_NUMBER_RE.format(units=_UNITS[lang]), " ", _normalize(text), flags=re.IGNORECASE)
    out = Counter()
    if lang == "zh":
        for word in _ZH_NOT_NUMBERS:  # not numbers here; 第 starts an ordinal (第二 = second), not counted
            text = re.sub(re.escape(word) + ("[一二兩三四五六七八九十百]+" if word == "第" else ""), " ", text)
        for m in re.finditer(r"([二兩两三四五六七八九十])分之([一二兩两三四五六七八九])", text):  # 三分之二 = 2/3
            out[Fraction(1, _WORDS["zh"][m.group(1)])] += 1
            if m.group(2) != "一":
                out[_WORDS["zh"][m.group(2)]] += 1
        text = re.sub(r"[二兩两三四五六七八九十]分之[一二兩两三四五六七八九]", " ", text)
        for ch in text:
            if _WORDS["zh"].get(ch) is not None:
                out[_WORDS["zh"][ch]] += 1
        return out
    if lang == "en":  # ordinals ("third") are not counted
        for m in re.finditer(_ENGLISH_FRACTION, text, re.IGNORECASE):
            out[_THIRD if (m.group(1) or m.group(2)).lower() == "third" else Fraction(1, 4)] += 1
        text = re.sub(r"\b(third|fourth)s?\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpor ciento\b", " ", text, flags=re.IGNORECASE)  # "12.5 por ciento": not 100
    for word in re.findall(r"[^\W\d_]+", text.lower()):
        if word in _WORDS[lang]:
            out[_WORDS[lang][word]] += 1
    return out


def numbers_match(english, translated, lang):
    """The translation has the same numbers as the English, counting the same kind of thing (money,
    percent, other), and the same numbers written as words. A month written as a word in an English date
    may be a number in the translation ("November 3" -> "11月3日")."""
    want, got = numbers_in(english, "en"), numbers_in(translated, lang)
    months = Counter(("number", Decimal(_MONTHS.index(m.group(1).lower()) + 1))
                     for m in re.finditer(rf"\b({'|'.join(_MONTHS)})\s+\d", english, re.IGNORECASE))
    if want - got or (got - want) - months:
        return False
    return number_words(english, "en") == number_words(translated, lang)


# ---------- official translated quotes ----------

_CJK = r"　-〿㐀-鿿豈-﫿＀-￯"


def _squash(text):
    """Collapse whitespace; none next to CJK characters (line breaks fall anywhere in Chinese text)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    return re.sub(rf"(?<=[{_CJK}]) | (?=[{_CJK}])", "", text)


def official_quote_ok(quote, field_text):
    """The quote occurs word for word (whitespace aside) in the official translated field: the whole field,
    or a part of at least 6 words (Spanish) or 10 characters (Chinese). No "..." joins."""
    q, field = _squash(quote), _squash(field_text)
    if not q or "..." in q or "…" in q:
        return False
    if q == field:
        return True
    cjk = len(re.findall(rf"[{_CJK}]", q))
    if (cjk < 10) if cjk else (len(q.split()) < 6):
        return False
    before = "" if re.match(rf"[{_CJK}\W]", q[0]) else r"(?<!\w)"
    after = "" if re.match(rf"[{_CJK}\W]", q[-1]) else r"(?!\w)"
    return re.search(before + re.escape(q) + after, field) is not None


# ---------- the two model calls ----------

def _stub_translate(user):
    """Offline stand-in: mark the claim with the language, keep its numbers; the whole official field as quote."""
    data = json.loads(user)
    return {"points": [{"claim": f"[{data['language']}] {p['claim']}", "quote": p.get("official_translation", "")}
                       for p in data["points"]]}


def _stub_check(user):
    return {"points": [dict({"ok": True}, **({"quote_ok": True} if "official_quote" in p else {}))
                       for p in json.loads(user)["points"]]}


def translate_points(points, lang, official, deadline=None):
    """Translated points [{"claim", "quote", "quote_lang"}] for English `points` [{"claim", "quote"}].

    `official[i]` is the official translated text of the field point i quotes, or None. Raises Rejected
    if a check fails, ai.AIError if a model can't be reached. Nothing here is stored.
    """
    request = {"language": lang, "points": [
        dict({"claim": p["claim"], "quote": p["quote"]}, **({"official_translation": o} if o else {}))
        for p, o in zip(points, official)]}
    system = TRANSLATE_SYSTEM.format(language=LANG_NAMES[lang], numbers=NUMBER_RULES[lang])
    reply = ai.chat_json(config.TRANSLATE_MODEL, system, json.dumps(request, ensure_ascii=False),
                         stub=_stub_translate, deadline=deadline)
    drafts = reply.get("points")
    if not isinstance(drafts, list) or len(drafts) != len(points) \
            or not all(isinstance(d, dict) and isinstance(d.get("claim"), str) and d["claim"].strip() for d in drafts):
        raise Rejected("format", "not one translated claim per point")

    claims, quotes = [], []  # quotes[i]: a candidate official translated quote for point i, or None
    for i, (p, d, o) in enumerate(zip(points, drafts, official)):
        claim = d["claim"].strip()
        if not numbers_match(p["claim"], claim, lang):
            raise Rejected("number", f"point {i + 1}")
        claims.append(claim)
        quote = d.get("quote") if isinstance(d.get("quote"), str) else ""
        # Word for word in the official translated field, with the English quote's numbers; the review
        # below must also confirm it says what the English quote says.
        ok = bool(o) and official_quote_ok(quote, o) and numbers_match(p["quote"], quote, lang)
        quotes.append(_squash(quote) if ok else None)

    pairs = {"language": lang, "points": [
        dict({"english": p["claim"], "translation": c},
             **({"english_quote": p["quote"], "official_quote": q} if q else {}))
        for p, c, q in zip(points, claims, quotes)]}
    review = ai.chat_json(config.TRANSLATE_CHECK_MODEL, CHECK_SYSTEM.format(language=LANG_NAMES[lang]),
                          json.dumps(pairs, ensure_ascii=False), stub=_stub_check, deadline=deadline)
    verdicts = review.get("points")
    if not isinstance(verdicts, list) or len(verdicts) != len(points):
        got = f"{len(verdicts)} verdicts" if isinstance(verdicts, list) else f"keys {sorted(review)[:5]}"
        raise Rejected("review", f"no verdict for every point ({got} for {len(points)} points)")
    out = []
    for i, (p, c, q, v) in enumerate(zip(points, claims, quotes, verdicts)):
        if not isinstance(v, dict) or v.get("ok") is not True:
            problem = v.get("problem") if isinstance(v, dict) and isinstance(v.get("problem"), str) else ""
            raise Rejected("review", f"point {i + 1}: {problem[:160]}")
        if q and v.get("quote_ok") is True:
            out.append({"claim": c, "quote": q, "quote_lang": lang})
        else:  # no matching official translated passage: the English quote, marked as English
            out.append({"claim": c, "quote": p["quote"], "quote_lang": "en"})
    return out
