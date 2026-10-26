from __future__ import annotations

from typing import Any, Protocol

from .models import (
    AdapterRef,
    AudioArtifact,
    ContextArtifact,
    DestinationEffect,
    DestinationReceipt,
    Exposure,
    TranscriptArtifact,
)


class SpeechProvider(Protocol):
    adapter_id: str
    exposure: Exposure

    def configuration_fingerprint(self) -> Any:
        """Stable non-secret JSON configuration/digest; required for durable runs."""
        ...

    async def transcribe(
        self, audio: AudioArtifact, config: AdapterRef
    ) -> TranscriptArtifact: ...


class RefinementProvider(Protocol):
    adapter_id: str
    exposure: Exposure

    def configuration_fingerprint(self) -> Any: ...

    async def refine(
        self,
        transcript: TranscriptArtifact,
        context: tuple[ContextArtifact, ...],
        config: AdapterRef,
        prompt_id: str | None,
    ) -> str: ...


class ContextProvider(Protocol):
    adapter_id: str
    exposure: Exposure

    def configuration_fingerprint(self) -> Any: ...

    async def collect(self, config: AdapterRef) -> ContextArtifact: ...


class Destination(Protocol):
    adapter_id: str
    exposure: Exposure
    effect: DestinationEffect

    def configuration_fingerprint(self) -> Any: ...

    async def deliver(
        self,
        text: str,
        config: AdapterRef,
        run_metadata: dict[str, Any],
    ) -> DestinationReceipt: ...
