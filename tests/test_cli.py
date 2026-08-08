from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from relayai_core.cli import main


EXAMPLE = Path(__file__).parents[1] / "examples" / "private-dictation.pipeline.json"
LOCAL_EXAMPLE = Path(__file__).parents[1] / "examples" / "local-audio.pipeline.json"


def invoke(*args: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = main(args)
    return result, stdout.getvalue(), stderr.getvalue()


class CLITests(unittest.TestCase):
    def _local_runtime(self, root: Path) -> tuple[Path, Path, Path]:
        executable = root / "whisper-cli"
        executable.write_text(
            f"""#!{sys.executable}
import json
import pathlib
import sys
args = sys.argv[1:]
output = pathlib.Path(args[args.index('--output-file') + 1] + '.json')
output.write_text(json.dumps({{
    'result': {{'language': 'en'}},
    'transcription': [{{'text': 'local execution works'}}]
}}), encoding='utf-8')
""",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        model = root / "ggml-small.bin"
        model.write_bytes(b"fake-model")
        audio = root / "sample.wav"
        audio.write_bytes(b"RIFFaudio")
        return executable, model, audio

    def test_run_executes_local_pipeline_and_persists_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable, model, audio = self._local_runtime(root)
            database = root / "relayai.sqlite3"

            status, output, error = invoke(
                "run",
                "--pipeline",
                str(LOCAL_EXAMPLE),
                "--audio",
                str(audio),
                "--database",
                str(database),
                "--whisper-cli",
                str(executable),
                "--model",
                f"small={model}",
            )

            self.assertEqual(status, 0, error)
            self.assertEqual(error, "")
            receipt = json.loads(output)
            self.assertEqual(receipt["status"], "succeeded")
            self.assertEqual(receipt["raw_transcript"], "local execution works")
            self.assertEqual(receipt["final_text"], "local execution works")
            self.assertEqual(receipt["destinations"][0]["status"], "succeeded")

            status, output, error = invoke(
                "history",
                "--database",
                str(database),
                "list",
                "--pipeline-id",
                "local-audio",
            )
            self.assertEqual(status, 0, error)
            history = json.loads(output)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["id"], receipt["id"])

    def test_run_prepare_only_persists_ready_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable, model, audio = self._local_runtime(root)

            status, output, error = invoke(
                "run",
                "--pipeline",
                str(LOCAL_EXAMPLE),
                "--audio",
                str(audio),
                "--database",
                str(root / "relayai.sqlite3"),
                "--whisper-cli",
                str(executable),
                "--model",
                f"small={model}",
                "--prepare-only",
            )

            self.assertEqual(status, 0, error)
            receipt = json.loads(output)
            self.assertEqual(receipt["status"], "ready")
            self.assertEqual(receipt["destinations"], [])

    def test_run_rejects_unknown_checksum_and_prepare_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable, model, audio = self._local_runtime(root)
            common = (
                "run",
                "--pipeline",
                str(LOCAL_EXAMPLE),
                "--audio",
                str(audio),
                "--database",
                str(root / "relayai.sqlite3"),
                "--whisper-cli",
                str(executable),
                "--model",
                f"small={model}",
            )

            status, _, error = invoke(
                *common,
                "--model-sha256",
                f"large={'0' * 64}",
            )
            self.assertEqual(status, 2)
            self.assertIn("unknown models", error)

            status, _, error = invoke(
                *common,
                "--prepare-only",
                "--approve-destination",
                "result",
            )
            self.assertEqual(status, 2)
            self.assertIn("cannot be used", error)

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
