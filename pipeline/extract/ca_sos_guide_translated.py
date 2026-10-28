"""Extractor: the Secretary of State's official translations of the voter guide (Spanish, Chinese).

The web guide is English only. The translations are published as PDFs; each proposition's short fields
(the ones on its web overview page) are in the Quick Reference Guide PDF, two propositions per page, in
the same boxes as the English guide: title and type, summary (with fiscal impact, supporters and
opponents), what a YES and a NO vote mean, and the arguments for and against.

Every field is cut by code from the saved reading of the PDF (pipeline/extract/pdf_cid.py: poppler's
text in content order; Chinese decoded with the font's own CMap). Nothing is translated here.
Each proposition yields a translation record that pipeline/extract/run.py attaches to the English
measure with the same id; fields not found stay English on the site, with a note.
"""

import re

from . import pdf_cid

CDN = "https://vig.cdn.sos.ca.gov/2026/general"
QRG = "quick-reference-guide.pdf"

# Words printed in the guide's boxes, per translation (the PDFs' folders are es/ and ch/).
LAYOUTS = {
    "es": {
        "folder": "es", "label": "Guía Oficial de Información para el Votante",
        "prop": "PROPUESTA", "summary": "RESUMEN", "vote": "QUÉ SIGNIFICA SU VOTO", "args": "ARGUMENTOS",
        "contact": "PARA OBTENER INFORMACIÓN ADICIONAL", "yes": "SÍ", "no": "NO", "pro": "PROS",
        "con": "CONTRAS",
        "split": r"(.*?)\s*Impacto Fiscal:\s*(.*?)\s*Partidarios:\s*(.*?)\s*Opositores:\s*(.*)$",
        "type": r"^(.*?)\s*((?:LEY|ENMIENDA|INICIATIVA)\b[^.]*\.)$",
    },
    "zh": {
        "folder": "ch", "label": "官方選民資訊指南",
        "prop": "提案", "summary": "摘要", "vote": "對投票行為的解釋或解讀", "args": "論點",
        "contact": "欲了解更多資訊", "yes": "贊成", "no": "反對", "pro": "優點", "con": "缺點",
        "split": r"(.*?)\s*財政影響：\s*(.*?)\s*支持者：\s*(.*?)\s*反對者：\s*(.*)$",
        "type": r"^(.*?)\s*((?:立法|倡議)[^。]*。)$",
    },
}

ROW = 5  # points: runs whose tops differ by less than this sit on one printed row


def _is(run, word):
    return run["text"].strip() == word


def _text(runs):
    return pdf_cid.join_lines(line["text"] for line in pdf_cid.lines_of(runs))


def _column_props(items, lay):
    """[(number, x0, x1, label_run)] for the propositions on one page, left to right."""
    labels = [r for r in items if _is(r, lay["prop"]) and r["top"] < 135]
    labels.sort(key=lambda r: r["left"])
    out = []
    for i, lab in enumerate(labels):
        x0 = lab["left"] - 27
        x1 = labels[i + 1]["left"] - 27 if i + 1 < len(labels) else 10 ** 6
        numbers = [r for r in items if re.fullmatch(r"\s*\d+\s*", r["text"]) and r["height"] >= 20
                   and x0 <= r["left"] < x1 and abs(r["top"] - lab["top"]) < 20]
        if len(numbers) != 1:
            raise ValueError(f"can't find the proposition number next to {lay['prop']} at x={lab['left']}")
        out.append((numbers[0]["text"].strip(), x0, x1, lab, numbers[0]))
    return out


def _heading(col, word, after=0):
    hits = [r for r in col if _is(r, word) and r["top"] > after]
    if len(hits) != 1:
        raise ValueError(f"expected one {word!r} heading, found {len(hits)}")
    return hits[0]


def _two_boxes(runs, left_label, right_label):
    """Split a section into the box under each label (label runs dropped). The label's box starts at
    the label's own x position; the right-hand box starts where its label starts."""
    if right_label["left"] < left_label["left"]:
        raise ValueError("unexpected order of boxes")
    split = right_label["left"] - 3
    body = [r for r in runs if r is not left_label and r is not right_label]
    return ([r for r in body if r["left"] < split], [r for r in body if r["left"] >= split])


