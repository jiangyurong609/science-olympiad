from __future__ import annotations
import json
from dataclasses import dataclass
import httpx
from app.core.config import get_settings


class ModelProviderError(RuntimeError):
    pass


@dataclass
class ModelResult:
    payload: dict
    provider: str
    model: str


class OpenAICompatibleProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = (settings.openai_compatible_base_url or "").rstrip("/")
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model
        self.embedding_model = settings.openai_embedding_model

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    @property
    def embeddings_configured(self) -> bool:
        return bool(self.configured and self.embedding_model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via an OpenAI-compatible /embeddings endpoint."""
        if not self.embeddings_configured:
            raise ModelProviderError("No embedding model is configured")
        url = f"{self.base_url}/embeddings"
        try:
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.embedding_model, "input": texts},
                timeout=httpx.Timeout(120.0, connect=15.0),
            )
            response.raise_for_status()
            data = response.json()["data"]
            return [row["embedding"] for row in data]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelProviderError(f"Embedding request failed: {exc}") from exc

    def generate_json(self, system: str, user: str) -> ModelResult:
        if not self.configured:
            raise ModelProviderError("No external model provider is configured")
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=httpx.Timeout(180.0, connect=15.0),
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return ModelResult(payload=json.loads(content), provider="openai-compatible", model=self.model)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelProviderError(f"Model request failed: {exc}") from exc
