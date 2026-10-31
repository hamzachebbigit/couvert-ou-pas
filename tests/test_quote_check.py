from app.pipeline.verdict import verify_quote

CLAUSE = (
    "Le vol commis dans les dépendances n’est garanti qu’en cas d’effraction de celles-ci "
    "ou si le vélo était attaché par un antivol homologué. Les vélos sont indemnisés à concurrence de 1 500 EUR par sinistre."
)


def test_exact_quote_is_verified():
    ok, fixed = verify_quote("Les vélos sont indemnisés à concurrence de 1 500 EUR par sinistre.", CLAUSE)
    assert ok
    assert fixed == "Les vélos sont indemnisés à concurrence de 1 500 EUR par sinistre."


def test_quote_with_straight_apostrophe_matches_curly_text():
    ok, fixed = verify_quote("n'est garanti qu'en cas d'effraction", CLAUSE)
    assert ok
    assert "n’est garanti qu’en cas d’effraction" == fixed


def test_quote_with_hyphenation_break_is_recovered():
    ok, fixed = verify_quote("Les vélos sont indem- nisés à concurrence de 1 500 EUR", CLAUSE)
    assert ok
    assert fixed.startswith("Les vélos sont indemnisés")


def test_invented_quote_is_rejected():
    ok, _ = verify_quote("Le vol de vélo est couvert sans condition dans tous les cas", CLAUSE)
    assert not ok


def test_too_short_quote_is_rejected():
    ok, _ = verify_quote("vol", CLAUSE)
    assert not ok
