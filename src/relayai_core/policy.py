from __future__ import annotations

from .adapters import ContextProvider, Destination, RefinementProvider, SpeechProvider
from .errors import ConfigurationError, PolicyViolation
from .models import DestinationEffect, Exposure, PipelineDefinition


def validate_stage_exposure(
    pipeline: PipelineDefinition,
    stage: str,
    adapter: SpeechProvider | RefinementProvider | ContextProvider | Destination,
) -> None:
    if not isinstance(adapter.exposure, Exposure):
        raise ConfigurationError("adapter exposure must be an Exposure enum")
    if (
        pipeline.policy.local_only
        and getattr(adapter, "effect", None) is DestinationEffect.EXECUTE
    ):
        raise PolicyViolation("local_only rejects unsandboxed executable destinations")
    if pipeline.policy.local_only and adapter.exposure is Exposure.NETWORK:
        raise PolicyViolation(
            f"pipeline '{pipeline.id}' is local_only but {stage} adapter "
            f"'{adapter.adapter_id}' uses the network"
        )


def destination_requires_approval(
    pipeline: PipelineDefinition, destination: Destination
) -> bool:
    if not isinstance(destination.effect, DestinationEffect):
        raise ConfigurationError("destination effect must be a DestinationEffect enum")
    if destination.effect is DestinationEffect.NETWORK:
        return pipeline.policy.confirm_network_destinations
    if destination.effect is DestinationEffect.EXECUTE:
        return pipeline.policy.confirm_executable_destinations
    return False
