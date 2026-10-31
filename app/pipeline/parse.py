"""Parsing : du PDF aux tables de clauses et de rangées.

Trois étapes, payées une fois par contrat :
1. Les lignes. PyMuPDF donne chaque ligne avec sa page, sa police, son corps,
   sa graisse et sa boîte. Les en-têtes et pieds de page sont retirés, les
   colonnes sont remises dans l'ordre de lecture.
2. Le plan. Le profil de mise en page du contrat dit quelles lignes sont des
   titres et à quel niveau. Chaque titre ouvre une clause, le texte qui suit
   lui appartient jusqu'au titre suivant.
3. Les tableaux. Docling les lit et chaque rangée devient une unité de
   recherche qui emporte ses en-têtes.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .families import families_for_clause, fold
from .models import Clause, Line, TableRow
from .profiles import NUMBER_RE, Profile, number_of, profile_for

HYPHEN_BREAK = re.compile(r"(\w)-\s+(?=[a-zà-ÿ])")
# Glyphes de polices de symboles (zone à usage privé) et caractères invisibles : retirés du texte.
PRIVATE_OR_INVISIBLE = re.compile("[\uE000-\uF8FF\u200B-\u200F\u202A-\u202E\u2060\uFEFF]")


def clean_text(text: str) -> str:
    """Normalise la typographie et retire ce qui n'est pas du texte lisible."""
    text = unicodedata.normalize("NFKC", text)
    text = PRIVATE_OR_INVISIBLE.sub(" ", text)
    text = text.replace("\t", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str, limit: int = 48) -> str:
    """Identifiant lisible à partir d'un titre."""
    folded = fold(text)
    folded = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")
    return folded[:limit].rstrip("_") or "clause"


def extract_lines(pdf_path: Path, profile: Profile) -> list[Line]:
    """Lignes du PDF dans l'ordre de lecture, avec leur typographie.

    Les espaces sont reconstruits à partir de l'écart entre caractères, parce
    que certains PDF justifiés perdent les espaces dans les passages en gras.
    """
    import pymupdf  # import local : l'application en ligne n'a pas besoin du parseur

    doc = pymupdf.open(pdf_path)
    patterns = [re.compile(p, re.I) for p in profile.header_footer_patterns]
    lines: list[Line] = []
    counter = 0
    for page_index, page in enumerate(doc):
        page_no = page_index + 1
        if page_no in profile.skip_pages:
            continue
        width = page.rect.width
        raw = page.get_text("rawdict")
        page_lines: list[tuple[int, float, float, Line]] = []
        for block in raw["blocks"]:
            if block.get("type") != 0:
                continue
            for raw_line in block["lines"]:
                text, size, bold, font = _assemble(raw_line)
                if not text:
                    continue
                if any(p.search(text) for p in patterns):
                    continue
                x0, y0, x1, y1 = raw_line["bbox"]
                column = int(x0 >= width * 0.48) if profile.columns == 2 else 0
                counter += 1
                page_lines.append((column, y0, x0, Line(page=page_no, line=counter, text=text, bbox=(x0, y0, x1, y1), size=size, bold=bold, font=font)))
        page_lines.sort(key=lambda item: (item[0], round(item[1] / 3), item[2]))
        ordered = [item[3] for item in page_lines]
        lines.extend(_merge_same_baseline(ordered) if profile.merge_same_line else ordered)
    return lines


def _assemble(raw_line: dict) -> tuple[str, float, bool, str]:
    """Reconstruit le texte d'une ligne caractère par caractère."""
    chars: list[str] = []
    prev_x1: float | None = None
    sizes: list[float] = []
    bolds: list[bool] = []
    fonts: list[str] = []
    for span in raw_line["spans"]:
        size = float(span["size"])
        font = span["font"]
        bold = "bold" in font.lower() or "black" in font.lower() or "heavy" in font.lower() or bool(span["flags"] & 16)
        for ch in span["chars"]:
            glyph = ch["c"]
            x0, _, x1, _ = ch["bbox"]
            if prev_x1 is not None and x0 - prev_x1 > 0.16 * size and chars and chars[-1] != " " and glyph != " ":
                chars.append(" ")
            chars.append(glyph)
            prev_x1 = x1
            if glyph.strip():
                sizes.append(size)
                bolds.append(bold)
                fonts.append(font)
    text = clean_text("".join(chars))
    if not sizes:
        return "", 0.0, False, ""
    size = round(max(sizes), 1)
    bold = sum(bolds) >= 0.8 * len(bolds)
    font = max(set(fonts), key=fonts.count)
    return text, size, bold, font


