"""Appels au fournisseur de modèles derrière une seule interface, avec repli.

Un modèle en erreur passe au palier inférieur, une limite de débit est
attendue sur le délai que la réponse annonce, et l'appelant ne voit qu'une
fonction : `generate_json(task, system, user)`.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import numpy as np

from .settings import Settings, settings

OPENAI_BASE = "https://api.openai.com/v1"
Task = Literal["verdict", "cheap"]
EMBED_BATCH = 100
EMBED_DIM = 768
MAX_OUTPUT_TOKENS = 16384
# Effort de raisonnement demandé au modèle par tâche. Mesuré sur dix questions du jeu annoté qui
# changeaient de verdict d'une passe à l'autre : le modèle courant le plus récent à effort bas en
# juge sept sur dix en 9 à 24 s, le précédent n'y arrive qu'à effort moyen en 37 à 62 s, et l'effort
# moyen sur le plus récent fait moins bien que l'effort bas. L'effort bas partout.
REASONING_BY_TASK: dict[str, str] = {"verdict": "low", "cheap": "low"}


class ProviderError(RuntimeError):
    """Le fournisseur n'a pas pu répondre."""


@dataclass
class Pacer:
    """Espace les appels d'un modèle pour rester sous la limite par minute."""

    rpm: int
    _last: float = 0.0
    _lock: threading.Lock = threading.Lock()

    def wait(self) -> None:
        interval = 60.0 / max(self.rpm, 1)
        with self._lock:
            now = time.monotonic()
            delay = self._last + interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def _retry_delay(response: httpx.Response, default: float) -> float:
    """Le délai demandé par une réponse 429 (en-tête Retry-After, en secondes ou en millisecondes), borné à 75 s."""
    header = response.headers.get("retry-after-ms") or response.headers.get("retry-after")
    if header:
        try:
            value = float(header)
            return min(75.0, value / 1000 if "retry-after-ms" in response.headers else value) + 0.5
        except ValueError:
            pass
    match = re.search(r"try again in ([\d.]+)(ms|s)", response.text)
    if match:
        value = float(match.group(1)) / (1000 if match.group(2) == "ms" else 1)
        return min(75.0, value) + 0.5
    return default


def _error_message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", {}).get("message", ""))
    except ValueError:
        return response.text[:200]


def _strip_json(text: str) -> str:
    """Retire une éventuelle clôture de bloc de code autour du JSON."""
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return match.group(1) if match else text


class OpenAIProvider:
    """Appels REST : complétion de chat en mode JSON et embeddings."""

    def __init__(self, api_key: str, rpm: int) -> None:
        self.api_key = api_key
        self.rpm = rpm
        self.pacers: dict[str, Pacer] = {}
        self.client = httpx.Client(base_url=OPENAI_BASE, headers={"Authorization": f"Bearer {api_key}"}, timeout=180)

    def _pacer(self, model: str) -> Pacer:
        """Un rythme par modèle : les limites par minute sont comptées par modèle."""
        return self.pacers.setdefault(model, Pacer(self.rpm))

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Un appel avec reprise : attente annoncée sur 429, pause croissante sur 5xx.

        Un paramètre que le modèle ne prend pas (effort de raisonnement sur un
        modèle sans raisonnement, température sur un modèle qui l'impose) est
        retiré et l'appel repart tel quel.
        """
        last: Exception | None = None
        for attempt in range(5):
            self._pacer(str(body.get("model", ""))).wait()
            try:
                response = self.client.post(path, json=body)
            except httpx.HTTPError as error:
                last = error
                time.sleep(2 * (attempt + 1))
                continue
            if response.status_code == 429:
                last = ProviderError(f"429 : {_error_message(response)[:120]}")
                time.sleep(_retry_delay(response, default=min(30, 5 * (attempt + 1))))
                continue
            if response.status_code >= 500:
                last = ProviderError(f"{response.status_code} {response.text[:200]}")
                time.sleep((3, 8, 15, 25, 40)[attempt])
                continue
            if response.status_code == 400:
                message = _error_message(response)
                if "reasoning_effort" in message and body.pop("reasoning_effort", None) is not None:
                    body.setdefault("temperature", 0.0)
                    continue
                if "temperature" in message and body.pop("temperature", None) is not None:
                    continue
            if response.status_code >= 400:
                raise ProviderError(f"{response.status_code} {_error_message(response)[:300]}")
            return response.json()
        raise ProviderError(str(last))

    def generate_json(self, model: str, system: str, user: str, temperature: float = 0.0, reasoning: str = "") -> dict[str, Any]:
        """Un appel en mode JSON.

        Le budget de sortie compte les jetons de raisonnement : il est large, et
        une réponse coupée par ce budget est une erreur, jamais un JSON partiel
        rafistolé. Un modèle qui raisonne n'accepte pas de température, elle
        n'est envoyée qu'en l'absence d'effort de raisonnement.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": MAX_OUTPUT_TOKENS,
        }
        if reasoning:
            body["reasoning_effort"] = reasoning
        else:
            body["temperature"] = temperature
        data = self._post("/chat/completions", body)
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(f"réponse vide : {json.dumps(data)[:300]}")
        if choices[0].get("finish_reason") == "length":
            raise ProviderError("réponse tronquée (budget de sortie atteint)")
        text = choices[0].get("message", {}).get("content") or ""
        return json.loads(_strip_json(text))

    def embed(self, model: str, texts: list[str], dim: int = EMBED_DIM) -> np.ndarray:
        """Embeddings par lots, normalisés pour une similarité cosinus."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            chunk = texts[start : start + EMBED_BATCH]
            data = self._post("/embeddings", {"model": model, "input": chunk, "dimensions": dim})
            items = sorted(data["data"], key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in items)
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.maximum(norms, 1e-9)

    def list_models(self) -> list[str]:
        response = self.client.get("/models")
        response.raise_for_status()
        return sorted(m["id"] for m in response.json().get("data", []))


class Router:
    """Choisit le modèle par tâche et applique l'ordre de repli."""

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.provider = OpenAIProvider(config.openai_api_key, config.openai_rpm) if config.openai_api_key else None

    def _ladder(self, task: Task) -> list[str]:
        """Les modèles à essayer, du plus adapté au plus modeste."""
        if task == "verdict":
            ladder = [self.config.model_verdict, self.config.model_cheap]
        else:
            ladder = [self.config.model_cheap, self.config.model_verdict]
        seen: list[str] = []
        for model in ladder:
            if model and model not in seen:
                seen.append(model)
        return seen

    def generate_json(self, task: Task, system: str, user: str, temperature: float = 0.0) -> tuple[dict[str, Any], str]:
        """Renvoie le JSON et le nom du modèle qui a répondu."""
        if not self.provider:
            raise ProviderError("aucun fournisseur configuré")
        errors: list[str] = []
        for model in self._ladder(task):
            try:
                return self.provider.generate_json(model, system, user, temperature, REASONING_BY_TASK[task]), model
            except (ProviderError, json.JSONDecodeError, KeyError) as error:
                errors.append(f"{model}: {error}")
        raise ProviderError(" | ".join(errors) or "aucun modèle configuré")

    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        """Vecteurs des textes. `task_type` distingue documents et requêtes pour les fournisseurs qui le lisent."""
        if not self.provider or not self.config.model_embed:
            raise ProviderError("aucun modèle d'embeddings configuré")
        return self.provider.embed(self.config.model_embed, texts)

    @property
    def embed_model(self) -> str:
        return self.config.model_embed


router = Router(settings)
