"""Construit data/index.db à partir des contrats parsés.

    python scripts/build_index.py            # avec embeddings (clé Gemini requise)
    python scripts/build_index.py --no-embeddings
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline.index import Index  # noqa: E402
from app.pipeline.providers import router  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-embeddings", action="store_true")
    args = parser.parse_args()
    ids = [c["id"] for c in json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))["contracts"]]
    ids = [i for i in ids if (ROOT / "data" / "parsed" / i / "clauses.json").exists()]
    embed = None if args.no_embeddings else (lambda texts: router.embed(texts, "RETRIEVAL_DOCUMENT"))
    Index().build(ids, embed=embed, embed_model="" if args.no_embeddings else router.embed_model)
    print("index écrit :", ROOT / "data" / "index.db")


if __name__ == "__main__":
    main()
