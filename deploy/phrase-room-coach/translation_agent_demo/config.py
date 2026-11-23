import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigurationError

OPENAI_BASE_URL = "https://api.openai.com/v1"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
PROVIDERS = ("openai", "anthropic", "google", "responses")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Claude thinks adaptively before answering and its SDK retries a timed-out call (each retry may
# be billed), so it gets a longer default; LLM_TIMEOUT_SECONDS overrides both.
DEFAULT_TIMEOUT_SECONDS = {"openai": 30.0, "anthropic": 120.0, "google": 60.0, "responses": 120.0}


def _read_env_file(path: Path) -> dict[str, str]:
    """Read a small KEY=VALUE env file without adding a dotenv dependency."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def environment_values() -> dict[str, str]:
    """The demo .env file next to this module, with os.environ taking precedence."""
    values = _read_env_file(Path(__file__).resolve().parent / ".env")
    values.update(os.environ)
    return values


def choice(values: Mapping[str, str], name: str, allowed: tuple[str, ...], default: str | None = None) -> str | None:
    """A lower-cased setting that must be one of allowed; blank means the default."""
    value = values.get(name, "").strip().lower() or default
    if value is not None and value not in allowed:
        raise ConfigurationError(f"{name} must be one of: {', '.join(allowed)}.")
    return value


def openai_api_key(values: Mapping[str, str]) -> str | None:
    """OPENAI_API_KEY, else LLM_API_KEY when LLM_BASE_URL is OpenAI's (the same fallback embeddings use)."""
    key = values.get("OPENAI_API_KEY", "").strip()
    if not key and values.get("LLM_BASE_URL", OPENAI_BASE_URL).strip().rstrip("/") == OPENAI_BASE_URL:
        key = values.get("LLM_API_KEY", "").strip()
    return key or None


def timeout_for(values: Mapping[str, str], provider: str) -> float:
    """LLM_TIMEOUT_SECONDS, or the provider's default when it is not set."""
    try:
        return float(values.get("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS[provider]))
    except ValueError as exc:
        raise ConfigurationError("Timeout, retry and character limits must be numbers.") from exc


def _anthropic_endpoint(values: Mapping[str, str]) -> tuple[str, str | None]:
    """Claude has its own key and URL, so a leftover OpenAI LLM_BASE_URL or LLM_API_KEY is never sent to it."""
    base_url = values.get("ANTHROPIC_BASE_URL", "").strip() or ANTHROPIC_BASE_URL
    return base_url, values.get("ANTHROPIC_API_KEY", "").strip() or None


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float = 30.0
    max_input_chars: int = 4000
    max_output_chars: int = 8000
    provider: str = "openai"
    effort: str | None = None  # Claude output_config.effort; None keeps the model's default
    max_retries: int = 4  # Claude SDK retries (429, 5xx, connection); the OpenAI adapter never retries

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls.from_values(environment_values())

    @classmethod
    def from_values(cls, values: Mapping[str, str]) -> "Settings":
        provider = choice(values, "LLM_PROVIDER", PROVIDERS, "openai")
        if provider == "anthropic":
            base_url, api_key = _anthropic_endpoint(values)
        elif provider == "responses":
            base_url, api_key = values.get("RESPONSES_BASE_URL", OPENAI_BASE_URL), values.get("RESPONSES_API_KEY")
        elif provider == "google":
            base_url, api_key = GOOGLE_BASE_URL, values.get("GEMINI_API_KEY") or values.get("GOOGLE_API_KEY")
        else:
            base_url = values.get("LLM_BASE_URL", OPENAI_BASE_URL).strip()
            api_key = values.get("LLM_API_KEY", "").strip() or None
        model = values.get("LLM_MODEL", "").strip()

        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigurationError("LLM_BASE_URL must be an http(s) URL.")
        if not model:
            raise ConfigurationError("Set LLM_MODEL in the environment or demo .env file.")

        timeout_seconds = timeout_for(values, provider)
        try:
            max_input_chars = int(values.get("MAX_INPUT_CHARS", "4000"))
            max_output_chars = int(values.get("MAX_OUTPUT_CHARS", "8000"))
            max_retries = int(values.get("LLM_MAX_RETRIES", "4"))
        except ValueError as exc:
            raise ConfigurationError("Timeout, retry and character limits must be numbers.") from exc

        if timeout_seconds <= 0 or max_input_chars <= 0 or max_output_chars <= 0:
            raise ConfigurationError("Timeout and character limits must be greater than zero.")
        if not 0 <= max_retries <= 10:
            raise ConfigurationError("LLM_MAX_RETRIES must be between 0 and 10.")

        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_input_chars=max_input_chars,
            max_output_chars=max_output_chars,
            provider=provider,
            effort=choice(values, "LLM_EFFORT", EFFORTS) if provider == "anthropic" else None,
            max_retries=max_retries,
        )


def settings_for(base: Settings, provider: str, model: str, *, effort: str | None = None,
                 values: Mapping[str, str] | None = None) -> Settings:
    """Settings for a second model (the evaluation judge) that may use another provider than chat.

    The same provider keeps the chat endpoint and key; otherwise the other provider's own key
    and default timeout are used, so an OpenAI judge still reaches OpenAI while chat runs on Claude."""
    if provider not in PROVIDERS:
        raise ConfigurationError(f"Unknown provider {provider!r}.")
    effort = effort if provider == "anthropic" else None
    if provider == base.provider:
        return replace(base, model=model, effort=effort)
    values = environment_values() if values is None else values
    if provider == "anthropic":
        base_url, api_key = _anthropic_endpoint(values)
    elif provider == "responses":
        base_url, api_key = values.get("RESPONSES_BASE_URL", OPENAI_BASE_URL), values.get("RESPONSES_API_KEY")
    elif provider == "google":
        base_url, api_key = GOOGLE_BASE_URL, values.get("GEMINI_API_KEY") or values.get("GOOGLE_API_KEY")
    else:
        base_url, api_key = OPENAI_BASE_URL, openai_api_key(values)
    return replace(base, provider=provider, base_url=base_url.rstrip("/"), api_key=api_key, model=model,
                   effort=effort, timeout_seconds=timeout_for(values, provider))
