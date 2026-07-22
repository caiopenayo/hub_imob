class SearchIntentGenerationError(Exception):
    """Raised when a model cannot produce a valid search intent."""


class SearchIntentParsingError(Exception):
    """Raised when a model response does not contain valid JSON."""


class SearchIntentValidationError(Exception):
    """Raised when parsed JSON does not match the SearchIntent schema."""


class SearchModelUnavailableError(Exception):
    """Raised when the configured local model cannot be used."""
