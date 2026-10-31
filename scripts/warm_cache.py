"""Pré-calcule les verdicts du jeu annoté, pour que la démo réponde depuis le cache.

Reprend là où il s'est arrêté : une question déjà en cache ne coûte rien.
    python scripts/warm_cache.py            # tout le jeu
    python scripts/warm_cache.py q01 q02    # certaines questions
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline.cache import Cache  # noqa: E402
from app.pipeline.index import Index  # noqa: E402
from app.pipeline.providers import router  # noqa: E402
from app.pipeline.verdict import AnalysisError, analyse  # noqa: E402


def main(argv: list[str]) -> int:
    index = Index().load()
    cache = Cache()
    wanted = set(argv)
    lines = (ROOT / "data" / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    failures = 0
    for line in lines:
        if not line.strip():
            continue
        item = json.loads(line)
        if wanted and item["id"].split("_")[0] not in wanted and item["id"] not in wanted:
            continue
        try:
            response = analyse(router, index, cache, item["contract_id"], item["question"], daily_cap=10_000, client_ip="warm", per_ip_cap=10_000)
            flag = "cache" if response.trace.cache_hit else f"{response.trace.total_ms} ms"
            print(f"{item['id']:<28} {response.verdict.verdict:<26} {flag}")
        except AnalysisError as error:
            failures += 1
            print(f"{item['id']:<28} ÉCHEC {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
