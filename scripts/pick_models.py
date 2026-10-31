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
    stable = [n for n in names if not any(tag in n for tag in ("exp", "preview", "tts", "image", "audio", "live", "thinking", "learnlm", "gemma"))]
    pro = [n for n in stable if "pro" in n]
    flash = [n for n in stable if "flash" in n and "lite" not in n]
    lite = [n for n in stable if "lite" in n]
    verdict = (sorted(pro, reverse=True) or sorted(flash, reverse=True) or names)[0]
    cheap = (sorted(lite, reverse=True) or sorted(flash, reverse=True) or names)[0]
    embed_names = [m["name"].removeprefix("models/") for m in embedders]
    embed = (sorted([n for n in embed_names if "gemini-embedding" in n], reverse=True) or sorted(embed_names, reverse=True))[0]
    print("\nProposition à recopier dans .env (à vérifier contre les quotas gratuits de la clé) :")
    print(f"GEMINI_MODEL_VERDICT={verdict}")
    print(f"GEMINI_MODEL_CHEAP={cheap}")
    print(f"GEMINI_MODEL_EMBED={embed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
