"""The Bias Buster's deterministic checks, with planted problems."""

from thinkballot.services.bias import checks, engine

SOURCE = ("A YES vote means the state could sell $1.5 billion in bonds for parks. "
          "A NO vote means the state could not sell these bonds.")


def test_quote_found_ignores_case_quotes_and_spacing():
    assert checks.quote_found("the state could  sell $1.5 BILLION in bonds", [SOURCE])
    assert checks.quote_found("A YES vote means … for parks", [SOURCE])


def test_invented_quote_is_caught():
    assert not checks.quote_found("the state must sell $2 billion in bonds", [SOURCE])
    assert checks.check_quote("", [SOURCE])


def test_hallucinated_number_is_caught():
    findings = checks.check_numbers("The bonds cost $2 billion over 30 years.", [SOURCE])
    assert {f["detail"] for f in findings} == {
        "number 2 does not appear in the official text", "number 30 does not appear in the official text"}
    assert checks.check_numbers("It allows $1.5 billion in bonds.", [SOURCE]) == []


def test_loaded_word_is_caught_unless_the_source_uses_it():
    assert checks.check_loaded_words("This disastrous bond adds debt.", [SOURCE])
    assert checks.check_loaded_words("a common-sense idea", ["Placeholder: a common-sense idea"]) == []


def test_balance_needs_both_sides_of_similar_length():
    assert checks.check_balance("YES means parks get money.", "")
    assert checks.check_balance("one two", "one two three four five six seven eight nine ten")
    assert checks.check_balance("YES means bonds are sold.", "NO means bonds are not sold.") == []


def test_answer_drops_bad_points_and_keeps_good_ones():
    points = [
        {"claim": "YES lets the state sell $1.5 billion in bonds.",
         "quote": "the state could sell $1.5 billion in bonds for parks"},
        {"claim": "It will cost $9 billion.", "quote": "the state could sell $1.5 billion"},
        {"claim": "A terrible idea.", "quote": "A NO vote means the state could not sell these bonds"},
    ]
    result = engine.check_answer(points, [SOURCE], use_ai=False)
    assert result["verdict"] == "revised"
    assert [p["claim"] for p in result["points"]] == ["YES lets the state sell $1.5 billion in bonds."]
    assert {f["check"] for f in result["findings"]} == {"number", "loaded_words"}


def test_answer_with_nothing_grounded_is_blocked():
    result = engine.check_answer([{"claim": "Parks are nice.", "quote": "parks are nice"}], [SOURCE],
                                 use_ai=False)
    assert result["verdict"] == "blocked"


def test_ai_review_failure_blocks_the_answer(monkeypatch):
    def boom(*_a, **_k):
        raise engine.ai.AIError("down")
    monkeypatch.setattr(engine.ai, "chat_json", boom)
    points = [{"claim": "YES lets the state sell bonds.", "quote": "the state could sell $1.5 billion"}]
    assert engine.check_answer(points, [SOURCE])["verdict"] == "blocked"


def test_ai_edits_are_checked_again(monkeypatch):
    # The reviewer "improves" the answer by inventing a number; the re-check must remove it.
    monkeypatch.setattr(engine.ai, "chat_json", lambda *_a, **_k: {
        "findings": [{"detail": "reworded"}],
        "points": [{"claim": "It costs $7 billion.", "quote": "the state could sell $1.5 billion"}]})
    points = [{"claim": "YES lets the state sell bonds.", "quote": "the state could sell $1.5 billion"}]
    assert engine.check_answer(points, [SOURCE])["verdict"] == "blocked"


def test_verify_and_audit_modes():
    assert engine.check_text("could sell $1.5 billion in bonds", [SOURCE], "verify")["verdict"] == "pass"
    assert engine.check_text("could sell $2 billion in bonds", [SOURCE], "verify")["verdict"] == "fail"
    audited = engine.check_text("A common-sense plan.", ["A common-sense plan."], "audit")
    assert audited["verdict"] == "flagged" and audited["text"] == "A common-sense plan."
