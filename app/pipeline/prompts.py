"""Chargement des prompts versionnés depuis prompts/*.md."""

from __future__ import annotations

import re
from functools import lru_cache

from .settings import settings

VERSION_RE = re.compile(r"^version:\s*(\S+)\s*\n", re.I)


@lru_cache(maxsize=16)
def load_prompt(name: str) -> tuple[str, str]:
    """Renvoie (version, texte) du prompt demandé."""
    raw = (settings.prompts_dir / f"{name}.md").read_text(encoding="utf-8")
    match = VERSION_RE.match(raw)
    version = match.group(1) if match else "0"
    text = raw[match.end():].strip() if match else raw.strip()
    return version, text


def prompt_version() -> str:
    """Version combinée des prompts qui entrent dans la clé de cache."""
    return "+".join(f"{name}{load_prompt(name)[0]}" for name in ("parse_question", "rerank", "verdict"))
