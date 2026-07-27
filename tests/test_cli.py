from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from relayai_core.cli import main


EXAMPLE = Path(__file__).parents[1] / "examples" / "private-dictation.pipeline.json"


def invoke(*args: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = main(args)
    return result, stdout.getvalue(), stderr.getvalue()


class CLITests(unittest.TestCase):
    def test_validate_and_inspect_pipeline(self) -> None:
        status, output, error = invoke("pipeline", "validate", str(EXAMPLE))
        self.assertEqual(status, 0)
        self.assertEqual(error, "")
        self.assertEqual(json.loads(output)["status"], "valid")

        status, output, error = invoke("pipeline", "inspect", str(EXAMPLE))
        summary = json.loads(output)
        self.assertEqual(status, 0)
        self.assertEqual(error, "")
        self.assertTrue(summary["policy"]["local_only"])
        self.assertEqual(summary["destinations"][0]["id"], "cursor")

    def test_database_import_list_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "relayai.sqlite3")
            exported = Path(directory) / "exported.pipeline.json"

            status, _, error = invoke(
                "database",
                "--database",
                database,
                "import",
                str(EXAMPLE),
            )
            self.assertEqual(status, 0)
            self.assertEqual(error, "")

            status, output, _ = invoke(
                "database",
                "--database",
                database,
                "list",
            )
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output)[0]["id"], "private-dictation")

            status, output, _ = invoke(
                "database",
                "--database",
                database,
                "export",
                "private-dictation",
                "--output",
                str(exported),
            )
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output)["status"], "exported")
            self.assertEqual(
                json.loads(exported.read_text())["id"],
                "private-dictation",
            )

    def test_invalid_pipeline_returns_user_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text('{"schema_version": 999}', encoding="utf-8")
            status, output, error = invoke(
                "pipeline",
                "validate",
                str(invalid),
            )
            self.assertEqual(status, 2)
            self.assertEqual(output, "")
            self.assertIn("unsupported schema_version", error)

    def test_history_purge_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "relayai.sqlite3")
            status, _, error = invoke(
                "history",
                "--database",
                database,
                "purge",
                "--pipeline-id",
                "private",
            )
            self.assertEqual(status, 2)
            self.assertIn("requires --yes", error)


if __name__ == "__main__":
    unittest.main()
