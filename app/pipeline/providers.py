"""Fournisseurs de modèles derrière une seule interface, avec repli.

Le fournisseur principal est Gemini. Une clé épuisée passe à la clé suivante,
un modèle en erreur passe au palier inférieur, et un fournisseur exposant une
API de complétion de chat prend le relais si une clé est configurée. L'appelant ne
voit qu'une fonction : `generate_json(task, system, user)`.
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

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
Task = Literal["verdict", "cheap"]
EMBED_BATCH = 40
EMBED_BATCH_SPACING_S = 30
# Niveau de réflexion demandé au modèle par tâche : le verdict mérite une réflexion moyenne,
# la lecture de la question et le reclassement n'en ont pas besoin.
THINKING_BY_TASK: dict[str, str] = {"verdict": "medium", "cheap": "low"}


class ProviderError(RuntimeError):
    """Aucun fournisseur n'a pu répondre."""


@dataclass
class Pacer:
    """Espace les appels d'une clé pour rester sous la limite par minute."""

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
    """Le délai demandé par une réponse 429 (RetryInfo ou phrase « retry in »), borné à 75 s."""
    try:
        data = response.json()
    except ValueError:
        return default
    for detail in data.get("error", {}).get("details", []):
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            match = re.match(r"([\d.]+)s", str(detail.get("retryDelay", "")))
            if match:
                return min(75.0, float(match.group(1)) + 1.0)
    match = re.search(r"retry in ([\d.]+)s", data.get("error", {}).get("message", ""))
    return min(75.0, float(match.group(1)) + 1.0) if match else default


def _quota_hint(response: httpx.Response) -> str:
    """Le nom du quota touché, pour le journal, sans le reste du message."""
    try:
        message = response.json().get("error", {}).get("message", "")
    except ValueError:
        return ""
    match = re.search(r"metric: ([\w./]+)", message)
    return match.group(1).rsplit("/", 1)[-1] if match else message[:80]


def _daily_quota(response: httpx.Response) -> bool:
    """Vrai quand le 429 porte sur un quota journalier : attendre ne sert à rien."""
    return "PerDay" in response.text


def _strip_json(text: str) -> str:
    """Retire une éventuelle clôture de bloc de code autour du JSON."""
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return match.group(1) if match else text


