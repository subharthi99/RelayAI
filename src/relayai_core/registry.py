from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Generic, TypeVar

from .adapters import ContextProvider, Destination, RefinementProvider, SpeechProvider
from .errors import AdapterNotFound, ConfigurationError
from .models import Exposure, DestinationEffect


T = TypeVar("T")


@dataclass(slots=True)
class _AdapterMap(Generic[T]):
    kind: str
    values: dict[str, T] = field(default_factory=dict)

    def add(self, adapter: T) -> None:
        adapter_id = getattr(adapter, "adapter_id", "")
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            raise ConfigurationError(f"{self.kind} adapter has no adapter_id")
        self._validate(adapter)
        if adapter_id in self.values:
            raise ConfigurationError(f"duplicate {self.kind} adapter id: {adapter_id}")
        self.values[adapter_id] = adapter

    def get(self, adapter_id: str) -> T:
        try:
            adapter = self.values[adapter_id]
        except KeyError as exc:
            raise AdapterNotFound(f"unknown {self.kind} adapter: {adapter_id}") from exc
        self._validate(adapter)
        if adapter.adapter_id != adapter_id:
            raise ConfigurationError("registered adapter identity changed")
        return adapter

    def _validate(self, adapter: T) -> None:
        if not isinstance(getattr(adapter, "exposure", None), Exposure):
            raise ConfigurationError(f"{self.kind} exposure must be an Exposure enum")
        if self.kind == "destination":
            effect = getattr(adapter, "effect", None)
            if not isinstance(effect, DestinationEffect):
                raise ConfigurationError(
                    "destination effect must be a DestinationEffect enum"
                )
            if (
                effect is DestinationEffect.NETWORK
                and adapter.exposure is not Exposure.NETWORK
            ):
                raise ConfigurationError(
                    "network destination must declare network exposure"
                )


@dataclass(slots=True)
class AdapterRegistry:
    _versions: dict[str, str] = field(default_factory=dict, repr=False)
    _claim_lock: Lock = field(default_factory=Lock, repr=False)

    def claim(self, run_id: str, previous: str, current: str) -> None:
        with self._claim_lock:
            if self._versions.get(run_id, previous) != previous:
                raise ConfigurationError(
                    "run is already claimed or this snapshot is stale"
                )
            self._versions[run_id] = current

    def remember(self, run_id: str, current: str) -> None:
        with self._claim_lock:
            self._versions[run_id] = current

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
