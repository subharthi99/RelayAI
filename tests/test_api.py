from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from relayai_core.api import create_server
from relayai_core.errors import ConfigurationError
from relayai_core.models import AdapterRef, PipelineDefinition, PipelineRun, RunStatus
from relayai_core.storage import SQLiteStore


TOKEN = "test-token-that-is-at-least-thirty-two-characters"


class LocalAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(
            Path(self.temporary_directory.name) / "relayai.sqlite3"
        )
        asyncio.run(self.store.initialize())
        pipeline = PipelineDefinition(
            id="private",
            name="Private",
            transcription=AdapterRef("local.speech"),
            destinations=(AdapterRef("platform.cursor", id="cursor"),),
        )
        asyncio.run(self.store.save_pipeline(pipeline))
        run = PipelineRun(pipeline_id="private")
        run.raw_transcript = "sensitive transcript"
        run.final_text = "sensitive transcript"
        run.finish(RunStatus.SUCCEEDED)
        asyncio.run(self.store.save_run(run))
        self.run_id = run.id

        self.server = create_server(self.store, TOKEN, port=0)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def request(self, path: str, *, authenticated: bool = True):
        headers = {"Authorization": f"Bearer {TOKEN}"} if authenticated else {}
        request = urllib.request.Request(self.base_url + path, headers=headers)
        return urllib.request.urlopen(request, timeout=3)

    def test_health_is_available_without_exposing_state(self) -> None:
        with self.request("/health", authenticated=False) as response:
            payload = json.load(response)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_v1_routes_require_bearer_authentication(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/v1/pipelines", authenticated=False)
        self.assertEqual(raised.exception.code, 401)

    def test_pipeline_list_and_detail(self) -> None:
        with self.request("/v1/pipelines") as response:
            pipelines = json.load(response)
        self.assertEqual(pipelines[0]["id"], "private")

        with self.request("/v1/pipelines/private") as response:
            pipeline = json.load(response)
        self.assertEqual(pipeline["destinations"][0]["id"], "cursor")

    def test_run_list_is_redacted_but_detail_contains_receipt(self) -> None:
        with self.request("/v1/runs?pipeline_id=private&limit=10") as response:
            runs = json.load(response)
        self.assertNotIn("raw_transcript", runs[0])
        self.assertEqual(runs[0]["id"], self.run_id)

        with self.request(f"/v1/runs/{self.run_id}") as response:
            receipt = json.load(response)
        self.assertEqual(receipt["raw_transcript"], "sensitive transcript")

    def test_server_rejects_unsafe_binding_and_short_token(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "127.0.0.1"):
            create_server(self.store, TOKEN, host="0.0.0.0", port=0)
        with self.assertRaisesRegex(ConfigurationError, "at least 32"):
            create_server(self.store, "short", port=0)


if __name__ == "__main__":
    unittest.main()
