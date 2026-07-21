from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from .adapters import ContextProvider, Destination, RefinementProvider, SpeechProvider
from .errors import AdapterNotFound, ConfigurationError


T = TypeVar("T")


@dataclass(slots=True)
class _AdapterMap(Generic[T]):
    kind: str
    values: dict[str, T] = field(default_factory=dict)

    def add(self, adapter: T) -> None:
        adapter_id = getattr(adapter, "adapter_id", "")
        if not adapter_id:
            raise ConfigurationError(f"{self.kind} adapter has no adapter_id")
        if adapter_id in self.values:
            raise ConfigurationError(
                f"duplicate {self.kind} adapter id: {adapter_id}"
            )
        self.values[adapter_id] = adapter

    def get(self, adapter_id: str) -> T:
        try:
            return self.values[adapter_id]
        except KeyError as exc:
            raise AdapterNotFound(
                f"unknown {self.kind} adapter: {adapter_id}"
            ) from exc


@dataclass(slots=True)
class AdapterRegistry:
    speech: _AdapterMap[SpeechProvider] = field(
        default_factory=lambda: _AdapterMap("speech")
    )
    refinement: _AdapterMap[RefinementProvider] = field(
        default_factory=lambda: _AdapterMap("refinement")
    )
    context: _AdapterMap[ContextProvider] = field(
        default_factory=lambda: _AdapterMap("context")
    )
    destinations: _AdapterMap[Destination] = field(
        default_factory=lambda: _AdapterMap("destination")
    )
