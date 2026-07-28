class RelayAIError(Exception):
    """Base exception for recoverable core failures."""


class ConfigurationError(RelayAIError):
    """A pipeline or adapter configuration is invalid."""


class PolicyViolation(RelayAIError):
    """Execution would violate an enforceable pipeline policy."""


class AdapterNotFound(ConfigurationError):
    """A pipeline references an adapter that is not registered."""


class ProviderError(RelayAIError):
    """A provider request failed or returned an invalid response."""
