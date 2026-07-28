from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from .errors import ConfigurationError


class CredentialResolver(Protocol):
    """Resolves an opaque credential ID without persisting the secret."""

    def resolve(self, credential_id: str) -> str: ...


class MappingCredentialResolver:
    """In-memory resolver for tests and embedding applications.

    Production desktop builds should implement ``CredentialResolver`` with the
    operating-system keychain instead.
    """

    def __init__(self, credentials: Mapping[str, str]) -> None:
        self._credentials = dict(credentials)

    def resolve(self, credential_id: str) -> str:
        try:
            value = self._credentials[credential_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"credential reference '{credential_id}' was not found"
            ) from exc
        if not isinstance(value, str) or not value:
            raise ConfigurationError(
                f"credential reference '{credential_id}' resolved to an empty value"
            )
        return value
