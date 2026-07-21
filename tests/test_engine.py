from __future__ import annotations

import unittest

from relayai_core.adapters import Destination
from relayai_core.engine import PipelineEngine
from relayai_core.errors import ConfigurationError, PolicyViolation
from relayai_core.models import (
    AdapterRef,
    AudioArtifact,
    DestinationEffect,
    DestinationReceipt,
    Exposure,
    PipelineDefinition,
    PipelinePolicy,
    RefinementConfig,
    RunStatus,
    TranscriptArtifact,
)
from relayai_core.registry import AdapterRegistry


class FakeSpeech:
    adapter_id = "fake.speech"

    def __init__(self, exposure: Exposure = Exposure.LOCAL) -> None:
        self.exposure = exposure
        self.calls = 0

    async def transcribe(
        self, audio: AudioArtifact, config: AdapterRef
    ) -> TranscriptArtifact:
        self.calls += 1
        return TranscriptArtifact(audio.content.decode())


class FakeRefinement:
    adapter_id = "fake.refinement"
    exposure = Exposure.LOCAL

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def refine(self, transcript, context, config, prompt_id):
        if self.fail:
            raise TimeoutError("provider timed out")
        return transcript.text.upper()


class FakeDestination(Destination):
    def __init__(
        self,
        adapter_id: str,
        effect: DestinationEffect = DestinationEffect.PASSIVE,
        exposure: Exposure = Exposure.LOCAL,
        fail: bool = False,
    ) -> None:
        self.adapter_id = adapter_id
        self.effect = effect
        self.exposure = exposure
        self.fail = fail
        self.delivered: list[str] = []

    async def deliver(self, text, config, run_metadata):
        if self.fail:
            raise RuntimeError("delivery failed")
        self.delivered.append(text)
        return DestinationReceipt(
            destination_id=config.instance_id,
            adapter_id=self.adapter_id,
            status="succeeded",
            effect=self.effect,
        )


def pipeline(
    *,
    local_only: bool = False,
    refinement: bool = False,
    destinations: tuple[AdapterRef, ...] | None = None,
) -> PipelineDefinition:
    return PipelineDefinition(
        id="test",
        name="Test",
        transcription=AdapterRef("fake.speech"),
        refinement=RefinementConfig(
            enabled=refinement,
            adapter=AdapterRef("fake.refinement") if refinement else None,
        ),
        policy=PipelinePolicy(local_only=local_only),
        destinations=destinations or (AdapterRef("fake.output", id="primary"),),
    )


class PipelineEngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.registry = AdapterRegistry()
        self.speech = FakeSpeech()
        self.output = FakeDestination("fake.output")
        self.registry.speech.add(self.speech)
        self.registry.destinations.add(self.output)

    async def test_local_only_rejects_network_before_transcription(self) -> None:
        self.speech.exposure = Exposure.NETWORK
        engine = PipelineEngine(self.registry)

        with self.assertRaises(PolicyViolation):
            await engine.prepare(pipeline(local_only=True), AudioArtifact(b"hello"))

        self.assertEqual(self.speech.calls, 0)

    async def test_refinement_failure_falls_back_to_raw_transcript(self) -> None:
        self.registry.refinement.add(FakeRefinement(fail=True))
        engine = PipelineEngine(self.registry)

        prepared = await engine.prepare(
            pipeline(refinement=True), AudioArtifact(b"raw words")
        )
        run = await engine.dispatch(prepared)

        self.assertEqual(run.raw_transcript, "raw words")
        self.assertEqual(run.final_text, "raw words")
        self.assertEqual(self.output.delivered, ["raw words"])
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertIn("refinement failed", run.warnings[0])

    async def test_network_destination_requires_instance_approval(self) -> None:
        webhook = FakeDestination(
            "fake.webhook", DestinationEffect.NETWORK, Exposure.NETWORK
        )
        self.registry.destinations.add(webhook)
        configured = pipeline(
            destinations=(AdapterRef("fake.webhook", id="issue-tracker"),)
        )
        engine = PipelineEngine(self.registry)

        first = await engine.prepare(configured, AudioArtifact(b"create issue"))
        unapproved = await engine.dispatch(first)
        self.assertEqual(unapproved.status, RunStatus.PARTIAL)
        self.assertEqual(
            unapproved.destinations[0].status, "awaiting_confirmation"
        )
        self.assertEqual(webhook.delivered, [])

        second = await engine.prepare(configured, AudioArtifact(b"create issue"))
        approved = await engine.dispatch(second, {"issue-tracker"})
        self.assertEqual(approved.status, RunStatus.SUCCEEDED)
        self.assertEqual(webhook.delivered, ["create issue"])

    async def test_same_adapter_can_have_multiple_destination_instances(self) -> None:
        configured = pipeline(
            destinations=(
                AdapterRef("fake.output", id="first"),
                AdapterRef("fake.output", id="second"),
            )
        )
        run = await PipelineEngine(self.registry).dispatch(
            await PipelineEngine(self.registry).prepare(
                configured, AudioArtifact(b"two copies")
            )
        )
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertEqual(self.output.delivered, ["two copies", "two copies"])

    async def test_unknown_approval_is_rejected(self) -> None:
        engine = PipelineEngine(self.registry)
        prepared = await engine.prepare(pipeline(), AudioArtifact(b"hello"))
        with self.assertRaises(ConfigurationError):
            await engine.dispatch(prepared, {"not-configured"})

    async def test_failed_destination_receipt_keeps_instance_id(self) -> None:
        failing = FakeDestination("fake.failing", fail=True)
        self.registry.destinations.add(failing)
        configured = pipeline(
            destinations=(AdapterRef("fake.failing", id="named-output"),)
        )
        engine = PipelineEngine(self.registry)
        run = await engine.dispatch(
            await engine.prepare(configured, AudioArtifact(b"preserved"))
        )

        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.raw_transcript, "preserved")
        self.assertEqual(run.destinations[0].destination_id, "named-output")


if __name__ == "__main__":
    unittest.main()
