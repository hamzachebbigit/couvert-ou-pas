"""La ligne structurée d'un contrat, remplie une fois à l'ingestion.

Les champs sont ceux qu'un gestionnaire nomme sans réfléchir : conditions du
vol, plafonds, franchise, inoccupation, chaleur sans incendie, biens hors du
bâtiment. Pour chaque groupe de champs, le code choisit les clauses
candidates par famille et mots-clés, puis un appel au modèle économique
remplit les valeurs avec une citation, vérifiée en code.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .index import Index, Unit
from .models import GUARANTEE_FAMILIES, Cited, ContractRow
from .prompts import load_prompt
from .providers import Router
from .verdict import verify_quote

FIELD_GROUPS: dict[str, dict[str, str]] = {
    "vol": {
        "theft_conditions": "conditions pour que le vol soit couvert dans l'habitation (effraction, escalade, fausses clés, agression, vol simple)",
        "theft_common_areas": "sort du vol dans les dépendances, caves, garages, locaux communs ou parties communes (conditions, exclusion, antivol)",
        "bike_cap": "plafond ou limite d'indemnité pour un vélo ou un cycle (montant)",
        "jewellery_cap": "plafond ou limite d'indemnité pour les bijoux ou objets précieux (montant ou pourcentage)",
    },
    "incendie": {
        "heat_without_fire_excluded": "exclusion ou traitement des dommages causés par la chaleur sans incendie (brûlures, roussissement, source de chaleur sans flamme)",
        "contents_outside_building": "sort du mobilier et des biens situés hors du bâtiment (jardin, terrasse, mobilier de jardin, en plein air)",
        "accidental_damage_option": "existence d'une option tous risques ou dommages accidentels et ce qu'elle couvre",
    },
    "general": {
        "deductible_general": "franchise générale appliquée par sinistre (montant ou mode de calcul)",
        "unoccupancy_limit": "durée d'inoccupation tolérée avant restriction des garanties (nombre de jours) et garanties concernées",
        "notable_exclusions": "liste de trois à six exclusions générales marquantes",
    },
}

GROUP_QUERIES: dict[str, list[str]] = {
    "vol": ["vol effraction escalade fausses clés agression conditions", "vol dépendances locaux communs cave garage antivol", "vélo cycle limite indemnité", "bijoux objets précieux limite indemnité"],
    "incendie": ["chaleur sans incendie brûlure roussissement exclu", "mobilier de jardin en plein air hors du bâtiment", "tous risques dommages accidentels option"],
    "general": ["franchise par sinistre montant", "inoccupation jours consécutifs inhabité", "exclusions générales ne sont pas garantis"],
}

GROUP_FAMILIES: dict[str, list[str]] = {
    "vol": ["vol", "definitions", "biens_assures", "franchises_plafonds"],
    "incendie": ["incendie", "dommages_accidentels", "biens_assures", "definitions", "exclusions_generales"],
    "general": ["franchises_plafonds", "inoccupation", "exclusions_generales", "degats_eaux", "vol"],
}


def _candidates(index: Index, contract_id: str, group: str, per_query: int = 6) -> list[Unit]:
    units = index.units[contract_id]
    positions = index.candidates(contract_id, GROUP_FAMILIES[group])
    chosen: dict[str, Unit] = {}
    for query in GROUP_QUERIES[group]:
        for position, _ in index.bm25_rank(contract_id, query, positions, per_query):
            unit = units[position]
            chosen.setdefault(unit.unit_id, unit)
    return list(chosen.values())[:18]


def _cited(raw: Any, units: list[Unit]) -> Cited:
    if not isinstance(raw, dict) or not raw.get("value"):
        return Cited()
    clause_id = str(raw.get("clause_id") or "")
    quote = raw.get("quote") or None
    page = raw.get("page")
    unit = next((u for u in units if u.unit_id == clause_id or u.clause_id == clause_id), None)
    if unit and quote:
        ok, fixed = verify_quote(str(quote), f"{unit.title} {unit.text}")
        if not ok:
            quote = None
        else:
            quote = fixed
        page = page if isinstance(page, int) and unit.page_start <= page <= unit.page_end else unit.page_start
        clause_id = unit.clause_id
    elif not unit:
        quote = None
        clause_id = ""
    return Cited(value=str(raw.get("value"))[:300], page=page if isinstance(page, int) else None, clause_id=clause_id or None, quote=quote)


def extract_row(router: Router, index: Index, contract_id: str, source: dict) -> ContractRow:
    """Remplit la ligne structurée d'un contrat, groupe de champs par groupe."""
    _, system = load_prompt("extract_row")
    values: dict[str, Any] = {}
    for group, fields in FIELD_GROUPS.items():
        units = _candidates(index, contract_id, group)
        listing = "\n\n".join(f"[{u.unit_id}] {u.path} (pages {u.page_start} à {u.page_end})\n{u.text[:2500]}" for u in units)
        asked = "\n".join(f"- {name} : {description}" for name, description in fields.items())
        user = f"Champs demandés :\n{asked}\n\nClauses du contrat :\n\n{listing}"
        data, _ = router.generate_json("cheap", system, user)
        for name in fields:
            raw = data.get(name) if isinstance(data, dict) else None
            if name == "notable_exclusions":
                items = raw if isinstance(raw, list) else []
                values[name] = [c for c in (_cited(item, units) for item in items[:6]) if c.value]
            else:
                values[name] = _cited(raw, units)
    counts = Counter(f for u in index.units[contract_id] for f in u.families)
    families = [f for f in GUARANTEE_FAMILIES if counts.get(f, 0) >= 2 and f not in ("definitions", "exclusions_generales", "biens_assures", "sinistre_procedure", "franchises_plafonds")]
    return ContractRow(
        contract_id=contract_id,
        insurer=source["insurer"],
        product=source["product"],
        edition=source.get("edition"),
        pages=int(source.get("pages") or 0),
        guarantee_families=families,
        **values,
    )


def dump_row(row: ContractRow) -> str:
    return json.dumps(row.model_dump(), ensure_ascii=False, indent=1)
