import argparse
import sys

from .config import Settings
from .errors import TranslationDemoError
from .providers.openai_compatible import OpenAICompatibleChatModel
from .service import TranslationService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Translate text into English using an LLM."
    )
    parser.add_argument("text", nargs="?", help="Text to translate; omit to enter it interactively.")
    args = parser.parse_args(argv)

    text = args.text
    if text is None:
        try:
            text = input("Text to translate: ")
        except EOFError:
            print("No input received.", file=sys.stderr)
            return 2

    try:
        settings = Settings.from_environment()
        service = TranslationService(OpenAICompatibleChatModel(settings), settings)
        result = service.translate(text)
    except TranslationDemoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(result.translation)
    return 0