def parse_qrg(pages, lay):
    """{number: {title, measure_type, summary, fiscal_effect, supporters, opponents, yes_means, no_means,
    argument_for, argument_against}} from the runs of the Quick Reference Guide."""
    out = {}
    for items in pages:
        for number, x0, x1, label, number_run in _column_props(items, lay):
            col = [r for r in items if x0 <= r["left"] < x1]
            summary_h = _heading(col, lay["summary"])
            vote_h = _heading(col, lay["vote"])
            args_h = _heading(col, lay["args"], after=vote_h["top"])
            contact = [r for r in col if _is(r, lay["contact"]) and r["top"] > args_h["top"]]
            end = contact[0]["top"] if contact else 10 ** 6

            title_runs = [r for r in col if r["top"] < summary_h["top"] - ROW and r is not label
                          and r is not number_run and r["top"] >= label["top"] - 14 and r["height"] < 20]
            m = re.match(lay["type"], _text(title_runs), re.S)
            if not m:
                raise ValueError(f"can't split title and type for Prop {number}")
            fields = {"title": m.group(1).strip(), "measure_type": m.group(2).strip()}

            summary_runs = [r for r in col if summary_h["top"] + ROW <= r["top"] < vote_h["top"] - ROW]
            m = re.match(lay["split"], _text(summary_runs), re.S)
            if not m:
                raise ValueError(f"can't split the summary box of Prop {number}")
            for name, value in zip(("summary", "fiscal_effect", "supporters", "opponents"), m.groups()):
                fields[name] = value.strip()

            vote = [r for r in col if vote_h["top"] + ROW <= r["top"] < args_h["top"] - ROW]
            yes_box, no_box = _two_boxes(vote, _heading(vote, lay["yes"]), _heading(vote, lay["no"]))
            args = [r for r in col if args_h["top"] + ROW <= r["top"] < end - ROW]
            pro_box, con_box = _two_boxes(args, _heading(args, lay["pro"]), _heading(args, lay["con"]))
            for name, box in (("yes_means", yes_box), ("no_means", no_box), ("argument_for", pro_box),
                              ("argument_against", con_box)):
                fields[name] = _text(box)
            if any(not v for v in fields.values()):
                raise ValueError(f"empty field for Prop {number}: {[k for k, v in fields.items() if not v]}")
            if number in out:
                raise ValueError(f"Prop {number} appears twice")
            out[number] = fields
    return out


def extract(pages, field):
    """pages: {url: raw page row}; one translation record per proposition in the guide."""
    langs = [lang for lang, lay in LAYOUTS.items() if f"{CDN}/{lay['folder']}/pdf/{QRG}" in pages]
    if len(langs) != 1:
        raise ValueError("no Quick Reference Guide PDF in this source")
    lang = langs[0]
    lay = LAYOUTS[lang]
    base = f"{CDN}/{lay['folder']}/pdf"
    qrg_url = f"{base}/{QRG}"
    parsed = parse_qrg(pdf_cid.runs(pages[qrg_url]["body"]), lay)
    records = []
    for number, values in sorted(parsed.items(), key=lambda kv: int(kv[0])):
        label = f"{lay['label']}: {QRG_LABEL[lang]}"
        documents = {}
        for kind, name in (("analysis", f"prop{number}-title-summ-analysis.pdf"),
                           ("arguments", f"prop{number}-arg-rebuttals.pdf")):
            if f"{base}/{name}" in pages:
                documents[kind] = f"{base}/{name}"
        records.append({
            "translation_of": f"prop-{number}", "language": lang,
            "title": field(values.pop("title"), qrg_url, label),
            "fields": {name: field(text, qrg_url, label) for name, text in values.items()},
            "documents": documents,
        })
    return records


QRG_LABEL = {"es": "Guía de Referencia Rápida", "zh": "快速參考指南"}
