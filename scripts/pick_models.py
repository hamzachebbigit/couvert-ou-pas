"""Liste les modèles accessibles avec la clé et propose les identifiants à épingler.

    python scripts/pick_models.py

Rien n'est deviné : les identifiants viennent de la réponse de l'API. Le script
propose le modèle standard le plus récent pour le verdict, sa version mini
pour la lecture de la question, le reclassement et l'extraction, et le petit
modèle d'embeddings, puis vérifie chacun par un appel minuscule.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline.providers import router  # noqa: E402

# Un identifiant standard est « gpt-<version> » ou « gpt-<version>-mini », sans date ni nom de variante.
STANDARD = re.compile(r"^gpt-(\d+(?:\.\d+)?)(-mini)?$")


def main() -> int:
    if not router.provider:
        print("OPENAI_API_KEY absent du .env")
        return 1
    ids = router.provider.list_models()
    print("Modèles de génération standard :")
    standard = {}
    for name in ids:
        match = STANDARD.match(name)
        if match:
            standard[name] = (float(match.group(1)), bool(match.group(2)))
            print(f"  {name}")
    embeds = [n for n in ids if "embedding" in n]
    print("Modèles d'embeddings :")
    for name in embeds:
        print(f"  {name}")

    # Une seule famille : la version la plus récente qui existe à la fois en modèle courant et en mini,
    # pour que les deux tâches partagent le même comportement. Chaque candidat est ensuite sondé.
    versions = {v for v, mini in standard.values() if mini} & {v for v, mini in standard.values() if not mini}
    full = sorted((n for n, (v, mini) in standard.items() if not mini and v in versions), key=lambda n: standard[n][0], reverse=True)
    minis = sorted((n for n, (v, mini) in standard.items() if mini and v in versions), key=lambda n: standard[n][0], reverse=True)
    print("\nSondage des candidats (un appel chacun) :")
    verdict = _first_answering(full) or _first_answering(minis)
    cheap = _first_answering(minis) or verdict
    embed = next((n for n in embeds if n.endswith("3-small")), embeds[0] if embeds else "")
    print("\nProposition à recopier dans .env :")
    print(f"OPENAI_MODEL_VERDICT={verdict}")
    print(f"OPENAI_MODEL_CHEAP={cheap}")
    print(f"OPENAI_MODEL_EMBED={embed}")
    return 0


def _first_answering(candidates: list[str]) -> str | None:
    """Le premier identifiant de la liste qui répond réellement à un appel JSON avec effort de raisonnement."""
    for name in candidates:
        try:
            router.provider.generate_json(name, "Réponds en JSON.", '{"ok": true}', reasoning="low")
            print(f"  {name:<24} répond")
            return name
        except Exception as error:  # noqa: BLE001 : un modèle muet passe simplement son tour
            print(f"  {name:<24} muet ({str(error)[:60]})")
    return None


if __name__ == "__main__":
    raise SystemExit(main())
