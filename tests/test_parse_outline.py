from app.pipeline.index import split_long
from app.pipeline.parse import clean_text
from app.pipeline.profiles import number_of


def test_number_of_accepts_article_numbers():
    assert number_of("12. Le tableau des limites") == ("12", "Le tableau des limites")
    assert number_of("3.1.6. Vol") == ("3.1.6", "Vol")
    assert number_of("1.1Formule de Souscription") == ("1.1", "Formule de Souscription")
    assert number_of("II. ASSURANCES HABITATION") == ("II", "ASSURANCES HABITATION")


def test_number_of_rejects_words_and_ordinals():
    assert number_of("Vol")[0] is None
    assert number_of("Indice Baloise")[0] is None
    assert number_of("1er risque (Assurance au…)")[0] is None
    assert number_of("Valeur à neuf")[0] is None


def test_clean_text_strips_symbol_glyphs_and_keeps_hyphens():
    assert clean_text("a\uf0a3b  c\u200Bd e-f") == "a b c d e-f"


def test_split_long_keeps_short_text_whole_and_splits_long_text_at_sentences():
    assert split_long("Une phrase courte.") == ["Une phrase courte."]
    text = " ".join(f"Phrase numéro {i} qui parle de la garantie vol et de ses conditions." for i in range(200))
    pieces = split_long(text, limit=800)
    assert len(pieces) > 1
    assert all(len(p) <= 900 for p in pieces)
    assert " ".join(pieces) == text
