from pathlib import Path

from app.pipeline.cache import Cache, cache_key, normalise_question
from app.pipeline.families import families_for_clause
from app.pipeline.index import tokenize


def test_normalised_question_ignores_case_accents_and_spacing():
    a = normalise_question("On m'a volé mon vélo   dans le local commun.")
    b = normalise_question("on m’a vole mon velo dans le local commun.")
    assert a == b
    assert cache_key("c", "On m'a volé mon vélo", "v1", "m") == cache_key("c", "on m’a VOLE mon velo", "v1", "m")
    assert cache_key("c", "q", "v1", "m") != cache_key("c", "q", "v2", "m")


def test_families_come_from_title_first():
    assert "vol" in families_for_clause("Vol", "Garanties de base > Vol", "texte")
    assert "definitions" in families_for_clause("Lexique", "", "")
    assert "incendie" in families_for_clause("Incendie et périls assimilés", "", "")


def test_tokenizer_stems_french_and_drops_stopwords():
    tokens = tokenize("Les vélos volés dans les dépendances")
    assert "les" not in tokens
    assert any(t.startswith("velo") for t in tokens)
    assert any(t.startswith("depend") for t in tokens)


def test_daily_cap_and_ip_cap(tmp_path: Path):
    cache = Cache(tmp_path / "cache.db")
    assert cache.reserve_daily(2)
    assert cache.reserve_daily(2)
    assert not cache.reserve_daily(2)
    assert cache.reserve_ip_minute("1.2.3.4", 1)
    assert not cache.reserve_ip_minute("1.2.3.4", 1)
    assert cache.reserve_ip_minute("5.6.7.8", 1)


def test_cache_roundtrip(tmp_path: Path):
    cache = Cache(tmp_path / "cache.db")
    key = cache_key("c", "q", "v", "m")
    assert cache.get(key) is None
    cache.put(key, "c", "q", "v", "m", {"verdict": {"verdict": "ambigu"}})
    assert cache.get(key) == {"verdict": {"verdict": "ambigu"}}
