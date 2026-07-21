from __future__ import annotations

from .adapters import ContextProvider, Destination, RefinementProvider, SpeechProvider
from .errors import PolicyViolation
from .models import DestinationEffect, Exposure, PipelineDefinition


def validate_stage_exposure(
    pipeline: PipelineDefinition,
    stage: str,
    adapter: SpeechProvider | RefinementProvider | ContextProvider | Destination,
) -> None:
    if pipeline.policy.local_only and adapter.exposure is Exposure.NETWORK:
        raise PolicyViolation(
            f"pipeline '{pipeline.id}' is local_only but {stage} adapter "
            f"'{adapter.adapter_id}' uses the network"
        )


def destination_requires_approval(
    pipeline: PipelineDefinition, destination: Destination
) -> bool:
    if destination.effect is DestinationEffect.NETWORK:
        return pipeline.policy.confirm_network_destinations
    if destination.effect is DestinationEffect.EXECUTE:
        return pipeline.policy.confirm_executable_destinations
    return False
