"""Configuration lue depuis l'environnement, validée au démarrage."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    """Paramètres du service. La clé reste dans l'environnement, jamais dans le code."""

    openai_api_key: str
    model_verdict: str
    model_cheap: str
    model_embed: str
    openai_rpm: int
    daily_cap: int
    per_ip_per_minute: int
    cf_access_team_domain: str
    cf_access_aud: str
    data_dir: Path = field(default=ROOT / "data")
    prompts_dir: Path = field(default=ROOT / "prompts")
    cache_db_path: Path = field(default=ROOT / "data" / "cache.db")

    @property
    def has_llm(self) -> bool:
        return bool(self.openai_api_key)


def load_settings() -> Settings:
    """Construit les paramètres depuis l'environnement."""
    return Settings(
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        model_verdict=os.environ.get("OPENAI_MODEL_VERDICT", "").strip(),
        model_cheap=os.environ.get("OPENAI_MODEL_CHEAP", "").strip(),
        model_embed=os.environ.get("OPENAI_MODEL_EMBED", "").strip(),
        openai_rpm=_int("OPENAI_RPM", 60),
        daily_cap=_int("DAILY_CAP", 60),
        per_ip_per_minute=_int("PER_IP_PER_MINUTE", 6),
        cf_access_team_domain=os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip(),
        cf_access_aud=os.environ.get("CF_ACCESS_AUD", "").strip(),
        # Le cache vit hors de l'image quand le conteneur est en lecture seule.
        cache_db_path=Path(os.environ.get("CACHE_DB_PATH", "").strip() or (ROOT / "data" / "cache.db")),
    )


settings = load_settings()
