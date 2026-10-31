"""Recherche : filtre d'abord, hybride ensuite, arbitre à la fin.

1. Filtre : le contrat choisi et les familles de garanties de la question,
   plus les définitions, les exclusions générales, les biens assurés et les
   plafonds, toujours candidats.
2. Hybride : BM25 et embeddings sur les candidats, fusionnés par rang
   réciproque.
3. Arbitre : un appel au modèle économique note les finalistes de 0 à 3,
   les 6 à 8 meilleurs partent au verdict.
4. Toujours présents : la définition de l'événement et la clause
   d'exclusions générales, déclarées et non découvertes.
"""

from __future__ import annotations

import json
import re

from .families import QUERY_TERMS, fold
from .index import Index, Unit
from .models import ParsedQuestion, RetrievedClause, Trace
from .prompts import load_prompt
from .providers import ProviderError, Router

ALWAYS_FAMILIES = ("definitions", "exclusions_generales", "biens_assures", "franchises_plafonds")
FUSION_K = 60
TOP_PER_SIGNAL = 20
FINAL_COUNT = 8
MIN_COUNT = 5


def retrieve(router: Router, index: Index, contract_id: str, question: str, parsed: ParsedQuestion, trace: Trace) -> list[RetrievedClause]:
    """Renvoie les clauses retenues pour le verdict, scores compris."""
    families = list(dict.fromkeys([*parsed.event_family, *ALWAYS_FAMILIES]))
    positions = index.candidates(contract_id, families)
    trace.candidates_after_filter = len(positions)
    units = index.units[contract_id]

    query = _query_text(question, parsed)
    bm25 = index.bm25_rank(contract_id, query, positions, TOP_PER_SIGNAL)
    embed: list[tuple[int, float]] = []
    try:
        if index.vectors.get(contract_id) is not None:
            vector = router.embed([query], task_type="RETRIEVAL_QUERY")[0]
            embed = index.embed_rank(contract_id, vector, positions, TOP_PER_SIGNAL)
            trace.models["embed"] = router.embed_model
    except ProviderError as error:
        trace.post_checks.append(f"embeddings indisponibles ({str(error)[:80]}), BM25 seul")

    fused: dict[int, float] = {}
    bm25_rank: dict[int, int] = {}
    embed_rank: dict[int, int] = {}
    for rank, (position, _) in enumerate(bm25, start=1):
        fused[position] = fused.get(position, 0.0) + 1.0 / (FUSION_K + rank)
        bm25_rank[position] = rank
    for rank, (position, _) in enumerate(embed, start=1):
        fused[position] = fused.get(position, 0.0) + 1.0 / (FUSION_K + rank)
        embed_rank[position] = rank
    ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:TOP_PER_SIGNAL]
    trace.candidates_after_fusion = len(ordered)

    candidates = [
        RetrievedClause(
            clause_id=units[p].unit_id,
            title=units[p].title,
            path=units[p].path,
            page_start=units[p].page_start,
            page_end=units[p].page_end,
            text=units[p].text,
            families=units[p].families,
            bm25_rank=bm25_rank.get(p),
            embed_rank=embed_rank.get(p),
            fused_score=score,
            kind="table_row" if units[p].kind == "table_row" else "clause",
        )
        for p, score in ordered
    ]

    scores = _rerank(router, question, candidates, trace)
    for candidate in candidates:
        candidate.rerank_score = scores.get(candidate.clause_id)
    candidates.sort(key=lambda c: ((c.rerank_score if c.rerank_score is not None else 1.5), c.fused_score), reverse=True)
    chosen = [c for c in candidates if (c.rerank_score is None or c.rerank_score >= 1)][:FINAL_COUNT]
    if len(chosen) < MIN_COUNT:
        # L'arbitre a tout écarté ou presque : les meilleurs de la fusion restent au dossier, notés comme tels,
        # pour que le verdict ne se prononce jamais sur un contrat vide.
        kept = {c.clause_id for c in chosen}
        for candidate in sorted(candidates, key=lambda c: c.fused_score, reverse=True):
            if len(chosen) >= MIN_COUNT:
                break
            if candidate.clause_id not in kept:
                chosen.append(candidate)
                kept.add(candidate.clause_id)
        trace.post_checks.append(f"arbitre trop sévère, {MIN_COUNT} clauses de la fusion gardées")

    for extra in _always_included(units, parsed, chosen):
        chosen.append(extra)
    trace.candidates_after_rerank = len(chosen)
    trace.retrieved = [c.model_copy(update={"text": c.text[:400]}) for c in chosen]
    return chosen


