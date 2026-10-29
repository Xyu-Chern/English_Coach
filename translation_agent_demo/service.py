from .config import Settings
from .guardrails import encode_user_payload, parse_translation_response, validate_request
from .models import TranslationResponse
from .prompts import SYSTEM_PROMPT
from .providers.protocol import ChatModel


class TranslationService:
    """Application service: validate input, call one model, validate output."""

    def __init__(self, model: ChatModel, settings: Settings) -> None:
        self._model = model
        self._settings = settings

    def translate(self, text: str) -> TranslationResponse:
        request = validate_request(text, max_chars=self._settings.max_input_chars)
        raw_content = self._model.complete(
            system_prompt=SYSTEM_PROMPT,
            user_payload=encode_user_payload(request),
        )
        return parse_translation_response(
            raw_content,
            max_chars=self._settings.max_output_chars,
        )
