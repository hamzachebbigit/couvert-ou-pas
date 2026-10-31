import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
evaluate = importlib.util.module_from_spec(spec)
sys.modules["evaluate"] = evaluate
spec.loader.exec_module(evaluate)  # type: ignore[union-attr]


def _item(id_: str, expected: str, obtained: str, hit: bool | None = True) -> dict:
    return {"id": id_, "expected_verdict": expected, "obtained_verdict": obtained, "expected_clauses": ["x"] if hit is not None else [], "citation_hit": hit}


def test_summary_counts_the_two_error_types_separately():
    items = [
        _item("a", "couvert", "couvert"),
        _item("b", "non_couvert", "couvert"),
        _item("c", "information_insuffisante", "non_couvert", False),
        _item("d", "ambigu", "ambigu"),
        _item("e", "information_insuffisante", "information_insuffisante"),
    ]
    summary = evaluate.summarise(items)
    assert summary["n"] == 5
    assert summary["accuracy"] == 0.6
    assert summary["false_covered"] == {"n": 1, "ids": ["b"]}
    assert summary["false_not_covered"] == {"n": 1, "ids": ["c"]}
    assert summary["abstention"]["n"] == 2
    assert summary["abstention"]["justified"] == 2
    assert summary["citation_hit"]["rate"] == 0.8
    assert summary["per_class"]["couvert"]["accuracy"] == 1.0
