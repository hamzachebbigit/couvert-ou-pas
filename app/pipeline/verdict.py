"""Le verdict typé et ses vérifications de code.

Un seul appel au modèle de verdict, sur les clauses retenues. Puis le code, pas le
prompt, applique trois règles :
1. Chaque citation doit être un extrait exact de la clause. Sinon elle tombe,
   et un verdict qui ne tient plus sur rien devient ambigu.
2. Un verdict couvert ou non_couvert sans clause citée devient
   information_insuffisante.
3. Un verdict couvert ou non_couvert alors qu'une clause citée dépend d'un
   fait absent de la question (effraction, antivol, local fermé à clé) devient
   information_insuffisante, avec la question à poser : un vol dans un local
   non fermé n'est ni couvert ni exclu tant qu'on ignore s'il y a eu effraction.
   Les autres faits de la liste informent le modèle, qui décide s'ils changent
   le verdict.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from pydantic import ValidationError

from .cache import Cache, cache_key
from .families import fold, gate_terms
from .index import Index
from .models import AnalyseResponse, Cited, CitedClause, Clause, ParsedQuestion, RetrievedClause, Trace, Verdict
from .prompts import load_prompt, prompt_version
from .providers import ProviderError, Router
from .question import describe, parse_question
from .retrieve import dump_for_prompt, retrieve
from .trace import Stopwatch

MAX_QUESTION_CHARS = 500


class AnalysisError(RuntimeError):
    """Erreur présentable à l'utilisateur."""


