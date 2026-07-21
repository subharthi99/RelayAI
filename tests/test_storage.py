from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from relayai_core.models import (
    AdapterRef,
    PipelineDefinition,
    PipelineRun,
    RunStatus,
)
from relayai_core.storage import SQLiteStore


class SQLiteStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_and_run_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "relayai.sqlite3")
            await store.initialize()
            pipeline = PipelineDefinition(
                id="private",
                name="Private",
                transcription=AdapterRef("local.whisper"),
                destinations=(
                    AdapterRef("platform.focused-field", id="cursor"),
                ),
            )
            await store.save_pipeline(pipeline)
            loaded = await store.get_pipeline("private")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.name, "Private")
            self.assertEqual(len(await store.list_pipelines()), 1)

            run = PipelineRun(pipeline_id="private")
            run.raw_transcript = "hello"
            run.final_text = "hello"
            run.finish(RunStatus.SUCCEEDED)
            await store.save_run(run)
            receipt = await store.get_run_receipt(run.id)

            self.assertIsNotNone(receipt)
            self.assertEqual(receipt["status"], "succeeded")
            self.assertEqual(receipt["raw_transcript"], "hello")


if __name__ == "__main__":
    unittest.main()
