"""Familles de garanties : le vocabulaire commun aux clauses et aux questions.

Une clause reçoit ses familles par son titre et son chemin dans le plan,
puis par des mots-clés dans son texte. La question reçoit les siennes à la
lecture. Le filtre de recherche ne retient que les clauses dont une famille
rencontre celles de la question, plus les définitions et les exclusions
générales, toujours présentes.
"""

from __future__ import annotations

import re
import unicodedata

from .models import GUARANTEE_FAMILIES


def fold(text: str) -> str:
    """Minuscules sans accents, pour comparer des mots sans se soucier de la typographie."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


# Mots-clés du titre ou du chemin d'une clause. Le titre est le signal le plus sûr.
TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "incendie": ("incendie", "explosion", "foudre", "fumee", "feu"),
    "degats_eaux": ("degats des eaux", "degat des eaux", "eaux", "fuite", "infiltration", "gel", "mazout", "liquide"),
    "vol": ("vol", "vandalisme", "cambriolage", "effraction", "antivol"),
    "tempete": ("tempete", "vent", "neige", "poids de la neige"),
    "grele": ("grele",),
    "catnat": ("catastrophe", "inondation", "tremblement", "seisme", "glissement", "naturel"),
    "bris_glace": ("bris", "vitres", "vitrage", "verre", "glaces"),
    "rc": ("responsabilite", "recours", "tiers", "voisins", "locataire"),
    "dommages_electriques": ("electri", "surtension", "appareils", "court-circuit", "foudre"),
    "pertes_denrees": ("denrees", "congel", "refriger", "cave a vin"),
    "dommages_accidentels": ("tous risques", "accidentel", "dommages accidentels", "serenite", "confort"),
    "assistance": ("assistance", "depannage"),
    "protection_juridique": ("protection juridique", "juridique"),
    "definitions": ("definition", "lexique", "glossaire"),
    "exclusions_generales": ("exclusions generales", "exclusions communes", "exclusion", "ne sont pas garantis", "non assure"),
    "biens_assures": ("biens assures", "biens designes", "contenu", "mobilier", "objets", "batiment", "dependances", "jardin"),
    "inoccupation": ("inoccup", "inhabit", "absence", "vacance"),
    "sinistre_procedure": ("sinistre", "declaration", "obligations", "indemnisation", "indemnite", "estimation", "expertise"),
    "franchises_plafonds": ("franchise", "plafond", "limite", "montant", "sommes assurees", "tableau", "capital"),
}

# Mots-clés du corps de la clause, un seuil plus haut parce que le texte est bavard.
BODY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "incendie": ("incendie", "explosion", "chaleur", "flamme", "brule", "roussi"),
    "degats_eaux": ("fuite", "infiltration", "eau", "canalisation", "debordement"),
    "vol": ("vol ", "voleur", "effraction", "escalade", "antivol", "cambriol"),
    "tempete": ("tempete", "vent", "ouragan", "neige"),
    "grele": ("grele",),
    "catnat": ("inondation", "tremblement", "glissement", "affaissement"),
    "bris_glace": ("vitr", "verre", "bris"),
    "rc": ("responsabilite civile", "tiers", "recours"),
    "dommages_electriques": ("surtension", "court-circuit", "electrique"),
    "pertes_denrees": ("denrees", "congel"),
    "dommages_accidentels": ("tous risques", "accidentel"),
    "inoccupation": ("inoccup", "inhabit", "jours consecutifs", "absence"),
    "franchises_plafonds": ("franchise", "plafond", "eur", "limite d'indemnite"),
}


def families_for_clause(title: str, path: str, text: str) -> list[str]:
    """Attribue les familles d'une clause, titre d'abord, texte ensuite."""
    found: list[str] = []
    head = fold(f"{path} {title}")
    for family, words in TITLE_KEYWORDS.items():
        if any(word in head for word in words):
            found.append(family)
    body = fold(text)
    for family, words in BODY_KEYWORDS.items():
        if family in found:
            continue
        hits = sum(len(re.findall(re.escape(word), body)) for word in words)
        if hits >= 3:
            found.append(family)
    return [f for f in GUARANTEE_FAMILIES if f in found]


# Faits qu'un événement exige en général. Remplis par des règles, pas par le modèle.
FACTS_NEEDED_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "vol": (
        "y a-t-il eu effraction (porte ou fenêtre forcée) ?",
        "le lieu était-il fermé à clé ?",
        "l'objet volé était-il attaché par un antivol (pour un vélo ou un objet laissé dehors) ?",
        "le vol a-t-il eu lieu à l'intérieur de l'habitation, dans une dépendance ou un local commun, ou hors du domicile ?",
    ),
    "incendie": (
        "y a-t-il eu des flammes ou un incendie déclaré, ou seulement de la chaleur ?",
        "le bien endommagé est-il à l'intérieur de l'habitation ou dehors ?",
    ),
    "degats_eaux": (
        "d'où vient l'eau (canalisation, appareil, toiture, voisin) ?",
        "le logement était-il occupé ou inoccupé depuis longtemps ?",
    ),
    "tempete": ("la vitesse du vent ou un bulletin d'alerte est-il disponible ?",),
    "rc": ("qui a causé le dommage et à qui (membre du foyer, animal, tiers) ?",),
    "dommages_electriques": ("l'appareil a-t-il grillé après une surtension ou une foudre, ou par usure ?",),
    "inoccupation": ("depuis combien de jours le logement était-il inoccupé ?",),
    "catnat": ("l'événement a-t-il été reconnu comme catastrophe naturelle ?",),
}
