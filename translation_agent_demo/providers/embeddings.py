"""Select one embedding space for corpus preparation and query retrieval."""

import os
from pathlib import Path

from ..config import _read_env_file
from .embedding_protocol import EmbeddingError, EmbeddingProvider
from .google_embeddings import GoogleEmbeddingClient
from .local_embeddings import MODEL as LOCAL_MODEL, local_client
from .openai_embeddings import OpenAIEmbeddingClient, OpenAIEmbeddingSettings


def _settings(env_file: Path | None):
    path = env_file or Path(__file__).resolve().parents[1] / ".env"
    return {**_read_env_file(path), **os.environ}


def _provider(values):
    provider = values.get("EMBEDDING_PROVIDER", "openai").strip().lower()
    if provider not in {"google", "openai", "local"}:
        raise EmbeddingError("EMBEDDING_PROVIDER must be local, openai or google.")
    return provider


def embedding_model(env_file: Path | None = None) -> str:
    models = {"local": LOCAL_MODEL, "google": GoogleEmbeddingClient.model, "openai": OpenAIEmbeddingClient.model}
    return models[_provider(_settings(env_file))]


def embedding_client(env_file: Path | None = None) -> EmbeddingProvider:
    values = _settings(env_file)
    provider = _provider(values)
    if provider == "local":
        return local_client()
    if provider == "google":
        return GoogleEmbeddingClient(values.get("GEMINI_API_KEY") or values.get("GOOGLE_API_KEY", ""))
    return OpenAIEmbeddingClient(OpenAIEmbeddingSettings.from_environment(env_file))