def _query_text(question: str, parsed: ParsedQuestion) -> str:
    """La question enrichie des champs typés, pour les deux signaux de recherche."""
    extras = [parsed.event, parsed.object or "", parsed.place or "", *parsed.circumstances]
    vocabulary = [QUERY_TERMS[f] for f in parsed.event_family if f in QUERY_TERMS]
    return f"{question} {' '.join(e for e in extras if e)} {' '.join(vocabulary)}"


def _rerank(router: Router, question: str, candidates: list[RetrievedClause], trace: Trace) -> dict[str, float]:
    """Un seul appel : l'arbitre note tous les finalistes."""
    if not candidates:
        return {}
    _, system = load_prompt("rerank")
    listing = "\n\n".join(f"[{c.clause_id}] {c.path}\n{c.text[:1200]}" for c in candidates)
    user = f"Question, entre balises :\n<question>\n{question}\n</question>\n\nClauses candidates :\n\n{listing}"
    try:
        data, model = router.generate_json("cheap", system, user)
        trace.models["rerank"] = model
        raw = data.get("scores", {}) if isinstance(data, dict) else {}
        return {str(k): float(v) for k, v in raw.items() if _is_number(v)}
    except (ProviderError, ValueError, TypeError) as error:
        trace.post_checks.append(f"reclassement indisponible ({str(error)[:80]}), fusion seule")
        return {}


def _is_number(value: object) -> bool:
    try:
        float(value)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


def _always_included(units: list[Unit], parsed: ParsedQuestion, chosen: list[RetrievedClause]) -> list[RetrievedClause]:
    """La définition de l'événement et les exclusions générales, si elles manquent."""
    present = {c.clause_id for c in chosen}
    extras: list[RetrievedClause] = []
    terms = [fold(t) for t in [parsed.event, parsed.object or ""] if t]
    terms = [t for t in terms if len(t) >= 3]

    def add(unit: Unit) -> None:
        if unit.unit_id not in present:
            present.add(unit.unit_id)
            extras.append(
                RetrievedClause(
                    clause_id=unit.unit_id, title=unit.title, path=unit.path, page_start=unit.page_start, page_end=unit.page_end,
                    text=unit.text, families=unit.families, always_included=True, kind="clause",
                )
            )

    definitions = [u for u in units if "definitions" in u.families and u.kind == "clause" and len(u.text) < 2500]
    for unit in definitions:
        title = fold(unit.title)
        if any(re.search(rf"\b{re.escape(t)}", title) for t in terms) and len(extras) < 2:
            add(unit)
    exclusions = [u for u in units if "exclusions_generales" in u.families and u.kind == "clause" and u.level <= 2 and "exclusion" in fold(u.title)]
    exclusions.sort(key=lambda u: (u.level, len(u.text)))
    if exclusions:
        add(exclusions[0])
    return extras


def dump_for_prompt(chosen: list[RetrievedClause]) -> str:
    """Les clauses retenues telles qu'elles entrent dans le prompt du verdict."""
    blocks = []
    for c in chosen:
        header = f"[{c.clause_id}] {c.path} (pages {c.page_start} à {c.page_end})"
        blocks.append(f"{header}\n{c.text}")
    return "\n\n".join(blocks)


def as_json(chosen: list[RetrievedClause]) -> str:
    return json.dumps([c.model_dump() for c in chosen], ensure_ascii=False)
