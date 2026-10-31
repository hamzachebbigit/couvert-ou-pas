from app.pipeline.models import CitedClause, Clause, ParsedQuestion, RetrievedClause, Trace, Verdict
from app.pipeline.verdict import post_check

TEXT = "Le vol commis dans les dépendances n’est garanti qu’en cas d’effraction ou si le vélo était attaché par un antivol."


def _clause() -> Clause:
    return Clause(contract_id="c", clause_id="3_1_6", title="Vol", level=3, path="Garanties > Vol", page_start=41, page_end=43, text=TEXT, families=["vol"])


def _chosen() -> list[RetrievedClause]:
    c = _clause()
    return [RetrievedClause(clause_id=c.clause_id, title=c.title, path=c.path, page_start=c.page_start, page_end=c.page_end, text=c.text, families=c.families)]


def _parsed(needed: list[str]) -> ParsedQuestion:
    return ParsedQuestion(event="vol", event_family=["vol"], facts_potentially_needed=needed)


def test_covered_with_missing_fact_becomes_information_insuffisante():
    verdict = Verdict(verdict="couvert", summary="Couvert.", cited=[CitedClause(clause_id="3_1_6", page=41, quote="n’est garanti qu’en cas d’effraction", role="condition")], confidence=0.9)
    trace = Trace()
    out = post_check(verdict, _parsed(["y a-t-il eu effraction ?"]), _chosen(), {"3_1_6": _clause()}, trace)
    assert out.verdict == "information_insuffisante"
    assert "y a-t-il eu effraction ?" in out.missing_facts
    assert out.confidence <= 0.6


def test_unverified_quote_is_dropped_and_verdict_suspended():
    verdict = Verdict(verdict="non_couvert", summary="Non couvert.", cited=[CitedClause(clause_id="3_1_6", page=41, quote="le vol de vélo n'est jamais couvert nulle part", role="exclusion")], confidence=0.9)
    trace = Trace()
    out = post_check(verdict, _parsed([]), _chosen(), {"3_1_6": _clause()}, trace)
    assert out.cited == []
    assert out.verdict == "information_insuffisante"
    assert any("non vérifiée" in note for note in trace.post_checks)


def test_covered_with_all_facts_given_stays_covered():
    verdict = Verdict(verdict="couvert", summary="Couvert.", cited=[CitedClause(clause_id="3_1_6", page=41, quote="si le vélo était attaché par un antivol", role="condition")], confidence=0.85)
    out = post_check(verdict, _parsed([]), _chosen(), {"3_1_6": _clause()}, Trace())
    assert out.verdict == "couvert"
    assert out.cited[0].verified


def test_citation_outside_provided_clauses_is_removed():
    verdict = Verdict(verdict="couvert", summary="Couvert.", cited=[CitedClause(clause_id="9_9_9", page=1, quote="une clause qui n'a pas été fournie au modèle", role="garantie")], confidence=0.8)
    out = post_check(verdict, _parsed([]), _chosen(), {"3_1_6": _clause()}, Trace())
    assert out.verdict == "information_insuffisante"
    assert out.cited == []


def test_sure_verdict_with_missing_facts_is_downgraded():
    verdict = Verdict(verdict="non_couvert", summary="Non couvert.", cited=[CitedClause(clause_id="3_1_6", page=41, quote="n’est garanti qu’en cas d’effraction", role="condition")], missing_facts=["y a-t-il eu effraction ?"], confidence=0.9)
    out = post_check(verdict, _parsed([]), _chosen(), {"3_1_6": _clause()}, Trace())
    assert out.verdict == "information_insuffisante"