class GeminiProvider:
    """Appels REST à Gemini : génération JSON et embeddings."""

    def __init__(self, keys: tuple[str, ...], rpm: int) -> None:
        self.keys = keys
        self.rpm = rpm
        self.pacers: dict[tuple[int, str], Pacer] = {}
        self.client = httpx.Client(timeout=120)

    def _pacer(self, key_index: int, path: str) -> Pacer:
        """Un rythme par clé ET par modèle : les quotas par minute sont comptés par modèle."""
        model = path.split(":", 1)[0]
        return self.pacers.setdefault((key_index, model), Pacer(self.rpm))

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Tente chaque clé à tour de rôle, avec une attente sur 429.

        Le palier gratuit compte chaque texte d'un lot d'embeddings comme une
        requête (100 par minute) : la réponse 429 porte le délai à respecter,
        il est lu et attendu plutôt que deviné.
        """
        last: Exception | None = None
        for index, key in enumerate(self.keys):
            for attempt in range(4):
                self._pacer(index, path).wait()
                try:
                    response = self.client.post(f"{GEMINI_BASE}/{path}", params={"key": key}, json=body)
                except httpx.HTTPError as error:
                    last = error
                    time.sleep(2 * (attempt + 1))
                    continue
                if response.status_code == 429:
                    last = ProviderError(f"429 sur la clé {index + 1} : {_quota_hint(response)}")
                    if _daily_quota(response):
                        break  # quota du jour épuisé sur cette clé : passer à la suivante
                    time.sleep(_retry_delay(response, default=min(20, 5 * (attempt + 1))))
                    continue
                if response.status_code >= 500:
                    last = ProviderError(f"{response.status_code} {response.text[:200]}")
                    time.sleep((5, 12, 25, 40)[attempt])  # une pointe de charge dure souvent une minute
                    continue
                if response.status_code == 400 and "thinking" in response.text.lower() and body.get("generationConfig", {}).pop("thinkingConfig", None):
                    continue  # ce modèle ne prend pas de niveau de réflexion : même appel sans
                if response.status_code >= 400:
                    raise ProviderError(f"{response.status_code} {response.text[:300]}")
                return response.json()
        raise ProviderError(str(last))

    def generate_json(self, model: str, system: str, user: str, temperature: float = 0.0, thinking: str = "") -> dict[str, Any]:
        """Un appel en mode JSON.

        Le budget de sortie compte les jetons de réflexion : avec 4 096 jetons, la
        réflexion par défaut du modèle de verdict mangeait tout et le JSON arrivait
        tronqué. Le budget est large et le niveau de réflexion est choisi par tâche.
        """
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "maxOutputTokens": 16384,
            },
        }
        if thinking:
            body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking}
        data = self._post(f"models/{model}:generateContent", body)
        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderError(f"réponse vide : {json.dumps(data)[:300]}")
        if candidates[0].get("finishReason") == "MAX_TOKENS":
            raise ProviderError("réponse tronquée (MAX_TOKENS)")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return json.loads(_strip_json(text))

    def embed(self, model: str, texts: list[str], task_type: str, dim: int = 768) -> np.ndarray:
        """Embeddings par lots, normalisés pour une similarité cosinus.

        Le palier gratuit compte chaque texte du lot (100 par minute, les lots
        refusés compris) : des lots de 40 espacés de 30 s restent sous la limite.
        """
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            if start:
                time.sleep(EMBED_BATCH_SPACING_S)
            chunk = texts[start : start + EMBED_BATCH]
            body = {
                "requests": [
                    {
                        "model": f"models/{model}",
                        "content": {"parts": [{"text": text}]},
                        "taskType": task_type,
                        "outputDimensionality": dim,
                    }
                    for text in chunk
                ]
            }
            data = self._post(f"models/{model}:batchEmbedContents", body)
            vectors.extend(item["values"] for item in data["embeddings"])
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.maximum(norms, 1e-9)

    def list_models(self) -> list[dict[str, Any]]:
        self.pacers[0].wait()
        response = self.client.get(f"{GEMINI_BASE}/models", params={"key": self.keys[0], "pageSize": 200})
        response.raise_for_status()
        return response.json().get("models", [])


class ChatCompletionsProvider:
    """Génération JSON via un service exposant le point d'entrée chat/completions."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.client = httpx.Client(timeout=90)

    def generate_json(self, system: str, user: str, temperature: float = 0.0) -> dict[str, Any]:
        body = {
            "model": self.model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
        )
        if response.status_code >= 400:
            raise ProviderError(f"{response.status_code} {response.text[:300]}")
        text = response.json()["choices"][0]["message"]["content"]
        return json.loads(_strip_json(text))


class Router:
    """Choisit le modèle par tâche et applique l'ordre de repli."""

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.gemini = GeminiProvider(config.gemini_keys, config.gemini_rpm) if config.gemini_keys else None
        self.secondary = (
            ChatCompletionsProvider(config.secondary_base_url, config.secondary_api_key, config.secondary_model)
            if config.secondary_api_key and config.secondary_base_url and config.secondary_model
            else None
        )

    def _ladder(self, task: Task) -> list[str]:
        """Les modèles Gemini à essayer, du plus adapté au plus modeste."""
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
        errors: list[str] = []
        if self.gemini:
            for model in self._ladder(task):
                try:
                    return self.gemini.generate_json(model, system, user, temperature, THINKING_BY_TASK[task]), f"gemini:{model}"
                except (ProviderError, json.JSONDecodeError, KeyError) as error:
                    errors.append(f"{model}: {error}")
        if self.secondary:
            try:
                return self.secondary.generate_json(system, user, temperature), f"secondary:{self.secondary.model}"
            except (ProviderError, json.JSONDecodeError, KeyError) as error:
                errors.append(f"secondary: {error}")
        raise ProviderError(" | ".join(errors) or "aucun fournisseur configuré")

    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        if not self.gemini or not self.config.model_embed:
            raise ProviderError("aucun modèle d'embeddings configuré")
        return self.gemini.embed(self.config.model_embed, texts, task_type)

    @property
    def embed_model(self) -> str:
        return self.config.model_embed


router = Router(settings)
