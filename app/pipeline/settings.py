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
    """Paramètres du service. Les clés restent dans l'environnement, jamais dans le code."""

    gemini_keys: tuple[str, ...]
    model_verdict: str
    model_cheap: str
    model_embed: str
    gemini_rpm: int
    secondary_base_url: str
    secondary_api_key: str
    secondary_model: str
    daily_cap: int
    per_ip_per_minute: int
    cf_access_team_domain: str
    cf_access_aud: str
    data_dir: Path = field(default=ROOT / "data")
    prompts_dir: Path = field(default=ROOT / "prompts")

    @property
    def has_llm(self) -> bool:
        return bool(self.gemini_keys) or bool(self.secondary_api_key)


def load_settings() -> Settings:
    """Construit les paramètres depuis l'environnement."""
    keys = tuple(k for k in (os.environ.get("GEMINI_API_KEY", ""), os.environ.get("GEMINI_API_KEY_2", "")) if k.strip())
    return Settings(
        gemini_keys=keys,
        model_verdict=os.environ.get("GEMINI_MODEL_VERDICT", "").strip(),
        model_cheap=os.environ.get("GEMINI_MODEL_CHEAP", "").strip(),
        model_embed=os.environ.get("GEMINI_MODEL_EMBED", "").strip(),
        gemini_rpm=_int("GEMINI_RPM", 8),
        secondary_base_url=os.environ.get("SECONDARY_BASE_URL", "").strip().rstrip("/"),
        secondary_api_key=os.environ.get("SECONDARY_API_KEY", "").strip(),
        secondary_model=os.environ.get("SECONDARY_MODEL", "").strip(),
        daily_cap=_int("DAILY_CAP", 60),
        per_ip_per_minute=_int("PER_IP_PER_MINUTE", 6),
        cf_access_team_domain=os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip(),
        cf_access_aud=os.environ.get("CF_ACCESS_AUD", "").strip(),
    )


settings = load_settings()
