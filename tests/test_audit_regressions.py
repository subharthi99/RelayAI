from __future__ import annotations

import asyncio
import copy
import json
import os
import stat
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from relayai_core import *
from relayai_core.models import AudioArtifact, TranscriptArtifact, DestinationReceipt
from relayai_core.registry import AdapterRegistry
from relayai_core.processes import run_process
from relayai_core.openai_compatible import StandardLibraryHTTPTransport


class Speech:
    adapter_id = "speech"
    exposure = Exposure.LOCAL

    def configuration_fingerprint(self):
        return "speech-fixture/v1"

    async def transcribe(self, audio, config):
        return TranscriptArtifact("private words")


class Output:
    adapter_id = "output"
    exposure = Exposure.LOCAL
    effect = DestinationEffect.PASSIVE

    def configuration_fingerprint(self):
        return "output-fixture/v1"

    def __init__(self):
        self.calls = 0

    async def deliver(self, text, config, metadata):
        self.calls += 1
        await asyncio.sleep(0.01)
        return DestinationReceipt(
            config.instance_id, self.adapter_id, "succeeded", self.effect
        )


def runtime():
    registry = AdapterRegistry()
    registry.speech.add(Speech())
    output = Output()
    registry.destinations.add(output)
    definition = PipelineDefinition(
        "audit", "Audit", AdapterRef("speech"), (AdapterRef("output", id="out"),)
    )
    return registry, output, definition


class ExecutionAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_copied_run_cannot_replay_through_same_registry(self):
        registry, output, definition = runtime()
        engine = PipelineEngine(registry)
        prepared = await engine.prepare(definition, AudioArtifact(b"audio"))
        stale = copy.deepcopy(prepared)
        await engine.dispatch(prepared)
        with self.assertRaisesRegex(ConfigurationError, "stale"):
            await PipelineEngine(registry).dispatch(stale)
        self.assertEqual(output.calls, 1)

    async def test_concurrent_dispatch_has_one_effect(self):
        registry, output, definition = runtime()
        engine = PipelineEngine(registry)
        prepared = await engine.prepare(definition, AudioArtifact(b"audio"))
        results = await asyncio.gather(
            engine.dispatch(prepared), engine.dispatch(prepared), return_exceptions=True
        )
        self.assertEqual(output.calls, 1)
        self.assertEqual(
            sum(isinstance(result, ConfigurationError) for result in results), 1
        )

    async def test_approval_resumes_without_replaying_passive_delivery(self):
        registry, output, definition = runtime()
        action = Output()
        action.adapter_id = "action"
        action.effect = DestinationEffect.EXECUTE
        registry.destinations.add(action)
        definition = replace(
            definition,
            destinations=(*definition.destinations, AdapterRef("action", id="action")),
        )
        engine = PipelineEngine(registry)
        prepared = await engine.prepare(definition, AudioArtifact(b"audio"))
        self.assertEqual((await engine.dispatch(prepared)).status, RunStatus.PARTIAL)
        self.assertEqual(
            (await engine.dispatch(prepared, {"action"})).status, RunStatus.SUCCEEDED
        )
        self.assertEqual((output.calls, action.calls), (1, 1))

    async def test_persistent_claim_rejects_stale_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "history.db")
            await store.initialize()
            registry, output, definition = runtime()
            engine = PipelineEngine(registry, store)
            prepared = await engine.prepare(definition, AudioArtifact(b"audio"))
            other = await store.get_prepared(prepared.run.id)
            results = await asyncio.gather(
                engine.dispatch(prepared),
                PipelineEngine(registry, store).dispatch(other),
                return_exceptions=True,
            )
            self.assertEqual(output.calls, 1)
            self.assertEqual(
                sum(isinstance(result, ConfigurationError) for result in results), 1
            )

    async def test_prepared_changes_invalidate_approval(self):
        registry, output, definition = runtime()
        engine = PipelineEngine(registry)
        prepared = await engine.prepare(definition, AudioArtifact(b"audio"))
        prepared.run.final_text = "changed"
        with self.assertRaisesRegex(ConfigurationError, "changed"):
            await engine.dispatch(prepared)
        prepared.run.final_text = "private words"
        output.effect = DestinationEffect.EXECUTE
        with self.assertRaisesRegex(ConfigurationError, "changed"):
            await engine.dispatch(prepared, {"out"})
        self.assertEqual(output.calls, 0)

    async def test_failed_context_retains_transcript_and_receipt(self):
        class BadContext:
            adapter_id = "context"
            exposure = Exposure.LOCAL

            async def collect(self, config):
                raise RuntimeError("sensitive diagnostic")

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "history.db")
            await store.initialize()
            registry, _, definition = runtime()
            registry.context.add(BadContext())
            definition = replace(definition, context=(AdapterRef("context"),))
            with self.assertRaises(RuntimeError) as caught:
                await PipelineEngine(registry, store).prepare(
                    definition, AudioArtifact(b"audio")
                )
            receipt = await store.get_run_receipt(caught.exception.run.id)
            self.assertEqual(receipt["raw_transcript"], "private words")
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["exposure_events"][-1]["outcome"], "failed")
            self.assertNotIn("sensitive diagnostic", json.dumps(receipt))

    async def test_cancelled_prepare_is_persisted(self):
        started = asyncio.Event()

        class SlowSpeech(Speech):
            async def transcribe(self, audio, config):
                started.set()
                await asyncio.sleep(60)

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "history.db")
            await store.initialize()
            registry, _, definition = runtime()
            registry.speech.values["speech"] = SlowSpeech()
            task = asyncio.create_task(
                PipelineEngine(registry, store).prepare(
                    definition, AudioArtifact(b"audio")
                )
            )
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            (receipt,) = await store.list_run_receipts()
            self.assertEqual(receipt["status"], "cancelled")
            self.assertEqual(receipt["exposure_events"][0]["outcome"], "cancelled")

    async def test_network_delivery_is_recorded(self):
        registry, output, definition = runtime()
        output.exposure = Exposure.NETWORK
        output.effect = DestinationEffect.NETWORK
        engine = PipelineEngine(registry)
        run = await engine.dispatch(
            await engine.prepare(definition, AudioArtifact(b"audio")), {"out"}
        )
        event = run.exposure_events[-1]
        self.assertEqual(
            (event.stage, event.exposure, event.outcome),
            ("destination:out", Exposure.NETWORK, "succeeded"),
        )

    async def test_local_only_rejects_unsandboxed_script(self):
        registry, output, definition = runtime()
        output.effect = DestinationEffect.EXECUTE
        definition = replace(definition, policy=PipelinePolicy(local_only=True))
        with self.assertRaises(PolicyViolation):
            await PipelineEngine(registry).prepare(definition, AudioArtifact(b"audio"))

    async def test_prepare_snapshots_nested_pipeline_settings(self):
        registry, _, definition = runtime()
        definition.transcription.settings["nested"] = {"value": "original"}
        prepared = await PipelineEngine(registry).prepare(
            definition, AudioArtifact(b"audio")
        )
        definition.transcription.settings["nested"]["value"] = "changed"
        self.assertEqual(
            prepared.pipeline.transcription.settings["nested"]["value"], "original"
        )


class BoundaryAuditTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_rejects_string_metadata(self):
        registry = AdapterRegistry()
        output = Output()
        output.effect = "execute"
        with self.assertRaises(ConfigurationError):
            registry.destinations.add(output)
        speech = Speech()
        speech.exposure = "network"
        with self.assertRaises(ConfigurationError):
            registry.speech.add(speech)

    async def test_symlink_swap_does_not_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "allowed"
            outside = root / "outside"
            allowed.mkdir()
            outside.mkdir()
            destination = FileDestination([allowed])
            original = asyncio.to_thread

            async def swap(fn, *args, **kwargs):
                allowed.rmdir()
                allowed.symlink_to(outside, target_is_directory=True)
                return await original(fn, *args, **kwargs)

            with patch("relayai_core.destinations.asyncio.to_thread", swap):
                with self.assertRaises(OSError):
                    await destination.deliver(
                        "blocked",
                        AdapterRef(
                            destination.adapter_id,
                            {"path": str(allowed / "note")},
                            id="file",
                        ),
                        {},
                    )
            self.assertFalse((outside / "note").exists())

    async def test_existing_file_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note"
            path.write_text("keep")
            destination = FileDestination([directory])
            with self.assertRaises(FileExistsError):
                await destination.deliver(
                    "replace",
                    AdapterRef(destination.adapter_id, {"path": str(path)}, id="file"),
                    {},
                )
            self.assertEqual(path.read_text(), "keep")
            await destination.deliver(
                "replace",
                AdapterRef(
                    destination.adapter_id,
                    {"path": str(path), "mode": "overwrite"},
                    id="file",
                ),
                {},
            )
            self.assertEqual(path.read_text(), "replace")

    async def test_cancelled_script_cannot_write_after_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready, marker = root / "ready", root / "after"
            code = f"from pathlib import Path; import time; Path({str(ready)!r}).touch(); time.sleep(.4); Path({str(marker)!r}).touch()"
            destination = ScriptDestination({"job": [sys.executable, "-c", code]})
            task = asyncio.create_task(
                destination.deliver(
                    "",
                    AdapterRef(destination.adapter_id, {"command_id": "job"}, id="job"),
                    {},
                )
            )

            async def wait_ready():
                while not ready.exists():
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_ready(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0.5)
            self.assertFalse(marker.exists())

    async def test_process_output_is_bounded_while_running(self):
        with self.assertRaisesRegex(ProviderError, "size limit"):
            await run_process(
                [
                    sys.executable,
                    "-c",
                    "import sys,time; sys.stdout.write('x'*100000); sys.stdout.flush(); time.sleep(60)",
                ],
                max_output_bytes=1024,
                timeout=3,
            )

    async def test_cancellation_kills_descendant_process(self):
        with tempfile.TemporaryDirectory() as directory:
            ready, marker = Path(directory) / "ready", Path(directory) / "child-effect"
            child = f"import time; from pathlib import Path; Path({str(ready)!r}).touch(); time.sleep(.4); Path({str(marker)!r}).touch()"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
            task = asyncio.create_task(
                run_process([sys.executable, "-c", parent], timeout=3)
            )

            async def wait_ready():
                while not ready.exists():
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_ready(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0.5)
            self.assertFalse(marker.exists())

    async def test_output_file_limit_kills_running_child(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output.json"
            code = f"from pathlib import Path; import time; Path({str(path)!r}).write_bytes(b'x'*100000); time.sleep(60)"
            with self.assertRaisesRegex(ProviderError, "size limit"):
                await run_process(
                    [sys.executable, "-c", code],
                    output_path=path,
                    max_file_bytes=1024,
                    timeout=3,
                )

    def test_http_transport_ignores_inherited_proxies(self):
        with patch.dict(
            os.environ,
            {"http_proxy": "http://192.0.2.1:3128", "no_proxy": ""},
            clear=True,
        ):
            transport = StandardLibraryHTTPTransport()
            self.assertFalse(
                any(
                    getattr(handler, "proxies", None)
                    for handler in transport._opener.handlers
                )
            )

    async def test_database_and_sidecars_are_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "history.db"
            old = os.umask(0o022)
            try:
                store = SQLiteStore(path)
                await store.initialize()
                with store._connect() as connection:
                    connection.execute("CREATE TABLE permissions_test (x)")
                    for suffix in ("", "-wal", "-shm"):
                        file = Path(str(path) + suffix)
                        if file.exists():
                            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            finally:
                os.umask(old)

    async def test_purge_removes_saved_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "history.db")
            await store.initialize()
            registry, _, definition = runtime()
            prepared = await PipelineEngine(registry, store).prepare(
                definition, AudioArtifact(b"audio")
            )
            await store.delete_run_receipts(pipeline_id=definition.id)
            with self.assertRaises(ConfigurationError):
                await store.get_prepared(prepared.run.id)


class ImportAuditTests(unittest.TestCase):
    def test_rejects_malformed_roots_duplicate_keys_and_nonfinite_numbers(self):
        for document in ("[]", "null", "42", '{"id":"a","id":"b"}'):
            with self.subTest(document=document), self.assertRaises(ConfigurationError):
                load_pipeline(document)
        registry, _, definition = runtime()
        base = json.loads(export_pipeline(definition))
        for change in (
            {"schema_version": True},
            {"description": {}},
            {"refinement": {}},
            {"capture": {"activation": []}},
            {"transcription": {"adapter_id": "speech", "credential_id": ""}},
            {
                "transcription": {
                    "adapter_id": "speech",
                    "settings": {"value": float("nan")},
                }
            },
        ):
            with self.subTest(change=change), self.assertRaises(ConfigurationError):
                load_pipeline({**base, **change})

    def test_rejects_credentials_in_url_values(self):
        _, _, definition = runtime()
        base = json.loads(export_pipeline(definition))
        for url in (
            "https://user:secret@example.test/v1",
            "https://example.test/?key=secret",
        ):
            base["transcription"]["settings"] = {"endpoint": url}
            with self.assertRaisesRegex(ConfigurationError, "credential-bearing URL"):
                load_pipeline(base)
