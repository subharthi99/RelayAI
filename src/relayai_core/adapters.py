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

    async def transcribe(
        self, audio: AudioArtifact, config: AdapterRef
    ) -> TranscriptArtifact: ...


class RefinementProvider(Protocol):
    adapter_id: str
    exposure: Exposure

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

    async def collect(self, config: AdapterRef) -> ContextArtifact: ...


class Destination(Protocol):
    adapter_id: str
    exposure: Exposure
    effect: DestinationEffect

    async def deliver(
        self,
        text: str,
        config: AdapterRef,
        run_metadata: dict[str, Any],
    ) -> DestinationReceipt: ...
