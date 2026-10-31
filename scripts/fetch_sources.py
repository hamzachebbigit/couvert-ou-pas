"""Télécharge les conditions générales listées dans data/sources.json.

Les PDF ne sont pas versionnés : ce script les reconstitue depuis les sites
des assureurs et vérifie leur empreinte SHA-256 quand elle est connue.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "data" / "sources.json"
DEST = ROOT / "data" / "sources"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
    "Accept-Language": "fr-LU,fr;q=0.9",
}


def sha256_of(path: Path) -> str:
    """Empreinte SHA-256 hexadécimale d'un fichier."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, client: httpx.Client) -> bytes:
    """Récupère un PDF en essayant d'abord sans en-tête de navigateur, puis avec.

    Les serveurs des assureurs ne sont pas d'accord entre eux : l'un refuse
    un client nu, l'autre répond 406 à un User-Agent de navigateur.
    """
    last_error: Exception | None = None
    for headers in ({}, HEADERS):
        try:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            if response.content.startswith(b"%PDF"):
                return response.content
            last_error = RuntimeError("la réponse n'est pas un PDF")
        except httpx.HTTPError as error:
            last_error = error
    raise RuntimeError(str(last_error))


def fetch(contract: dict, client: httpx.Client) -> Path:
    """Télécharge un contrat si le fichier local est absent, puis vérifie l'empreinte."""
    target = DEST / f"{contract['id']}.pdf"
    if not target.exists():
        print(f"Téléchargement de {contract['id']} depuis {contract['url']}")
        target.write_bytes(download(contract["url"], client))
    actual = sha256_of(target)
    expected = contract.get("sha256")
    if expected and actual != expected:
        raise RuntimeError(f"{contract['id']} : empreinte {actual}, attendue {expected}")
    print(f"{contract['id']} : {target.stat().st_size} octets, sha256 {actual[:12]}…")
    return target


def main(argv: list[str]) -> int:
    """Point d'entrée : tout télécharger, ou seulement les identifiants passés en argument."""
    DEST.mkdir(parents=True, exist_ok=True)
    contracts = json.loads(SOURCES.read_text(encoding="utf-8"))["contracts"]
    wanted = set(argv) or {c["id"] for c in contracts}
    failures = 0
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for contract in contracts:
            if contract["id"] not in wanted:
                continue
            try:
                fetch(contract, client)
            except Exception as error:  # noqa: BLE001
                failures += 1
                print(f"ÉCHEC {contract['id']} : {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
