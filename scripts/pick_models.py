"""Liste les modèles accessibles avec la clé Gemini et propose les identifiants à épingler.

    python scripts/pick_models.py

Rien n'est deviné : les identifiants viennent de la réponse de l'API. Le script
propose le modèle le plus capable pour le verdict, le plus économique pour la
lecture de la question et le reclassement, et le modèle d'embeddings.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline.providers import router  # noqa: E402


def main() -> int:
    if not router.gemini:
        print("GEMINI_API_KEY absent du .env")
        return 1
    models = router.gemini.list_models()
    generators = [m for m in models if "generateContent" in m.get("supportedGenerationMethods", [])]
    embedders = [m for m in models if "embedContent" in m.get("supportedGenerationMethods", [])]
    print("Modèles de génération :")
    for m in generators:
        print(f"  {m['name'].removeprefix('models/'):<40} {m.get('displayName', '')}")
    print("Modèles d'embeddings :")
    for m in embedders:
        print(f"  {m['name'].removeprefix('models/'):<40} {m.get('displayName', '')}")

    names = [m["name"].removeprefix("models/") for m in generators]
    excluded = ("exp", "preview", "latest", "tts", "image", "audio", "live", "thinking", "learnlm", "gemma",
                "lyria", "banana", "omni", "transcribe", "robotics", "research", "computer", "argon")
    stable = [n for n in names if not any(tag in n for tag in excluded)]
    flash = sorted((n for n in stable if "flash" in n and "lite" not in n), reverse=True)
    lite = sorted((n for n in stable if "lite" in n), reverse=True)
    embed_names = [m["name"].removeprefix("models/") for m in embedders]
    embed = (sorted([n for n in embed_names if "gemini-embedding" in n and "preview" not in n], reverse=True) or sorted(embed_names, reverse=True))[0]

    # Les modèles de la classe Pro n'ont pas de quota gratuit et les identifiants les plus récents
    # répondent parfois 503 sur la clé gratuite : chaque candidat est sondé par un appel minuscule.
    print("\nSondage des candidats (un appel chacun) :")
    verdict = _first_answering(flash) or _first_answering(lite)
    cheap = _first_answering(lite) or verdict
    print("\nProposition à recopier dans .env :")
    print(f"GEMINI_MODEL_VERDICT={verdict}")
    print(f"GEMINI_MODEL_CHEAP={cheap}")
    print(f"GEMINI_MODEL_EMBED={embed}")
    return 0


def _first_answering(candidates: list[str]) -> str | None:
    """Le premier identifiant de la liste qui répond réellement à un appel JSON."""
    for name in candidates:
        try:
            router.gemini.generate_json(name, "Réponds en JSON.", '{"ok": true}')
            print(f"  {name:<36} répond")
            return name
        except Exception as error:  # noqa: BLE001 : un modèle muet passe simplement son tour
            print(f"  {name:<36} muet ({str(error)[:60]})")
    return None


if __name__ == "__main__":
    raise SystemExit(main())
