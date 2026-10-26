"""Exercise the real CLI/model/audio contract; dependencies are provisioned by CI."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from relayai_core import AdapterRef, PipelineDefinition, PipelineEngine, PipelinePolicy
from relayai_core import (
    ResultDestination,
    SQLiteStore,
    WhisperCppModel,
    WhisperCppSpeechProvider,
)
from relayai_core.models import AudioArtifact, RunStatus
from relayai_core.registry import AdapterRegistry


async def smoke(args):
    provider = WhisperCppSpeechProvider(
        args.executable,
        {
            "tiny.en": WhisperCppModel(
                Path(args.model),
                "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f",
            )
        },
        timeout_seconds=180,
    )
    registry = AdapterRegistry()
    registry.speech.add(provider)
    registry.destinations.add(ResultDestination())
    pipeline = PipelineDefinition(
        "real-whisper",
        "Real whisper smoke",
        AdapterRef(
            provider.adapter_id,
            {"model": "tiny.en", "language": "en", "threads": 4, "no_gpu": True},
        ),
        (AdapterRef("builtin.result", id="result"),),
        policy=PipelinePolicy(local_only=True),
    )
    with tempfile.TemporaryDirectory(prefix="relayai-real-whisper-") as directory:
        store = SQLiteStore(Path(directory) / "receipts.db")
        await store.initialize()
        engine = PipelineEngine(registry, store)
        prepared = await engine.prepare(
            pipeline, AudioArtifact(Path(args.audio).read_bytes())
        )
        run = await engine.dispatch(prepared)
        assert run.status is RunStatus.SUCCEEDED
        assert "ask not" in run.final_text.lower()
        assert "country" in run.final_text.lower()
        assert (await store.get_run_receipt(run.id))["status"] == "succeeded"
        assert all(event.exposure.value == "local" for event in run.exposure_events)
        print(
            "Real whisper.cpp integration passed: verified model, JFK audio, transcript, and persisted receipt"
        )
        print(f"Transcription time: {run.timings_ms['transcription']:.0f} ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--audio", required=True)
    asyncio.run(smoke(parser.parse_args()))
