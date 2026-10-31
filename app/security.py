"""Vérification du jeton Cloudflare Access sur chaque requête.

Le service est publié derrière Cloudflare Access : seules les adresses
autorisées passent la porte. Le tunnel refuse déjà les requêtes sans jeton
valide. Cette couche le revérifie dans l'application, pour que l'accès reste
fermé même si une couche amont est mal configurée. Sans équipe Access
configurée (usage local), la vérification est désactivée.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from fastapi import Request
from fastapi.responses import JSONResponse

from app.pipeline.settings import settings

OPEN_PATHS = ("/healthz",)


class AccessVerifier:
    """Valide un JWT Access (RS256) contre les clés publiques de l'équipe."""

    def __init__(self, team_domain: str, audience: str) -> None:
        self.team_domain = team_domain
        self.audience = audience
        self.certs_url = f"https://{team_domain}/cdn-cgi/access/certs"
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.team_domain and self.audience)

    def _refresh_keys(self, force: bool = False) -> None:
        if not force and self._keys and time.time() - self._fetched_at < 3600:
            return
        response = httpx.get(self.certs_url, timeout=10)
        response.raise_for_status()
        keys = response.json().get("keys", [])
        self._keys = {k["kid"]: jwt.algorithms.RSAAlgorithm.from_jwk(k) for k in keys if k.get("kid")}
        self._fetched_at = time.time()

    def verify(self, token: str) -> dict[str, Any]:
        """Renvoie les claims du jeton, ou lève une exception."""
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        self._refresh_keys()
        if kid not in self._keys:
            self._refresh_keys(force=True)
        key = self._keys.get(kid)
        if key is None:
            raise jwt.InvalidTokenError("clé inconnue")
        return jwt.decode(token, key=key, algorithms=["RS256"], audience=self.audience, issuer=f"https://{self.team_domain}")


verifier = AccessVerifier(settings.cf_access_team_domain, settings.cf_access_aud)


async def access_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Refuse toute requête sans jeton Access valide, quand la vérification est active."""
    if not verifier.enabled or request.url.path in OPEN_PATHS:
        return await call_next(request)
    token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization", "")
    if not token:
        return JSONResponse({"error": "Accès réservé."}, status_code=401)
    try:
        claims = verifier.verify(token)
    except (jwt.PyJWTError, httpx.HTTPError, ValueError) as error:
        return JSONResponse({"error": f"Jeton d'accès refusé ({type(error).__name__})."}, status_code=401)
    request.state.access_email = claims.get("email", "")
    return await call_next(request)
