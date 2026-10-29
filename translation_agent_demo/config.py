import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigurationError


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


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float = 30.0
    max_input_chars: int = 4000
    max_output_chars: int = 8000

    @classmethod
    def from_environment(cls) -> "Settings":
        env_file = Path(__file__).resolve().parent / ".env"
        values = _read_env_file(env_file)
        values.update(os.environ)

        base_url = values.get("LLM_BASE_URL", "https://api.openai.com/v1").strip()
        model = values.get("LLM_MODEL", "").strip()
        api_key = values.get("LLM_API_KEY", "").strip() or None

        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigurationError("LLM_BASE_URL must be an http(s) URL.")
        if not model:
            raise ConfigurationError("Set LLM_MODEL in the environment or demo .env file.")

        try:
            timeout_seconds = float(values.get("LLM_TIMEOUT_SECONDS", "30"))
            max_input_chars = int(values.get("MAX_INPUT_CHARS", "4000"))
            max_output_chars = int(values.get("MAX_OUTPUT_CHARS", "8000"))
        except ValueError as exc:
            raise ConfigurationError("Timeout and character limits must be numbers.") from exc

        if timeout_seconds <= 0 or max_input_chars <= 0 or max_output_chars <= 0:
            raise ConfigurationError("Timeout and character limits must be greater than zero.")

        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_input_chars=max_input_chars,
            max_output_chars=max_output_chars,
        )
