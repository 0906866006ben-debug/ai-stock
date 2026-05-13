"""Exception contracts for technical analyzer v1."""


class MissingInvalidationError(ValueError):
    """Raised when a non-neutral read is missing invalidation signals."""


class InsufficientDataError(ValueError):
    """Raised when a requested analysis horizon lacks enough bars."""


class RuleRegistryError(RuntimeError):
    """Raised when the rule registry is missing required configuration."""
