from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from relayai_core.destinations import FileDestination, ScriptDestination
from relayai_core.errors import ConfigurationError
from relayai_core.models import AdapterRef


class DestinationTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_destination_writes_inside_allowlisted_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "note.txt"
            destination = FileDestination([directory])
            receipt = await destination.deliver(
                "hello",
                AdapterRef(
                    destination.adapter_id,
                    {"path": str(target)},
                    id="note",
                ),
                {},
            )
            self.assertEqual(target.read_text(), "hello")
            self.assertEqual(receipt.status, "succeeded")

    async def test_file_destination_rejects_path_outside_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as allowed:
            with tempfile.TemporaryDirectory() as outside:
                destination = FileDestination([allowed])
                with self.assertRaisesRegex(ConfigurationError, "outside"):
                    await destination.deliver(
                        "blocked",
                        AdapterRef(
                            destination.adapter_id,
                            {"path": str(Path(outside) / "note.txt")},
                            id="note",
                        ),
                        {},
                    )

    async def test_script_uses_allowlisted_argv_and_stdin(self) -> None:
        destination = ScriptDestination({"uppercase": ("/usr/bin/tr", "a-z", "A-Z")})
        receipt = await destination.deliver(
            "hello",
            AdapterRef(
                destination.adapter_id,
                {"command_id": "uppercase"},
                id="transform",
            ),
            {},
        )
        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(receipt.metadata["stdout_bytes"], 5)

    async def test_script_rejects_non_allowlisted_command(self) -> None:
        destination = ScriptDestination({"known": ("/usr/bin/true",)})
        with self.assertRaisesRegex(ConfigurationError, "not allowlisted"):
            await destination.deliver(
                "ignored",
                AdapterRef(
                    destination.adapter_id,
                    {"command_id": "unknown"},
                    id="script",
                ),
                {},
            )
