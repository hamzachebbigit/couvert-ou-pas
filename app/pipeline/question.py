"""Lecture de la question : des champs typés avant toute recherche.

Un appel au modèle économique rend l'événement, l'objet, le lieu, les
circonstances et l'état des faits que l'événement exige. La liste des faits
exigés vient des règles (`families.FACTS_NEEDED_BY_FAMILY`), pas du modèle.
Un fait sans statut est tenu pour absent : on ne devine pas.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .families import FACTS_NEEDED_BY_FAMILY
from .models import GUARANTEE_FAMILIES, ParsedQuestion
from .prompts import load_prompt
from .providers import Router


def _facts_block() -> str:
    lines = ["Faits que chaque famille exige en général (à reprendre dans facts_status pour les familles retenues) :"]
    for family, facts in FACTS_NEEDED_BY_FAMILY.items():
        lines.append(f"- {family} :")
        lines.extend(f"    - {fact}" for fact in facts)
    return "\n".join(lines)


def parse_question(router: Router, question: str) -> tuple[ParsedQuestion, dict[str, str], str]:
    """Renvoie (question typée, statut des faits exigés, modèle utilisé)."""
    _, system = load_prompt("parse_question")
    user = f"{_facts_block()}\n\nQuestion à analyser, entre les balises :\n<question>\n{question.strip()}\n</question>"
    last_error: Exception | None = None
    for attempt in range(2):
        data, model = router.generate_json("cheap", system, user if attempt == 0 else user + "\n\nLa réponse précédente ne respectait pas le schéma. Recommence.")
        try:
            parsed, status = _validate(data)
            return parsed, status, model
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            last_error = error
    raise ValueError(f"lecture de la question impossible : {last_error}")


def _validate(data: dict[str, Any]) -> tuple[ParsedQuestion, dict[str, str]]:
    families = [f for f in data.get("event_family", []) if f in GUARANTEE_FAMILIES]
    if not families:
        raise ValueError("aucune famille reconnue")
    raw_status = data.get("facts_status") or {}
    needed: list[str] = []
    status: dict[str, str] = {}
    for family in families:
        for fact in FACTS_NEEDED_BY_FAMILY.get(family, ()):
            if fact in needed:
                continue
            needed.append(fact)
            value = str(raw_status.get(fact, "absent")).strip().lower()
            status[fact] = value if value in ("donne", "absent", "sans_objet") else "absent"
    parsed = ParsedQuestion(
        event=str(data.get("event") or "autre"),
        event_family=families,
        object=data.get("object") or None,
        place=data.get("place") or None,
        circumstances=[str(c) for c in data.get("circumstances", [])][:10],
        facts_given=[str(f) for f in data.get("facts_given", [])][:12],
        facts_potentially_needed=[f for f in needed if status[f] == "absent"],
        question_type=data.get("question_type") if data.get("question_type") in ("couverture", "plafond", "franchise", "procedure") else "couverture",
    )
    return parsed, status


def describe(parsed: ParsedQuestion) -> str:
    """Résumé lisible de la question typée, pour le prompt du verdict."""
    return json.dumps(parsed.model_dump(), ensure_ascii=False, indent=1)
