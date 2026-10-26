from __future__ import annotations

import asyncio
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from relayai_core import (
    AdapterRef,
    Exposure,
    OpenAICompatibleRefinementProvider,
    ProviderError,
)
from relayai_core.models import TranscriptArtifact
from relayai_core.openai_compatible import StandardLibraryHTTPTransport


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.paths = []
        paths = self.paths

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                paths.append(self.path)
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if self.path == "/redirect":
                    self.send_response(307)
                    self.send_header("Location", "/unapproved")
                    self.end_headers()
                else:
                    body = json.dumps(
                        {"choices": [{"message": {"content": "refined"}}]}
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def test_local_request_bypasses_invalid_external_proxy(self):
        with patch.dict(
            os.environ, {"http_proxy": "http://192.0.2.1:1", "no_proxy": ""}, clear=True
        ):
            provider = OpenAICompatibleRefinementProvider(
                {"local": self.url + "/v1"},
                {"polish": "polish"},
                exposure=Exposure.LOCAL,
                require_credential=False,
            )
            result = asyncio.run(
                provider.refine(
                    TranscriptArtifact("raw"),
                    (),
                    AdapterRef(
                        provider.adapter_id, {"endpoint_id": "local", "model": "test"}
                    ),
                    "polish",
                )
            )
        self.assertEqual(result, "refined")
        self.assertEqual(self.paths, ["/v1/chat/completions"])

    def test_provider_redirect_never_reaches_other_endpoint(self):
        transport = StandardLibraryHTTPTransport()
        with self.assertRaises(ProviderError):
            asyncio.run(
                transport.post_json(self.url + "/redirect", {}, {"text": "private"}, 3)
            )
        self.assertEqual(self.paths, ["/redirect"])

    def test_webhook_redirect_never_reaches_other_endpoint(self):
        transport = StandardLibraryHTTPTransport()
        with self.assertRaises(ProviderError):
            asyncio.run(
                transport.post_webhook(self.url + "/redirect", b"private", 3, "id")
            )
        self.assertEqual(self.paths, ["/redirect"])
