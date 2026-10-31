"""Contrats typés du pipeline.

Chaque objet qui circule entre deux briques est un modèle Pydantic. Une
valeur absente est une valeur, pas une chaîne vide : `Cited.value` vaut None
quand le contrat ne dit rien, et `information_insuffisante` est un verdict,
pas un chemin d'erreur.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VerdictLabel = Literal["couvert", "non_couvert", "ambigu", "information_insuffisante"]
ClauseRole = Literal["garantie", "exclusion", "condition", "definition", "plafond", "franchise"]
QuestionType = Literal["couverture", "plafond", "franchise", "procedure"]

GUARANTEE_FAMILIES: tuple[str, ...] = (
    "incendie",
    "degats_eaux",
    "vol",
    "tempete",
    "grele",
    "catnat",
    "bris_glace",
    "rc",
    "dommages_electriques",
    "pertes_denrees",
    "dommages_accidentels",
    "assistance",
    "protection_juridique",
    "definitions",
    "exclusions_generales",
    "biens_assures",
    "inoccupation",
    "sinistre_procedure",
    "franchises_plafonds",
)


class Line(BaseModel):
    """Une ligne de texte du PDF, avec sa page et sa géométrie."""

    page: int
    line: int
    text: str
    bbox: tuple[float, float, float, float]
    size: float
    bold: bool
    font: str


class Clause(BaseModel):
    """Une clause du contrat, l'unité qui est recherchée et citée."""

    contract_id: str
    clause_id: str
    number: str | None = None
    title: str
    level: int
    parent_id: str | None = None
    path: str
    page_start: int
    page_end: int
    text: str
    families: list[str] = Field(default_factory=list)


class TableRow(BaseModel):
    """Une rangée de tableau sérialisée avec ses en-têtes."""

    contract_id: str
    row_id: str
    clause_id: str | None
    page: int
    headers: list[str]
    values: list[str]
    serialized: str
    families: list[str] = Field(default_factory=list)


class Cited(BaseModel):
    """Une valeur extraite avec sa citation. None veut dire : non trouvé."""

    value: str | None = None
    page: int | None = None
    clause_id: str | None = None
    quote: str | None = Field(default=None, max_length=400)


class ContractRow(BaseModel):
    """La ligne structurée d'un contrat, remplie une fois à l'ingestion."""

    contract_id: str
    insurer: str
    product: str
    edition: str | None
    pages: int
    guarantee_families: list[str]
    theft_conditions: Cited
    theft_common_areas: Cited
    bike_cap: Cited
    jewellery_cap: Cited
    deductible_general: Cited
    unoccupancy_limit: Cited
    heat_without_fire_excluded: Cited
    contents_outside_building: Cited
    accidental_damage_option: Cited
    notable_exclusions: list[Cited] = Field(default_factory=list)


class ParsedQuestion(BaseModel):
    """La question lue en champs typés avant toute recherche."""

    event: str
    event_family: list[str]
    object: str | None = None
    place: str | None = None
    circumstances: list[str] = Field(default_factory=list)
    facts_given: list[str] = Field(default_factory=list)
    facts_potentially_needed: list[str] = Field(default_factory=list)
    question_type: QuestionType = "couverture"


class CitedClause(BaseModel):
    """Une clause citée par le verdict, avec le passage exact."""

    clause_id: str
    page: int
    quote: str
    role: ClauseRole
    title: str | None = None
    verified: bool = True


class Verdict(BaseModel):
    """La réponse typée. Les vérifications de code s'appliquent après le modèle."""

    verdict: VerdictLabel
    summary: str
    reasoning: list[str] = Field(default_factory=list)
    cited: list[CitedClause] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    if_then: list[str] = Field(default_factory=list)
    cap: Cited | None = None
    deductible: Cited | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    alternative_reading: str | None = None
    notes: list[str] = Field(default_factory=list)


class RetrievedClause(BaseModel):
    """Une clause candidate avec ses scores de recherche."""

    clause_id: str
    title: str
    path: str
    page_start: int
    page_end: int
    text: str
    families: list[str]
    bm25_rank: int | None = None
    embed_rank: int | None = None
    fused_score: float = 0.0
    rerank_score: float | None = None
    always_included: bool = False
    kind: Literal["clause", "table_row"] = "clause"


class StageTiming(BaseModel):
    """Durée d'une étape du pipeline."""

    stage: str
    ms: int


class Trace(BaseModel):
    """Ce qui s'est passé pour produire le verdict. Affiché dans l'interface."""

    cache_hit: bool = False
    parsed: ParsedQuestion | None = None
    candidates_after_filter: int = 0
    candidates_after_fusion: int = 0
    candidates_after_rerank: int = 0
    retrieved: list[RetrievedClause] = Field(default_factory=list)
    models: dict[str, str] = Field(default_factory=dict)
    timings: list[StageTiming] = Field(default_factory=list)
    prompt_version: str = ""
    post_checks: list[str] = Field(default_factory=list)
    total_ms: int = 0


class AnalyseResponse(BaseModel):
    """La réponse de l'API : verdict, trace, et les clauses citées en entier."""

    contract_id: str
    question: str
    verdict: Verdict
    trace: Trace
    clauses: dict[str, Clause] = Field(default_factory=dict)
