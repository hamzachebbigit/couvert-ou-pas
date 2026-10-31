"""Index de recherche : BM25 en mémoire et embeddings dans SQLite.

Les unités indexées sont les clauses (découpées quand elles sont très longues)
et les rangées de tableau. Chaque unité garde son contrat, sa clause, ses
pages et ses familles, ce qui permet de filtrer avant de chercher.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from snowballstemmer import stemmer

from .models import Clause, TableRow
from .settings import settings

STEMMER = stemmer("french")
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = set(
    """le la les l un une des du de d et ou à a au aux en dans sur par pour avec sans sous ce cette ces cet se sa son ses leur leurs
    il elle ils elles on nous vous je tu qui que quoi dont où ne pas plus est sont été être ayant avoir fait faire mon ma mes
    notre nos votre vos y s n c qu si tout toute tous toutes même aussi ainsi lors cas""".split()
)
MAX_CHUNK = 3200
MIN_EMBED_CHARS = 80


@dataclass
class Unit:
    """Une unité de recherche : une clause, un morceau de clause ou une rangée."""

    contract_id: str
    unit_id: str
    kind: str
    clause_id: str
    title: str
    path: str
    page_start: int
    page_end: int
    text: str
    families: list[str] = field(default_factory=list)
    level: int = 0


def tokenize(text: str) -> list[str]:
    """Minuscules, accents retirés, mots vides ôtés, racines françaises."""
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    words = [w for w in TOKEN_RE.findall(folded) if w not in STOPWORDS and len(w) > 1]
    return STEMMER.stemWords(words)


def split_long(text: str, limit: int = MAX_CHUNK) -> list[str]:
    """Découpe une clause très longue à des frontières de phrases ou d'alinéas numérotés."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.;:])\s+(?=[A-ZÀ-Ý0-9«(]|\d+\.)", text):
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current.strip())
    return pieces


def units_from_parsed(contract_id: str, clauses: list[Clause], rows: list[TableRow]) -> list[Unit]:
    """Fabrique les unités d'un contrat à partir des fichiers parsés."""
    units: list[Unit] = []
    for clause in clauses:
        if not clause.text.strip():
            continue
        chunks = split_long(clause.text)
        for index, chunk in enumerate(chunks):
            unit_id = clause.clause_id if len(chunks) == 1 else f"{clause.clause_id}#{index + 1}"
            units.append(
                Unit(
                    contract_id=contract_id,
                    unit_id=unit_id,
                    kind="clause",
                    clause_id=clause.clause_id,
                    title=clause.title,
                    path=clause.path,
                    page_start=clause.page_start,
                    page_end=clause.page_end,
                    text=chunk,
                    families=list(clause.families),
                    level=clause.level,
                )
            )
    for row in rows:
        if len(row.serialized) < 12:
            continue
        units.append(
            Unit(
                contract_id=contract_id,
                unit_id=f"row:{row.row_id}",
                kind="table_row",
                clause_id=row.clause_id or "",
                title="Rangée de tableau",
                path=f"Tableau page {row.page}",
                page_start=row.page,
                page_end=row.page,
                text=row.serialized,
                families=list(row.families),
            )
        )
    return units


def load_parsed(contract_id: str, data_dir: Path | None = None) -> tuple[list[Clause], list[TableRow]]:
    base = (data_dir or settings.data_dir) / "parsed" / contract_id
    clauses = [Clause(**c) for c in json.loads((base / "clauses.json").read_text(encoding="utf-8"))]
    rows_path = base / "table_rows.json"
    rows = [TableRow(**r) for r in json.loads(rows_path.read_text(encoding="utf-8"))] if rows_path.exists() else []
    return clauses, rows


