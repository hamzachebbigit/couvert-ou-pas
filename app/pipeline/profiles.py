"""Profils de mise en page : comment reconnaître un titre dans chaque contrat.

Chaque assureur compose ses conditions générales avec sa propre typographie.
Plutôt qu'un modèle qui devine, une poignée de règles lisibles par contrat :
police, corps et graisse d'une ligne donnent son niveau dans le plan. Un
nouveau contrat demande un nouveau profil de dix lignes, pas un réentraînement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .models import Line

LevelRule = Callable[[Line], int | None]

# Un numéro d'article : « 12. », « 3.1.6 », « II. ». Un entier nu doit être suivi d'un point ou
# d'un espace (« 1er risque » n'est pas un numéro), un chiffre romain d'un point (« Vol » non plus).
NUMBER_RE = re.compile(
    r"^\s*(?:"
    r"(?P<roman>[IVX]{1,5})\.\s*"
    r"|(?P<dotted>\d+(?:\.\d+)+)\.?\s*"
    r"|(?P<plain>\d+)(?:\.\s*|\s+(?=[A-ZÀ-ÝÉ«(]))"
    r")(?=[A-ZÀ-ÝÉa-zà-ÿ«(]|$)"
)


def number_of(text: str) -> tuple[str | None, str]:
    """Sépare le numéro d'article du titre. Renvoie (numéro ou None, titre nettoyé)."""
    match = NUMBER_RE.match(text)
    if not match:
        return None, text.strip()
    number = match.group("roman") or match.group("dotted") or match.group("plain")
    return number, text[match.end():].strip()


def _font(line: Line, needle: str) -> bool:
    return needle.lower() in line.font.lower()


@dataclass
class Profile:
    """Les règles d'un contrat : pages à ignorer, colonnes, en-têtes, niveaux."""

    contract_id: str
    columns: int = 1
    skip_pages: tuple[int, ...] = ()
    header_footer_patterns: tuple[str, ...] = ()
    level_rules: list[LevelRule] = field(default_factory=list)
    merge_same_line: bool = True
    merge_consecutive_headings: bool = True
    definitions_chapter: str | None = None
    definition_term_rule: LevelRule | None = None
    scope_parts: tuple[str, ...] = ()
    body_size: float = 10.0

    def level_of(self, line: Line) -> int | None:
        for rule in self.level_rules:
            level = rule(line)
            if level is not None:
                return level
        return None


def _axa_rules() -> list[LevelRule]:
    def rule(line: Line) -> int | None:
        if _font(line, "FranklinGothic-Heavy") and line.size >= 16:
            return 1
        if _font(line, "FranklinGothic-Heavy") and line.size >= 12.5:
            return 2
        if _font(line, "FranklinGothic-Book") and line.size >= 11.5 and NUMBER_RE.match(line.text):
            return 3
        if _font(line, "FranklinGothic-Book") and line.size >= 11.5 and len(line.text) < 90:
            return 3
        return None

    return [rule]


def _baloise_rules() -> list[LevelRule]:
    def rule(line: Line) -> int | None:
        black = "BaloiseCreateText-Bl" in line.font
        if black and line.size >= 10.5:
            return 1
        if black and line.size >= 8.5:
            return 2
        return None

    return [rule]


def _baloise_term(line: Line) -> int | None:
    bold = "BaloiseCreateText-Bo" in line.font
    if bold and line.size >= 8.5 and len(line.text) <= 70 and not line.text.rstrip().endswith((",", ";", ".", ":")):
        return 3
    return None


# Parties du contrat Lalux posées en gras 17 sans numéro romain : elles ouvrent une partie à part entière.
LALUX_PART_RE = re.compile(r"^(Conditions Administratives|D[ée]finitions|Conditions G[ée]n[ée]rales)\b", re.I)


def _lalux_rules() -> list[LevelRule]:
    def rule(line: Line) -> int | None:
        trebuchet = _font(line, "Trebuchet")
        if not trebuchet:
            return None
        if line.size >= 17.5 and line.bold:
            return 0
        if line.size >= 16.5 and line.bold and LALUX_PART_RE.match(line.text):
            return 0
        if line.size >= 16.5 and line.bold:
            return 1
        if line.size >= 16.5 or (line.bold and 13.5 <= line.size < 16):
            return 2
        if line.size >= 11.5 and not line.bold:
            return 3
        if line.size >= 11.5 and line.bold and NUMBER_RE.match(line.text):
            return 3
        if 8.8 <= line.size < 11 and line.bold and (NUMBER_RE.match(line.text) or len(line.text) < 60):
            return 4
        return None

    return [rule]


PROFILES: dict[str, Profile] = {
    "axa_optihome_2025": Profile(
        contract_id="axa_optihome_2025",
        columns=1,
        skip_pages=(1, 2, 3, 4),
        header_footer_patterns=(r"^OPTIHOME\s+[–-]\s+CONDITIONS D.ASSURANCES\s*$", r"^\d{1,3}$"),
        level_rules=_axa_rules(),
        body_size=10.0,
    ),
    "baloise_home2_2024": Profile(
        contract_id="baloise_home2_2024",
        columns=2,
        skip_pages=(1, 2),
        header_footer_patterns=(
            r"^HOME\s*-\s*Conditions générales\s*\d*\s*$",
            r"^\d{1,2}\s*$",
            r"^CG-HOME\(2\)-LUFR-09-24\s*$",
            r"^Secret professionnel et traitement\s*$",
        ),
        level_rules=_baloise_rules(),
        definitions_chapter="1",
        definition_term_rule=_baloise_term,
        body_size=9.0,
    ),
    "lalux_easyprotect_2017": Profile(
        contract_id="lalux_easyprotect_2017",
        columns=1,
        skip_pages=(1, 2),
        header_footer_patterns=(
            r"^Assurance easy-PROTECT\s*$",
            r"^Dispositions Générales\s*$",
            r"^Conditions Générales\s*$",
            r"^l?\s*PAGE\s*\d+\s*/\s*\d+\s*$",
            r"LA LUXEMBOURGEOISE Société Anonyme",
            r"R\.C\.S\. Luxembourg B 31035",
        ),
        level_rules=_lalux_rules(),
        scope_parts=(r"ASSURANCES?\s*HABITATION", r"BASES G[ÉE]N[ÉE]RALES", r"CONDITIONS G[ÉE]N[ÉE]RALES", r"CONDITIONS ADMINISTRATIVES", r"^D[ÉE]FINITIONS"),
        body_size=8.0,
    ),
}


def profile_for(contract_id: str) -> Profile:
    try:
        return PROFILES[contract_id]
    except KeyError as error:
        raise KeyError(f"aucun profil de mise en page pour {contract_id}") from error
