"""Évalue le système sur le jeu annoté et écrit data/eval/results.json.

Les deux types d'erreur sont comptés séparément : un faux « couvert » n'a pas
le même coût qu'un faux « non couvert ». L'abstention est mesurée, et on dit
si elle était justifiée.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline.cache import Cache  # noqa: E402
from app.pipeline.index import Index  # noqa: E402
from app.pipeline.providers import router  # noqa: E402
from app.pipeline.verdict import AnalysisError, analyse  # noqa: E402

ABSTENTION = {"ambigu", "information_insuffisante"}
CLASSES = ("couvert", "non_couvert", "ambigu", "information_insuffisante")


def load_questions(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarise(items: list[dict]) -> dict:
    """Calcule les métriques à partir des lignes évaluées."""
    total = len(items)
    correct = sum(1 for i in items if i["obtained_verdict"] == i["expected_verdict"])
    per_class = {}
    for label in CLASSES:
        subset = [i for i in items if i["expected_verdict"] == label]
        per_class[label] = {
            "n": len(subset),
            "correct": sum(1 for i in subset if i["obtained_verdict"] == label),
            "accuracy": round(sum(1 for i in subset if i["obtained_verdict"] == label) / len(subset), 3) if subset else None,
        }
    false_covered = [i["id"] for i in items if i["obtained_verdict"] == "couvert" and i["expected_verdict"] != "couvert"]
    false_not_covered = [i["id"] for i in items if i["obtained_verdict"] == "non_couvert" and i["expected_verdict"] != "non_couvert"]
    abstained = [i for i in items if i["obtained_verdict"] in ABSTENTION]
    justified = [i for i in abstained if i["expected_verdict"] in ABSTENTION]
    with_expected = [i for i in items if i["expected_clauses"]]
    hits = [i for i in with_expected if i["citation_hit"]]
    confusion: dict[str, Counter] = defaultdict(Counter)
    for i in items:
        confusion[i["expected_verdict"]][i["obtained_verdict"]] += 1
    return {
        "n": total,
        "accuracy": round(correct / total, 3) if total else None,
        "per_class": per_class,
        "false_covered": {"n": len(false_covered), "ids": false_covered},
        "false_not_covered": {"n": len(false_not_covered), "ids": false_not_covered},
        "abstention": {
            "n": len(abstained),
            "rate": round(len(abstained) / total, 3) if total else None,
            "justified": len(justified),
            "justified_rate": round(len(justified) / len(abstained), 3) if abstained else None,
        },
        "citation_hit": {"n": len(hits), "of": len(with_expected), "rate": round(len(hits) / len(with_expected), 3) if with_expected else None},
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "errors": sum(1 for i in items if i.get("error")),
    }


def main() -> int:
    index = Index().load()
    cache = Cache()
    questions = load_questions(ROOT / "data" / "eval" / "questions.jsonl")
    items: list[dict] = []
    for q in questions:
        row = {
            "id": q["id"],
            "contract_id": q["contract_id"],
            "question": q["question"],
            "expected_verdict": q["expected_verdict"],
            "expected_clauses": q.get("expected_clauses", []),
            "notes": q.get("notes", ""),
        }
        try:
            response = analyse(router, index, cache, q["contract_id"], q["question"], daily_cap=10_000, client_ip="eval", per_ip_cap=10_000)
            cited = [c.clause_id for c in response.verdict.cited]
            row.update(
                obtained_verdict=response.verdict.verdict,
                cited_clauses=cited,
                citation_hit=any(e in cited for e in q.get("expected_clauses", [])) if q.get("expected_clauses") else None,
                confidence=response.verdict.confidence,
                summary=response.verdict.summary,
                missing_facts=response.verdict.missing_facts,
                post_checks=response.trace.post_checks,
                cache_hit=response.trace.cache_hit,
            )
        except AnalysisError as error:
            row.update(obtained_verdict="erreur", cited_clauses=[], citation_hit=False, confidence=None, error=str(error))
        items.append(row)
        print(f"{row['id']:<28} attendu {row['expected_verdict']:<26} obtenu {row['obtained_verdict']}")
    results = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "summary": summarise(items), "items": items}
    (ROOT / "data" / "eval" / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = results["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