def _merge_same_baseline(lines: list[Line]) -> list[Line]:
    """Fusionne un numéro et son titre posés sur la même ligne de base."""
    out: list[Line] = []
    for line in lines:
        if out:
            prev = out[-1]
            same_page = prev.page == line.page
            prev_mid = (prev.bbox[1] + prev.bbox[3]) / 2
            mid = (line.bbox[1] + line.bbox[3]) / 2
            close = abs(prev_mid - mid) < 0.6 * max(prev.size, line.size)
            right_of = line.bbox[0] >= prev.bbox[2] - 2
            if same_page and close and right_of and abs(prev.size - line.size) <= 1.5:
                out[-1] = prev.model_copy(
                    update={
                        "text": f"{prev.text} {line.text}".strip(),
                        "bbox": (prev.bbox[0], min(prev.bbox[1], line.bbox[1]), line.bbox[2], max(prev.bbox[3], line.bbox[3])),
                        "size": max(prev.size, line.size),
                        "bold": prev.bold or line.bold,
                    }
                )
                continue
        out.append(line)
    return out


def _join_text(parts: list[str]) -> str:
    """Joint des lignes en réparant les coupures de mots en fin de ligne."""
    text = " ".join(p.strip() for p in parts if p.strip())
    text = HYPHEN_BREAK.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _collect_headings(lines: list[Line], profile: Profile) -> list[tuple[int, Line, list[Line]]]:
    """Repère les titres et rattache à chacun les lignes qui le suivent."""
    headings: list[tuple[int, Line]] = []
    bodies: list[list[Line]] = []
    current_chapter: str | None = None
    in_definitions = False
    pending: list[Line] = []

    for line in lines:
        level = profile.level_of(line)
        if level is None and in_definitions and profile.definition_term_rule:
            level = profile.definition_term_rule(line)
        if level is None:
            pending.append(line)
            continue
        # Un titre coupé sur deux lignes : même niveau, lignes qui se suivent, pas de texte entre.
        if profile.merge_consecutive_headings and headings and not pending:
            last_level, last_line = headings[-1]
            gap = line.bbox[1] - last_line.bbox[3]
            if last_level == level and last_line.page == line.page and -4 < gap < 1.2 * line.size and not NUMBER_RE.match(line.text):
                merged = last_line.model_copy(
                    update={
                        "text": f"{last_line.text} {line.text}",
                        "bbox": (last_line.bbox[0], last_line.bbox[1], max(last_line.bbox[2], line.bbox[2]), line.bbox[3]),
                    }
                )
                headings[-1] = (level, merged)
                continue
        if headings:
            bodies.append(pending)
        pending = []
        headings.append((level, line))
        if level <= 1:
            number, _ = number_of(line.text)
            current_chapter = number
            in_definitions = bool(profile.definitions_chapter) and current_chapter == profile.definitions_chapter
    if headings:
        bodies.append(pending)
    return [(level, head, body) for (level, head), body in zip(headings, bodies, strict=True)]


def _apply_scope(items: list[tuple[int, Line, list[Line]]], profile: Profile) -> list[tuple[int, Line, list[Line]]]:
    """Dans un contrat multi-branches, ne garde que les parties qui concernent l'habitation."""
    if not profile.scope_parts:
        return items
    patterns = [re.compile(p, re.I) for p in profile.scope_parts]
    kept: list[tuple[int, Line, list[Line]]] = []
    keep_part = True
    for level, head, body in items:
        if level == 0:
            _, title = number_of(head.text)
            keep_part = any(p.search(title) for p in patterns)
        if keep_part:
            kept.append((level, head, body))
    return kept


