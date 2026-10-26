"""Embedding providers.

Embeddings are the highest-volume model call in the system: every
memory, every document chunk and every search goes through one. On a
paid API that becomes the largest line on the bill, so the default is
a local model that costs nothing and has no rate limit.

API providers are offered for people who prefer them, using the
same bring-your-own-key pattern as the LLM providers.
"""

from __future__ import annotations

import hashlib
import math
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.core.observability import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingModel:
    provider_key: str
    model: str
    dim: int
    needs_api_key: bool


# Only dimensions with a vector table exist here; see models/memory.py.
AVAILABLE_MODELS: dict[str, EmbeddingModel] = {
    "local": EmbeddingModel("local", "bge-small-en-v1.5", 384, needs_api_key=False),
    "gemini": EmbeddingModel("gemini", "text-embedding-004", 768, needs_api_key=True),
    "openai": EmbeddingModel("openai", "text-embedding-3-small", 1536, needs_api_key=True),
    "jina": EmbeddingModel("jina", "jina-embeddings-v3", 1024, needs_api_key=True),
}

DEFAULT_PROVIDER = "local"


class EmbeddingError(Exception):
    pass


class EmbeddingProvider(ABC):
    model: str
    dim: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


class LocalEmbeddingProvider(EmbeddingProvider):
    """Runs on this machine. Free, unlimited, and nothing leaves the server.

    Uses fastembed when it is installed, which is ONNX-based and far
    lighter than a torch install. When it is not available it falls back
    to a deterministic hashing embedder: that is **not** semantic and is
    only good enough for tests and local development, so it says so
    loudly rather than quietly degrading search quality in production.
    """

    def __init__(self, model: str = "bge-small-en-v1.5", dim: int = 384) -> None:
        self.model = model
        self.dim = dim
        self._backend = None
        self._semantic = False

        try:
            from fastembed import TextEmbedding

            self._backend = TextEmbedding(model_name=f"BAAI/{model}")
            self._semantic = True
        except Exception:  # noqa: BLE001 - optional dependency, absence is expected
            log.warning(
                "fastembed_unavailable",
                detail=(
                    "Falling back to hashed embeddings. These are deterministic but not "
                    "semantic: search will match wording, not meaning. Install fastembed "
                    "for real local embeddings."
                ),
            )

    @property
    def is_semantic(self) -> bool:
        return self._semantic

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._backend is not None:
            return [list(map(float, v)) for v in self._backend.embed(texts)]
        return [self._hashed(t) for t in texts]

    def _hashed(self, text: str) -> list[float]:
        """A stable pseudo-embedding, for tests and offline development.

        Deterministic for the same input, normalised to unit length so
        cosine distance behaves, and genuinely useless for meaning.
        """
        vector = [0.0] * self.dim
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode()).digest()
            for i in range(0, min(len(digest), 32), 4):
                index = struct.unpack("<I", digest[i : i + 4])[0] % self.dim
                vector[index] += 1.0

        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class APIEmbeddingProvider(EmbeddingProvider):
    """Gemini, OpenAI or Jina, using the person's own key."""

    def __init__(self, provider_key: str, api_key: str, model: str, dim: int) -> None:
        self.provider_key = provider_key
        self.api_key = api_key
        self.model = model
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.provider_key == "gemini":
            return await self._gemini(texts)
        return await self._openai_compatible(texts)

    async def _gemini(self, texts: list[str]) -> list[list[float]]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model}:batchEmbedContents"
        )
        payload = {
            "requests": [
                {"model": f"models/{self.model}", "content": {"parts": [{"text": t}]}}
                for t in texts
            ]
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, params={"key": self.api_key}, json=payload)

        if not response.is_success:
            raise EmbeddingError(f"Gemini embeddings failed: {response.text[:200]}")
        return [e["values"] for e in response.json()["embeddings"]]

    async def _openai_compatible(self, texts: list[str]) -> list[list[float]]:
        base = {
            "openai": "https://api.openai.com/v1",
            "jina": "https://api.jina.ai/v1",
        }.get(self.provider_key, "https://api.openai.com/v1")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )

        if not response.is_success:
            raise EmbeddingError(f"{self.provider_key} embeddings failed: {response.text[:200]}")
        return [item["embedding"] for item in response.json()["data"]]


def build_embedding_provider(
    provider_key: str, *, api_key: str | None = None, model: str | None = None
) -> EmbeddingProvider:
    spec = AVAILABLE_MODELS.get(provider_key)
    if spec is None:
        raise EmbeddingError(f"'{provider_key}' is not a supported embedding provider.")

    if provider_key == "local":
        return LocalEmbeddingProvider(model or spec.model, spec.dim)

    if not api_key:
        raise EmbeddingError(f"{provider_key} embeddings need an API key.")

    return APIEmbeddingProvider(provider_key, api_key, model or spec.model, spec.dim)
