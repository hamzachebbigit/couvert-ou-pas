"""Extrait la ligne structurée de chaque contrat vers data/parsed/<id>/row.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline.extract import dump_row, extract_row  # noqa: E402
from app.pipeline.index import Index  # noqa: E402
from app.pipeline.providers import router  # noqa: E402


def main(argv: list[str]) -> None:
    index = Index().load()
    sources = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))["contracts"]
    wanted = set(argv) or {s["id"] for s in sources}
    for source in sources:
        if source["id"] not in wanted or source["id"] not in index.units:
            continue
        row = extract_row(router, index, source["id"], source)
        target = ROOT / "data" / "parsed" / source["id"] / "row.json"
        target.write_text(dump_row(row), encoding="utf-8")
        filled = sum(1 for name in ("theft_conditions", "theft_common_areas", "bike_cap", "jewellery_cap", "deductible_general", "unoccupancy_limit", "heat_without_fire_excluded", "contents_outside_building", "accidental_damage_option") if getattr(row, name).value)
        print(f"{source['id']} : {filled}/9 champs renseignés, {len(row.notable_exclusions)} exclusions notables")


if __name__ == "__main__":
    main(sys.argv[1:])
