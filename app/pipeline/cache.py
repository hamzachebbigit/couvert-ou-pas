"""Cache des verdicts et compteurs d'usage, dans un fichier SQLite.

La clé d'un verdict est l'empreinte de (contrat, question normalisée, version
du prompt, modèle). Le plafond quotidien compte les appels hors cache, et un
compteur par adresse et par minute borne un visiteur pressé.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from .settings import settings

_LOCK = threading.Lock()


def normalise_question(question: str) -> str:
    """Minuscules, accents retirés, espaces réduits : deux formulations proches partagent un verdict."""
    text = unicodedata.normalize("NFKD", question.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.replace("’", "'").split())


def cache_key(contract_id: str, question: str, prompt_version: str, model: str) -> str:
    payload = "\u0001".join((contract_id, normalise_question(question), prompt_version, model))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Cache:
    """Accès SQLite sérialisé par un verrou, suffisant pour un processus."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.cache_db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS verdicts (
                key TEXT PRIMARY KEY,
                contract_id TEXT NOT NULL,
                question TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                model TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, count INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS ip_minutes (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL);
            """
        )

    def get(self, key: str) -> dict | None:
        with _LOCK:
            row = self.conn.execute("SELECT payload FROM verdicts WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, contract_id: str, question: str, prompt_version: str, model: str, payload: dict) -> None:
        with _LOCK:
            self.conn.execute(
                "INSERT OR REPLACE INTO verdicts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, contract_id, question, prompt_version, model, json.dumps(payload, ensure_ascii=False), datetime.now(UTC).isoformat()),
            )
            self.conn.commit()

    def count_today(self) -> int:
        day = datetime.now(UTC).date().isoformat()
        with _LOCK:
            row = self.conn.execute("SELECT count FROM usage WHERE day = ?", (day,)).fetchone()
        return row[0] if row else 0

    def reserve_daily(self, cap: int) -> bool:
        """Réserve un appel hors cache si le plafond du jour n'est pas atteint."""
        day = datetime.now(UTC).date().isoformat()
        with _LOCK:
            row = self.conn.execute("SELECT count FROM usage WHERE day = ?", (day,)).fetchone()
            current = row[0] if row else 0
            if current >= cap:
                return False
            self.conn.execute("INSERT OR REPLACE INTO usage VALUES (?, ?)", (day, current + 1))
            self.conn.commit()
        return True

    def reserve_ip_minute(self, ip: str, cap: int) -> bool:
        """Borne les analyses par adresse et par minute. L'adresse est hachée, jamais stockée en clair."""
        minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
        bucket = hashlib.sha256(f"{ip}|{minute}".encode()).hexdigest()[:24]
        with _LOCK:
            row = self.conn.execute("SELECT count FROM ip_minutes WHERE bucket = ?", (bucket,)).fetchone()
            current = row[0] if row else 0
            if current >= cap:
                return False
            self.conn.execute("INSERT OR REPLACE INTO ip_minutes VALUES (?, ?)", (bucket, current + 1))
            if current == 0:
                self.conn.execute("DELETE FROM ip_minutes WHERE bucket NOT IN (SELECT bucket FROM ip_minutes ORDER BY rowid DESC LIMIT 5000)")
            self.conn.commit()
        return True
