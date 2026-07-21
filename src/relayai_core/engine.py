from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Iterable

from .errors import ConfigurationError, PolicyViolation
from .models import (
    AdapterRef,
    AudioArtifact,
    DestinationReceipt,
    ExposureEvent,
    PipelineDefinition,
    PipelineRun,
    RunStatus,
)
from .policy import destination_requires_approval, validate_stage_exposure
from .registry import AdapterRegistry


@dataclass(frozen=True, slots=True)
class PreparedRun:
    pipeline: PipelineDefinition
    run: PipelineRun


class PipelineEngine:
    def __init__(self, registry: AdapterRegistry) -> None:
        self.registry = registry

    def _preflight(self, pipeline: PipelineDefinition) -> None:
        speech = self.registry.speech.get(pipeline.transcription.adapter_id)
        validate_stage_exposure(pipeline, "transcription", speech)

        if pipeline.refinement.enabled:
            if pipeline.refinement.adapter is None:
                raise ConfigurationError(
                    "refinement is enabled but no refinement adapter is configured"
                )
            refinement = self.registry.refinement.get(
                pipeline.refinement.adapter.adapter_id
            )
            validate_stage_exposure(pipeline, "refinement", refinement)

        for context_ref in pipeline.context:
            context = self.registry.context.get(context_ref.adapter_id)
            validate_stage_exposure(pipeline, "context", context)

        for destination_ref in pipeline.destinations:
            destination = self.registry.destinations.get(destination_ref.adapter_id)
            validate_stage_exposure(pipeline, "destination", destination)

    async def prepare(
        self, pipeline: PipelineDefinition, audio: AudioArtifact
    ) -> PreparedRun:
        run = PipelineRun(pipeline_id=pipeline.id)
        try:
            self._preflight(pipeline)
        except PolicyViolation:
            run.finish(RunStatus.DENIED)
            raise
        except Exception:
            run.finish(RunStatus.FAILED)
            raise

        speech = self.registry.speech.get(pipeline.transcription.adapter_id)
        started = perf_counter()
        transcript = await speech.transcribe(audio, pipeline.transcription)
        run.timings_ms["transcription"] = (perf_counter() - started) * 1000
        run.raw_transcript = transcript.text
        run.final_text = transcript.text
        run.providers.append(speech.adapter_id)
        run.exposure_events.append(
            ExposureEvent("transcription", speech.adapter_id, speech.exposure)
        )

        context_artifacts = []
        for context_ref in pipeline.context:
            provider = self.registry.context.get(context_ref.adapter_id)
            started = perf_counter()
            artifact = await provider.collect(context_ref)
            run.timings_ms[f"context:{provider.adapter_id}"] = (
                perf_counter() - started
            ) * 1000
            context_artifacts.append(artifact)
            run.providers.append(provider.adapter_id)
            run.exposure_events.append(
                ExposureEvent("context", provider.adapter_id, provider.exposure)
            )

        if pipeline.refinement.enabled:
            refinement_ref = pipeline.refinement.adapter
            assert refinement_ref is not None
            provider = self.registry.refinement.get(refinement_ref.adapter_id)
            started = perf_counter()
            try:
                run.final_text = await provider.refine(
                    transcript,
                    tuple(context_artifacts),
                    refinement_ref,
                    pipeline.refinement.prompt_id,
                )
            except Exception as exc:
                run.warnings.append(
                    f"refinement failed; using raw transcript: {type(exc).__name__}"
                )
                run.final_text = run.raw_transcript
            run.timings_ms["refinement"] = (perf_counter() - started) * 1000
            run.providers.append(provider.adapter_id)
            run.exposure_events.append(
                ExposureEvent("refinement", provider.adapter_id, provider.exposure)
            )

        run.status = RunStatus.READY
        return PreparedRun(pipeline=pipeline, run=run)

    async def dispatch(
        self,
        prepared: PreparedRun,
        approved_destination_ids: Iterable[str] = (),
    ) -> PipelineRun:
        run = prepared.run
        if run.status is not RunStatus.READY:
            raise ConfigurationError("only a prepared run can be dispatched")
        if run.final_text is None:
            raise ConfigurationError("prepared run has no final text")

        approved = set(approved_destination_ids)
        configured_ids = {
            ref.instance_id for ref in prepared.pipeline.destinations
        }
        unknown_approvals = approved - configured_ids
        if unknown_approvals:
            raise ConfigurationError(
                f"approval references unknown destinations: {sorted(unknown_approvals)}"
            )

        async def deliver(ref: AdapterRef) -> DestinationReceipt:
            adapter = self.registry.destinations.get(ref.adapter_id)
            if destination_requires_approval(prepared.pipeline, adapter):
                if ref.instance_id not in approved:
                    return DestinationReceipt(
                        destination_id=ref.instance_id,
                        adapter_id=adapter.adapter_id,
                        status="awaiting_confirmation",
                        effect=adapter.effect,
                        message="destination requires explicit approval",
                    )
            started = perf_counter()
            try:
                receipt = await adapter.deliver(
                    run.final_text or "",
                    ref,
                    {"run_id": run.id, "pipeline_id": run.pipeline_id},
                )
            except Exception as exc:
                receipt = DestinationReceipt(
                    destination_id=ref.instance_id,
                    adapter_id=adapter.adapter_id,
                    status="failed",
                    effect=adapter.effect,
                    message=f"{type(exc).__name__}: {exc}",
                )
            run.timings_ms[f"destination:{ref.instance_id}"] = (
                perf_counter() - started
            ) * 1000
            return receipt

        run.destinations = list(
            await asyncio.gather(
                *(deliver(ref) for ref in prepared.pipeline.destinations)
            )
        )
        statuses = {receipt.status for receipt in run.destinations}
        if statuses <= {"succeeded"}:
            run.finish(RunStatus.SUCCEEDED)
        elif "succeeded" in statuses:
            run.finish(RunStatus.PARTIAL)
        elif "awaiting_confirmation" in statuses:
            run.finish(RunStatus.PARTIAL)
        else:
            run.finish(RunStatus.FAILED)
        return run
