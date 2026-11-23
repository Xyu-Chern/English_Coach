class TranslationDemoError(Exception):
    """Base class for expected demo errors."""


class InputValidationError(TranslationDemoError):
    """The submitted text is missing or outside the accepted limits."""


class ConfigurationError(TranslationDemoError):
    """The model provider configuration is incomplete or invalid."""


class ModelProviderError(TranslationDemoError):
    """The configured model provider could not complete the request."""


class ModelOutputError(TranslationDemoError):
    """The model response did not match the required translation schema."""
