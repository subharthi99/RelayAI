from __future__ import annotations

import sqlite3
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
    async def test_connection_context_closes_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "relayai.sqlite3")
            with store._connect() as connection:
                connection.execute("SELECT 1")

            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
                connection.execute("SELECT 1")

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

            listed = await store.list_run_receipts(
                pipeline_id="private",
                limit=10,
            )
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["id"], run.id)

            deleted = await store.delete_run_receipts(pipeline_id="private")
            self.assertEqual(deleted, 1)
            self.assertEqual(await store.list_run_receipts(limit=10), ())

            self.assertTrue(await store.delete_pipeline("private"))
            self.assertFalse(await store.delete_pipeline("private"))

    async def test_receipt_queries_require_safe_limits_and_delete_filters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "relayai.sqlite3")
            await store.initialize()

            with self.assertRaisesRegex(Exception, "between 1 and 1000"):
                await store.list_run_receipts(limit=0)
            with self.assertRaisesRegex(Exception, "requires"):
                await store.delete_run_receipts()


if __name__ == "__main__":
    unittest.main()