def normalise_for_match(text: str) -> str:
    """Rend deux graphies du même passage comparables : apostrophes, guillemets, espaces, tirets."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("«", '"').replace("»", '"')
    text = text.replace("–", "-").replace("—", "-").replace("\u00AD", "")
    text = re.sub(r"(\w)-\s+(?=[a-zà-ÿ])", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def verify_quote(quote: str, clause_text: str) -> tuple[bool, str]:
    """Vérifie qu'une citation est un extrait de la clause.

    Renvoie (vérifiée, citation telle qu'elle figure dans la clause). Une
    citation qui diffère par la coupure d'un mot ou une apostrophe est
    rapprochée du texte réel, une citation inventée est rejetée.
    """
    if not quote or len(quote) < 8:
        return False, quote
    source = clause_text
    normalised_source = normalise_for_match(source)
    normalised_quote = normalise_for_match(quote).strip("\"' ")
    if normalised_quote and normalised_quote in normalised_source:
        return True, _recover_span(source, normalised_quote)
    matcher = difflib.SequenceMatcher(None, normalised_source, normalised_quote, autojunk=False)
    block = matcher.find_longest_match(0, len(normalised_source), 0, len(normalised_quote))
    if block.size >= max(20, int(0.85 * len(normalised_quote))):
        matched = normalised_source[block.a : block.a + block.size]
        return True, _recover_span(source, matched)
    return False, quote


def _recover_span(source: str, normalised_fragment: str) -> str:
    """Retrouve dans le texte d'origine le passage dont on connaît la forme normalisée."""
    normalised_source = normalise_for_match(source)
    start = normalised_source.find(normalised_fragment)
    if start < 0:
        return normalised_fragment
    # Les deux chaînes ont presque la même longueur : on cherche la fenêtre d'origine la plus proche.
    best = source[start : start + len(normalised_fragment)]
    for offset in range(-12, 13):
        candidate = source[max(0, start + offset) : max(0, start + offset) + len(normalised_fragment)]
        if normalise_for_match(candidate) == normalised_fragment:
            return candidate.strip()
    return best.strip()


def clause_text_for(clause_id: str, chosen: list[RetrievedClause], lookup: dict[str, Clause]) -> tuple[str, Clause | None]:
    """Le texte complet de la clause citée (une rangée de tableau cite son texte sérialisé)."""
    base = clause_id.split("#")[0]
    if base.startswith("row:"):
        for c in chosen:
            if c.clause_id == clause_id:
                return c.text, None
        return "", None
    clause = lookup.get(base)
    return (f"{clause.title} {clause.text}" if clause else ""), clause


def post_check(verdict: Verdict, parsed: ParsedQuestion, chosen: list[RetrievedClause], lookup: dict[str, Clause], trace: Trace) -> Verdict:
    """Les trois règles de code. Elles rétrogradent, jamais ne promeuvent."""
    kept: list[CitedClause] = []
    allowed = {c.clause_id for c in chosen} | {c.clause_id.split("#")[0] for c in chosen}
    for cited in verdict.cited:
        if cited.clause_id not in allowed:
            trace.post_checks.append(f"citation hors clauses fournies retirée : {cited.clause_id}")
            continue
        text, clause = clause_text_for(cited.clause_id, chosen, lookup)
        ok, fixed = verify_quote(cited.quote, text)
        if not ok:
            trace.post_checks.append(f"citation non vérifiée retirée : {cited.clause_id}")
            continue
        if fixed != cited.quote:
            trace.post_checks.append(f"citation ajustée au texte réel : {cited.clause_id}")
        page = cited.page
        if clause and not (clause.page_start <= page <= clause.page_end):
            page = clause.page_start
        kept.append(cited.model_copy(update={"quote": fixed, "page": page, "title": clause.title if clause else "Tableau", "verified": True, "clause_id": cited.clause_id.split("#")[0] if not cited.clause_id.startswith("row:") else cited.clause_id}))
    verdict.cited = kept

    for field_name in ("cap", "deductible"):
        value: Cited | None = getattr(verdict, field_name)
        if value and value.quote and value.clause_id:
            text, _ = clause_text_for(value.clause_id, chosen, lookup)
            ok, fixed = verify_quote(value.quote, text)
            if ok:
                value.quote = fixed
                value.clause_id = value.clause_id.split("#")[0]
            else:
                trace.post_checks.append(f"{field_name} : citation non vérifiée retirée")
                setattr(verdict, field_name, None)

    if verdict.verdict in ("couvert", "non_couvert") and not verdict.cited:
        trace.post_checks.append("verdict assuré sans clause vérifiée : rétrogradé en information_insuffisante")
        verdict.verdict = "information_insuffisante"
        verdict.notes.append("Aucune citation n'a pu être vérifiée dans le contrat, le verdict est suspendu.")
        if not verdict.missing_facts:
            verdict.missing_facts = ["Quelle clause du contrat traite précisément ce sinistre ?"]
        verdict.confidence = min(verdict.confidence, 0.4)

    if verdict.verdict in ("couvert", "non_couvert"):
        gated = _gated_facts(parsed, verdict, chosen, lookup)
        if gated:
            trace.post_checks.append(f"verdict {verdict.verdict} alors qu'une clause citée dépend d'un fait absent : rétrogradé en information_insuffisante")
            verdict.verdict = "information_insuffisante"
            for fact in gated:
                if fact not in verdict.missing_facts:
                    verdict.missing_facts.append(fact)
            verdict.notes.append("Une clause citée dépend d'un fait que la question ne donne pas.")
            verdict.confidence = min(verdict.confidence, 0.6)

    if verdict.verdict in ("couvert", "non_couvert") and verdict.missing_facts:
        trace.post_checks.append("verdict assuré accompagné de faits manquants : rétrogradé en information_insuffisante")
        verdict.verdict = "information_insuffisante"
        verdict.confidence = min(verdict.confidence, 0.6)

    if verdict.verdict == "ambigu" and not verdict.alternative_reading:
        verdict.alternative_reading = "Le contrat se lit de deux façons sur ce point, voir le raisonnement."
    verdict.confidence = max(0.0, min(1.0, verdict.confidence))
    return verdict


def _gated_facts(parsed: ParsedQuestion, verdict: Verdict, chosen: list[RetrievedClause], lookup: dict[str, Clause]) -> list[str]:
    """Les faits absents dont une clause citée dépend : ses mots-clés figurent dans le texte cité."""
    cited_text = fold(" ".join(clause_text_for(c.clause_id, chosen, lookup)[0] for c in verdict.cited))
    absent = list(parsed.facts_potentially_needed)
    effraction_known = not any("effraction" in fold(f) for f in absent)
    gated: list[str] = []
    for fact in absent:
        if effraction_known and "ferme a cle" in fold(fact):
            continue  # une effraction donnée rend la question de la fermeture sans objet
        terms = gate_terms(fact)
        if terms and any(term in cited_text for term in terms):
            gated.append(fact)
    return gated


def _coerce_verdict(data: dict[str, Any]) -> Verdict:
    """Valide la sortie du modèle, en tolérant des champs null là où une liste est attendue."""
    cleaned = dict(data)
    for key in ("reasoning", "cited", "missing_facts", "if_then"):
        if cleaned.get(key) is None:
            cleaned[key] = []
    for key in ("cap", "deductible"):
        value = cleaned.get(key)
        if isinstance(value, dict) and not value.get("value"):
            cleaned[key] = None
    if isinstance(cleaned.get("cited"), list):
        cleaned["cited"] = [c for c in cleaned["cited"] if isinstance(c, dict) and c.get("clause_id") and c.get("quote")]
        for c in cleaned["cited"]:
            c.setdefault("page", 0)
            if c.get("page") is None:
                c["page"] = 0
            if c.get("role") not in ("garantie", "exclusion", "condition", "definition", "plafond", "franchise"):
                c["role"] = "condition"
    if cleaned.get("confidence") is None:
        cleaned["confidence"] = 0.5
    return Verdict(**cleaned)


def analyse(router: Router, index: Index, cache: Cache, contract_id: str, question: str, *, daily_cap: int, client_ip: str, per_ip_cap: int) -> AnalyseResponse:
    """Le pipeline complet, du cache au verdict vérifié."""
    question = question.strip()
    if not question or len(question) > MAX_QUESTION_CHARS:
        raise AnalysisError(f"La question doit faire entre 1 et {MAX_QUESTION_CHARS} caractères.")
    if contract_id not in index.units:
        raise AnalysisError("Contrat inconnu.")
    version = prompt_version()
    model_tag = router.config.model_verdict or router.config.secondary_model
    key = cache_key(contract_id, question, version, model_tag)
    cached = cache.get(key)
    lookup = index.clause_lookup(contract_id)
    if cached:
        response = AnalyseResponse(**cached)
        response.trace.cache_hit = True
        response.clauses = _clauses_for(response.verdict, lookup)
        return response
    if not router.config.has_llm:
        raise AnalysisError("Aucun fournisseur de modèle n'est configuré, seules les questions déjà analysées sont disponibles.")
    if not cache.reserve_ip_minute(client_ip, per_ip_cap):
        raise AnalysisError("Trop de questions en une minute, réessayez dans un instant.")
    if not cache.reserve_daily(daily_cap):
        raise AnalysisError("Le quota d'analyses nouvelles du jour est atteint, les questions d'exemple restent disponibles.")

    trace = Trace(prompt_version=version)
    watch = Stopwatch(trace)
    try:
        with watch.stage("lecture de la question"):
            parsed, status, model = parse_question(router, question)
            trace.models["parse"] = model
            trace.parsed = parsed
        with watch.stage("recherche"):
            chosen = retrieve(router, index, contract_id, question, parsed, trace)
        with watch.stage("verdict"):
            verdict, model = _call_verdict(router, question, parsed, status, chosen)
            trace.models["verdict"] = model
            if router.config.model_verdict and model != f"gemini:{router.config.model_verdict}":
                trace.post_checks.append(f"modèle de verdict indisponible, réponse du modèle de repli {model}")
        with watch.stage("vérifications"):
            verdict = post_check(verdict, parsed, chosen, lookup, trace)
    except ProviderError as error:
        raise AnalysisError(f"Le fournisseur de modèle n'a pas répondu : {str(error)[:160]}") from error
    except ValueError as error:
        raise AnalysisError(str(error)) from error
    watch.close()
    response = AnalyseResponse(contract_id=contract_id, question=question, verdict=verdict, trace=trace)
    cache.put(key, contract_id, question, version, model_tag, response.model_dump())
    response.clauses = _clauses_for(verdict, lookup)
    return response


def _call_verdict(router: Router, question: str, parsed: ParsedQuestion, status: dict[str, str], chosen: list[RetrievedClause]) -> tuple[Verdict, str]:
    _, system = load_prompt("verdict")
    absent = [f for f, s in status.items() if s == "absent"]
    facts = "\n".join(f"- {f}" for f in absent) or "- aucun"
    user = (
        f"Question, entre balises :\n<question>\n{question}\n</question>\n\n"
        f"Lecture typée de la question :\n{describe(parsed)}\n\n"
        f"Faits que ce type de sinistre peut exiger et que la question ne donne pas (ils ne comptent que si une clause citée en dépend) :\n{facts}\n\n"
        f"Clauses du contrat (les seules que tu connais) :\n\n{dump_for_prompt(chosen)}"
    )
    last: Exception | None = None
    for attempt in range(2):
        data, model = router.generate_json("verdict", system, user if attempt == 0 else user + "\n\nLa réponse précédente ne respectait pas le schéma JSON demandé. Recommence.")
        try:
            return _coerce_verdict(data), model
        except (ValidationError, TypeError, ValueError) as error:
            last = error
    raise ValueError(f"verdict invalide : {last}")


def _clauses_for(verdict: Verdict, lookup: dict[str, Clause]) -> dict[str, Clause]:
    ids = {c.clause_id for c in verdict.cited}
    for value in (verdict.cap, verdict.deductible):
        if value and value.clause_id:
            ids.add(value.clause_id)
    return {i: lookup[i] for i in ids if i in lookup}
