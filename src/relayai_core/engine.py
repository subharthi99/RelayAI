from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Iterable

from .errors import ConfigurationError, PolicyViolation
from .models import (
    AudioArtifact,
    DestinationReceipt,
    ExposureEvent,
    PipelineDefinition,
    PipelineRun,
    RunStatus,
)
from .policy import destination_requires_approval, validate_stage_exposure
from .registry import AdapterRegistry
from .serialization import export_pipeline, load_pipeline


@dataclass(frozen=True, slots=True)
class PreparedRun:
    pipeline: PipelineDefinition
    run: PipelineRun
    binding: str = ""


class PipelineEngine:
    def __init__(self, registry: AdapterRegistry, store=None) -> None:
        self.registry = registry
        self.store = store

    async def _save(self, run: PipelineRun) -> None:
        if self.store is not None:
            await self.store.save_run(run)

    def _adapters(self, pipeline):
        yield (
            "transcription",
            self.registry.speech.get(pipeline.transcription.adapter_id),
        )
        if pipeline.refinement.enabled:
            if pipeline.refinement.adapter is None:
                raise ConfigurationError(
                    "refinement is enabled but no adapter is configured"
                )
            yield (
                "refinement",
                self.registry.refinement.get(pipeline.refinement.adapter.adapter_id),
            )
        for ref in pipeline.context:
            yield "context", self.registry.context.get(ref.adapter_id)
        for ref in pipeline.destinations:
            yield "destination", self.registry.destinations.get(ref.adapter_id)

    def _preflight(self, pipeline) -> None:
        for stage, adapter in self._adapters(pipeline):
            validate_stage_exposure(pipeline, stage, adapter)

    def _binding(self, pipeline, run) -> str:
        adapters = []
        for stage, adapter in self._adapters(pipeline):
            fingerprint = getattr(adapter, "configuration_fingerprint", None)
            fingerprint_value = fingerprint() if fingerprint is not None else None
            if fingerprint_value is None and self.store is not None:
                raise ConfigurationError(
                    "persisted adapters must implement configuration_fingerprint"
                )
            adapters.append(
                (
                    stage,
                    type(adapter).__module__,
                    type(adapter).__qualname__,
                    adapter.adapter_id,
                    adapter.exposure.value,
                    getattr(adapter, "effect", None),
                    fingerprint_value,
                )
            )
        document = json.dumps(
            [export_pipeline(pipeline), run.raw_transcript, run.final_text, adapters],
            sort_keys=True,
        )
        return hashlib.sha256(document.encode()).hexdigest()

    async def prepare(
        self, pipeline: PipelineDefinition, audio: AudioArtifact
    ) -> PreparedRun:
        run = PipelineRun(pipeline_id=pipeline.id)
        await self._save(run)
        try:
            pipeline = load_pipeline(export_pipeline(pipeline))
            self._preflight(pipeline)
            await self._prepare_stages(pipeline, audio, run)
            run.status = RunStatus.READY
            prepared = PreparedRun(pipeline, run, self._binding(pipeline, run))
            if self.store is not None:
                await self.store.save_prepared(prepared)
            return prepared
        except asyncio.CancelledError:
            run.error_code = "cancelled"
            run.finish(RunStatus.CANCELLED)
            await self._save(run)
            raise
        except Exception as exc:
            run.error_code = type(exc).__name__
            run.finish(
                RunStatus.DENIED
                if isinstance(exc, PolicyViolation)
                else RunStatus.FAILED
            )
            await self._save(run)
            exc.run = run
            raise

    async def _stage(self, run, name, adapter, operation):
        run.providers.append(adapter.adapter_id)
        index = len(run.exposure_events)
        run.exposure_events.append(
            ExposureEvent(name, adapter.adapter_id, adapter.exposure)
        )
        await self._save(run)
        start = perf_counter()
        outcome = "failed"
        try:
            result = await operation()
            outcome = "succeeded"
            return result
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            run.timings_ms[name] = (perf_counter() - start) * 1000
            run.exposure_events[index] = ExposureEvent(
                name, adapter.adapter_id, adapter.exposure, outcome
            )

    async def _prepare_stages(self, pipeline, audio, run):
        speech = self.registry.speech.get(pipeline.transcription.adapter_id)
        transcript = await self._stage(
            run,
            "transcription",
            speech,
            lambda: speech.transcribe(audio, pipeline.transcription),
        )
        if not isinstance(transcript.text, str):
            raise ConfigurationError("speech adapter returned non-text transcript")
        run.raw_transcript = run.final_text = transcript.text
        context = []
        for index, ref in enumerate(pipeline.context):
            adapter = self.registry.context.get(ref.adapter_id)
            context.append(
                await self._stage(
                    run, f"context:{index}", adapter, lambda: adapter.collect(ref)
                )
            )
        if pipeline.refinement.enabled:
            ref = pipeline.refinement.adapter
            adapter = self.registry.refinement.get(ref.adapter_id)
            try:
                refined = await self._stage(
                    run,
                    "refinement",
                    adapter,
                    lambda: adapter.refine(
                        transcript, tuple(context), ref, pipeline.refinement.prompt_id
                    ),
                )
                if not isinstance(refined, str) or not refined.strip():
                    raise ConfigurationError(
                        "refinement returned empty or non-text output"
                    )
                run.final_text = refined
            except Exception as exc:
                run.warnings.append(
                    f"refinement failed; using raw transcript: {type(exc).__name__}"
                )
                run.final_text = run.raw_transcript

    async def dispatch(
        self, prepared: PreparedRun, approved_destination_ids: Iterable[str] = ()
    ) -> PipelineRun:
        run = prepared.run
        if run.status not in {RunStatus.READY, RunStatus.PARTIAL}:
            raise ConfigurationError("only a prepared or pending run can be dispatched")
        if run.status is RunStatus.PARTIAL and not any(
            r.status == "awaiting_confirmation" for r in run.destinations
        ):
            raise ConfigurationError(
                "failed destinations cannot be retried automatically"
            )
        self._preflight(prepared.pipeline)
        if not prepared.binding or prepared.binding != self._binding(
            prepared.pipeline, run
        ):
            raise ConfigurationError(
                "prepared text, pipeline, or adapter configuration changed; prepare again"
            )
        approved = set(approved_destination_ids)
        configured = {ref.instance_id for ref in prepared.pipeline.destinations}
        if approved - configured:
            raise ConfigurationError(
                f"approval references unknown destinations: {sorted(approved - configured)}"
            )
        previous = json.dumps(asdict(run), sort_keys=True)
        previous_digest = hashlib.sha256(previous.encode()).hexdigest()
        self.registry.claim(run.id, previous_digest, "dispatching")
        run.status = RunStatus.DISPATCHING
        run.completed_at = None
        if self.store is not None:
            await self.store.claim_run(previous, run)
        receipts = {r.destination_id: r for r in run.destinations}
        try:
            for ref in prepared.pipeline.destinations:
                old = receipts.get(ref.instance_id)
                if old is not None and old.status != "awaiting_confirmation":
                    continue
                adapter = self.registry.destinations.get(ref.adapter_id)
                if (
                    destination_requires_approval(prepared.pipeline, adapter)
                    and ref.instance_id not in approved
                ):
                    receipts[ref.instance_id] = DestinationReceipt(
                        ref.instance_id,
                        adapter.adapter_id,
                        "awaiting_confirmation",
                        adapter.effect,
                        "destination requires explicit approval",
                    )
                else:
                    receipts[ref.instance_id] = DestinationReceipt(
                        ref.instance_id,
                        adapter.adapter_id,
                        "in_progress",
                        adapter.effect,
                    )
                    run.destinations = list(receipts.values())
                    await self._save(run)
                    try:
                        receipt = await self._stage(
                            run,
                            f"destination:{ref.instance_id}",
                            adapter,
                            lambda: adapter.deliver(
                                run.final_text or "",
                                ref,
                                {
                                    "run_id": run.id,
                                    "pipeline_id": run.pipeline_id,
                                    "idempotency_key": f"{run.id}:{ref.instance_id}",
                                },
                            ),
                        )
                        if (
                            receipt.destination_id != ref.instance_id
                            or receipt.adapter_id != adapter.adapter_id
                            or receipt.effect is not adapter.effect
                            or receipt.status != "succeeded"
                        ):
                            raise ConfigurationError(
                                "destination returned an invalid receipt"
                            )
                        receipts[ref.instance_id] = receipt
                    except Exception as exc:
                        receipts[ref.instance_id] = DestinationReceipt(
                            ref.instance_id,
                            adapter.adapter_id,
                            "failed",
                            adapter.effect,
                            type(exc).__name__,
                        )
                run.destinations = list(receipts.values())
                await self._save(run)
            statuses = {r.status for r in run.destinations}
            run.finish(
                RunStatus.SUCCEEDED
                if statuses == {"succeeded"}
                else RunStatus.PARTIAL
                if "succeeded" in statuses or "awaiting_confirmation" in statuses
                else RunStatus.FAILED
            )
        except asyncio.CancelledError:
            run.error_code = "cancelled_outcome_may_be_unknown"
            run.finish(RunStatus.CANCELLED)
            raise
        except Exception as exc:
            run.error_code = type(exc).__name__
            run.finish(RunStatus.FAILED)
            raise
        finally:
            await self._save(run)
            self.registry.remember(
                run.id,
                hashlib.sha256(
                    json.dumps(asdict(run), sort_keys=True).encode()
                ).hexdigest(),
            )
        return run
