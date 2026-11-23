from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationRequest:
    text: str


@dataclass(frozen=True)
class TranslationResponse:
    translation: str
