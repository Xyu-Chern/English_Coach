import json
from collections.abc import Mapping

from .errors import InputValidationError, ModelOutputError
from .models import TranslationRequest, TranslationResponse


_ALLOWED_CONTROLS = {"\n", "\r", "\t"}


def validate_request(text: str, *, max_chars: int) -> TranslationRequest:
    if not isinstance(text, str):
        raise InputValidationError("Input must be text.")

    normalized = text.strip()
    if not normalized:
        raise InputValidationError("Enter text to translate.")
    if len(normalized) > max_chars:
        raise InputValidationError(f"Input is too long (limit: {max_chars} characters).")

    for char in normalized:
        if (ord(char) < 32 and char not in _ALLOWED_CONTROLS) or ord(char) == 127:
            raise InputValidationError("Input contains unsupported control characters.")

    return TranslationRequest(text=normalized)


def encode_user_payload(request: TranslationRequest) -> str:
    """Keep the untrusted translation text structurally separate from instructions."""
    return json.dumps({"text": request.text}, ensure_ascii=False)


def parse_translation_response(raw_content: str, *, max_chars: int) -> TranslationResponse:
    try:
        payload = json.loads(raw_content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ModelOutputError("The model did not return the required JSON translation.") from exc

    if not isinstance(payload, Mapping) or set(payload.keys()) != {"translation"}:
        raise ModelOutputError("The model response must contain only a translation field.")

    translation = payload["translation"]
    if not isinstance(translation, str) or not translation.strip():
        raise ModelOutputError("The model returned an empty or invalid translation.")

    translation = translation.strip()
    if len(translation) > max_chars:
        raise ModelOutputError("The model response exceeded the output limit.")

    return TranslationResponse(translation=translation)