def build_clauses(lines: list[Line], profile: Profile) -> list[Clause]:
    """Reconstruit le plan et découpe le texte en clauses."""
    items = _apply_scope(_collect_headings(lines, profile), profile)
    clauses: list[Clause] = []
    stack: list[tuple[int, str, str]] = []  # (niveau, identifiant, titre)
    used: set[str] = set()
    for level, head, body in items:
        number, clean_title = number_of(head.text.strip())
        clean_title = clean_title.lstrip("•·-– ").strip()
        text = _join_text([line.text for line in body])
        if not clean_title:
            clean_title = (text[:60].rsplit(" ", 1)[0] + "…") if len(text) > 60 else (text or head.text.strip())
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        base = number.replace(".", "_") if number else slugify(clean_title)
        if not number and stack:
            base = f"{stack[-1][1]}__{base}"
        clause_id = base
        if clause_id in used and parent_id:
            # Deux parties du contrat reprennent la même numérotation : le parent lève l'ambiguïté.
            clause_id = f"{parent_id}__{base}"
        suffix = 2
        while clause_id in used:
            clause_id = f"{base}_{suffix}"
            suffix += 1
        used.add(clause_id)
        path = " > ".join([*(item[2] for item in stack), clean_title])
        last_page = body[-1].page if body else head.page
        clause = Clause(
            contract_id=profile.contract_id,
            clause_id=clause_id,
            number=number,
            title=clean_title,
            level=level,
            parent_id=parent_id,
            path=path,
            page_start=head.page,
            page_end=last_page,
            text=text,
            families=[],
        )
        clauses.append(clause)
        stack.append((level, clause_id, clean_title))
    for clause in clauses:
        clause.families = families_for_clause(clause.title, clause.path, clause.text)
    return clauses


def table_rows_from_docling(docling_json: Path, clauses: list[Clause], contract_id: str) -> list[TableRow]:
    """Chaque rangée d'un tableau Docling devient une unité, en-têtes compris."""
    data = json.loads(docling_json.read_text(encoding="utf-8"))
    rows: list[TableRow] = []
    for t_index, table in enumerate(data.get("tables", [])):
        if table.get("label") == "document_index":
            continue
        prov = table.get("prov") or []
        page = int(prov[0]["page_no"]) if prov else 0
        grid = table.get("data", {}).get("grid", [])
        if len(grid) < 2:
            continue
        headers = [_cell_text(c) for c in grid[0]]
        if sum(1 for h in headers if h) < max(1, len(headers) // 2):
            headers = [f"colonne {i + 1}" for i in range(len(headers))]
        clause_id = _clause_for_page(clauses, page)
        if clause_id is None:
            # Tableau d'une page hors périmètre (sommaire, autre branche du contrat) : ignoré.
            continue
        previous_first = ""
        for r_index, row in enumerate(grid[1:], start=1):
            values = [_cell_text(c) for c in row]
            if not any(values):
                continue
            # Une première cellule vide reprend celle de la rangée précédente (cellule fusionnée).
            if values and not values[0]:
                values[0] = previous_first
            previous_first = values[0] if values else ""
            pairs = [f"{h}: {v}" for h, v in zip(headers, values, strict=False) if v]
            serialized = " | ".join(pairs)
            rows.append(
                TableRow(
                    contract_id=contract_id,
                    row_id=f"t{t_index + 1}_r{r_index}",
                    clause_id=clause_id,
                    page=page,
                    headers=headers,
                    values=values,
                    serialized=serialized,
                    families=families_for_clause(serialized, "", serialized),
                )
            )
    return rows


def _cell_text(cell: dict) -> str:
    return clean_text(str(cell.get("text", "")))


def _clause_for_page(clauses: list[Clause], page: int) -> str | None:
    """La clause la plus profonde dont l'étendue couvre la page du tableau."""
    best: Clause | None = None
    for clause in clauses:
        if clause.page_start <= page <= clause.page_end and (best is None or clause.level >= best.level):
            best = clause
    return best.clause_id if best else None


def parse_contract(contract_id: str, pdf_path: Path, docling_json: Path | None) -> tuple[list[Clause], list[TableRow]]:
    """Parse complet d'un contrat : lignes, plan, clauses, rangées."""
    profile = profile_for(contract_id)
    lines = extract_lines(pdf_path, profile)
    clauses = build_clauses(lines, profile)
    rows = table_rows_from_docling(docling_json, clauses, contract_id) if docling_json and docling_json.exists() else []
    return clauses, rows
