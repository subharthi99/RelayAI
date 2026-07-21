from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import time
from typing import Any
from uuid import uuid4


CURRENT_SCHEMA_VERSION = 1


class Exposure(StrEnum):
    LOCAL = "local"
    NETWORK = "network"


class DestinationEffect(StrEnum):
    PASSIVE = "passive"
    LOCAL_WRITE = "local_write"
    NETWORK = "network"
    EXECUTE = "execute"


class RunStatus(StrEnum):
    PREPARING = "preparing"
    READY = "ready"
    PARTIAL = "partial"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class AdapterRef:
    adapter_id: str
    settings: dict[str, Any] = field(default_factory=dict)
    credential_id: str | None = None
    id: str | None = None

    @property
    def instance_id(self) -> str:
        return self.id or self.adapter_id


@dataclass(frozen=True, slots=True)
class CaptureConfig:
    activation: str = "push_to_talk"
    source: str = "default_microphone"


@dataclass(frozen=True, slots=True)
class RefinementConfig:
    enabled: bool
    adapter: AdapterRef | None = None
    prompt_id: str | None = None


@dataclass(frozen=True, slots=True)
class PipelinePolicy:
    local_only: bool = False
    confirm_network_destinations: bool = True
    confirm_executable_destinations: bool = True


@dataclass(frozen=True, slots=True)
class PipelineDefinition:
    id: str
    name: str
    transcription: AdapterRef
    destinations: tuple[AdapterRef, ...]
    schema_version: int = CURRENT_SCHEMA_VERSION
    description: str = ""
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    context: tuple[AdapterRef, ...] = ()
    refinement: RefinementConfig = field(
        default_factory=lambda: RefinementConfig(enabled=False)
    )
    policy: PipelinePolicy = field(default_factory=PipelinePolicy)


@dataclass(frozen=True, slots=True)
class AudioArtifact:
    content: bytes
    media_type: str = "audio/wav"


@dataclass(frozen=True, slots=True)
class TranscriptArtifact:
    text: str
    language: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextArtifact:
    provider_id: str
    values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExposureEvent:
    stage: str
    adapter_id: str
    exposure: Exposure


@dataclass(frozen=True, slots=True)
class DestinationReceipt:
    destination_id: str
    adapter_id: str
    status: str
    effect: DestinationEffect
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PipelineRun:
    pipeline_id: str
    id: str = field(default_factory=lambda: str(uuid4()))
    status: RunStatus = RunStatus.PREPARING
    started_at: float = field(default_factory=time)
    completed_at: float | None = None
    raw_transcript: str | None = None
    final_text: str | None = None
    providers: list[str] = field(default_factory=list)
    exposure_events: list[ExposureEvent] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    warnings: list[str] = field(default_factory=list)
    destinations: list[DestinationReceipt] = field(default_factory=list)

    def finish(self, status: RunStatus) -> None:
        self.status = status
        self.completed_at = time()