class Index:
    """L'index chargé en mémoire : unités, BM25 par contrat, vecteurs par contrat."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.data_dir / "index.db"
        self.units: dict[str, list[Unit]] = {}
        self.bm25: dict[str, BM25Okapi] = {}
        self.vectors: dict[str, np.ndarray] = {}
        self.embed_model: str = ""
        self._lookups: dict[str, dict[str, Clause]] = {}

    def build(self, contract_ids: list[str], embed: "callable | None" = None, embed_model: str = "", resume: bool = False) -> None:
        """Construit l'index et l'enregistre dans SQLite, un contrat à la fois.

        Chaque contrat est validé dès qu'il est indexé : un quota atteint au
        troisième contrat ne défait pas les deux premiers. Avec `resume`, les
        contrats déjà vectorisés avec le même modèle sont laissés tels quels.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists() and not resume:
            self.db_path.unlink()
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS units (contract_id TEXT, unit_id TEXT, kind TEXT, clause_id TEXT, title TEXT, path TEXT,
                page_start INTEGER, page_end INTEGER, text TEXT, families TEXT, level INTEGER, PRIMARY KEY (contract_id, unit_id));
            CREATE TABLE IF NOT EXISTS vectors (contract_id TEXT, unit_id TEXT, vector BLOB, PRIMARY KEY (contract_id, unit_id));
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            """
        )
        previous = conn.execute("SELECT value FROM meta WHERE key = 'embed_model'").fetchone()
        same_model = bool(previous) and previous[0] == embed_model
        for contract_id in contract_ids:
            done = conn.execute("SELECT COUNT(*) FROM vectors WHERE contract_id = ?", (contract_id,)).fetchone()[0]
            if resume and same_model and (done or embed is None):
                print(f"{contract_id} : déjà indexé")
                continue
            clauses, rows = load_parsed(contract_id)
            units = units_from_parsed(contract_id, clauses, rows)
            vectors: list[tuple[str, str, bytes]] = []
            if embed is not None:
                # Les unités réduites à un titre n'ont pas de vecteur : BM25 les retrouve par leurs mots,
                # et chaque vecteur compte dans le quota journalier du palier gratuit.
                worth = [u for u in units if len(u.text) >= MIN_EMBED_CHARS]
                try:
                    matrix = embed([f"{u.path}\n{u.text[:3000]}" for u in worth])
                    vectors = [(u.contract_id, u.unit_id, np.asarray(matrix[i], dtype=np.float32).tobytes()) for i, u in enumerate(worth)]
                except Exception as error:  # noqa: BLE001 : un quota atteint n'efface pas le texte indexé
                    print(f"{contract_id} : embeddings indisponibles ({str(error)[:80]}), unités écrites sans vecteur, relancer avec --resume")
            conn.execute("DELETE FROM units WHERE contract_id = ?", (contract_id,))
            conn.execute("DELETE FROM vectors WHERE contract_id = ?", (contract_id,))
            conn.executemany(
                "INSERT INTO units VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(u.contract_id, u.unit_id, u.kind, u.clause_id, u.title, u.path, u.page_start, u.page_end, u.text, json.dumps(u.families), u.level) for u in units],
            )
            conn.executemany("INSERT INTO vectors VALUES (?,?,?)", vectors)
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('embed_model', ?)", (embed_model,))
            conn.commit()
            print(f"{contract_id} : {len(units)} unités indexées")
        conn.close()

    def load(self) -> "Index":
        """Charge l'index depuis SQLite et prépare BM25 par contrat."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT contract_id, unit_id, kind, clause_id, title, path, page_start, page_end, text, families, level FROM units").fetchall()
        for row in rows:
            unit = Unit(
                contract_id=row[0], unit_id=row[1], kind=row[2], clause_id=row[3], title=row[4], path=row[5],
                page_start=row[6], page_end=row[7], text=row[8], families=json.loads(row[9]), level=row[10],
            )
            self.units.setdefault(unit.contract_id, []).append(unit)
        for contract_id, units in self.units.items():
            self.bm25[contract_id] = BM25Okapi([tokenize(f"{u.title} {u.text}") for u in units])
            vectors = conn.execute("SELECT unit_id, vector FROM vectors WHERE contract_id = ?", (contract_id,)).fetchall()
            if vectors:
                by_id = {unit_id: np.frombuffer(blob, dtype=np.float32) for unit_id, blob in vectors}
                dim = len(next(iter(by_id.values())))
                self.vectors[contract_id] = np.stack([by_id.get(u.unit_id, np.zeros(dim, dtype=np.float32)) for u in units])
        meta = conn.execute("SELECT value FROM meta WHERE key = 'embed_model'").fetchone()
        self.embed_model = meta[0] if meta else ""
        conn.close()
        return self

    def contracts(self) -> list[str]:
        return sorted(self.units)

    def candidates(self, contract_id: str, families: list[str]) -> list[int]:
        """Filtre d'abord : positions des unités dont une famille rencontre celles de la question."""
        units = self.units.get(contract_id, [])
        if not families:
            return list(range(len(units)))
        wanted = set(families)
        return [i for i, u in enumerate(units) if wanted & set(u.families)]

    def bm25_rank(self, contract_id: str, query: str, positions: list[int], k: int) -> list[tuple[int, float]]:
        scores = self.bm25[contract_id].get_scores(tokenize(query))
        ranked = sorted(((i, float(scores[i])) for i in positions), key=lambda item: item[1], reverse=True)
        return [(i, s) for i, s in ranked[:k] if s > 0]

    def embed_rank(self, contract_id: str, query_vector: np.ndarray, positions: list[int], k: int) -> list[tuple[int, float]]:
        matrix = self.vectors.get(contract_id)
        if matrix is None or not positions:
            return []
        sub = matrix[positions]
        sims = sub @ query_vector
        order = np.argsort(-sims)[:k]
        return [(positions[int(j)], float(sims[int(j)])) for j in order]

    def clause_lookup(self, contract_id: str) -> dict[str, Clause]:
        """Les clauses complètes d'un contrat par identifiant, lues une fois."""
        cached = self._lookups.get(contract_id)
        if cached is None:
            clauses, _ = load_parsed(contract_id)
            cached = {c.clause_id: c for c in clauses}
            self._lookups[contract_id] = cached
        return cached
