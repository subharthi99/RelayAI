from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from relayai_core.errors import ConfigurationError, ProviderError
from relayai_core.models import AdapterRef, AudioArtifact
from relayai_core.whisper_cpp import WhisperCppModel, WhisperCppSpeechProvider


SUCCESS_SCRIPT = r'''
import json
import pathlib
import sys

args = sys.argv[1:]
output = pathlib.Path(args[args.index("--output-file") + 1] + ".json")
audio = pathlib.Path(args[args.index("--file") + 1])
model = pathlib.Path(args[args.index("--model") + 1])
assert audio.read_bytes() == b"RIFFaudio"
assert model.read_bytes() == b"model-data"
assert "--output-json" in args
assert "--no-prints" in args
assert args[args.index("--language") + 1] == "en"
assert args[args.index("--threads") + 1] == "4"
output.write_text(json.dumps({
    "result": {"language": "en"},
    "transcription": [
        {"text": " hello"},
        {"text": " world"}
    ]
}), encoding="utf-8")
'''


def executable_script(directory: Path, body: str) -> Path:
    script = directory / "whisper-cli"
    script.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    script.chmod(0o700)
    return script


class WhisperCppSpeechProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_allowlisted_binary_and_parses_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = executable_script(root, SUCCESS_SCRIPT)
            model = root / "model with spaces.bin"
            model.write_bytes(b"model-data")
            digest = hashlib.sha256(b"model-data").hexdigest()
            provider = WhisperCppSpeechProvider(
                executable,
                {"small": WhisperCppModel(model, digest)},
                timeout_seconds=5,
            )

            transcript = await provider.transcribe(
                AudioArtifact(b"RIFFaudio"),
                AdapterRef(
                    provider.adapter_id,
                    {"model": "small", "language": "en", "threads": 4},
                ),
            )

            self.assertEqual(transcript.text, "hello world")
            self.assertEqual(transcript.language, "en")
            self.assertEqual(transcript.provider_metadata["model_id"], "small")
            self.assertEqual(transcript.provider_metadata["segment_count"], 2)

    async def test_rejects_unlisted_model_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            executable = executable_script(
                root,
                f"import pathlib\npathlib.Path({str(marker)!r}).touch()\n",
            )
            model = root / "model.bin"
            model.write_bytes(b"model-data")
            provider = WhisperCppSpeechProvider(executable, {"small": model})

            with self.assertRaisesRegex(ConfigurationError, "not allowlisted"):
                await provider.transcribe(
                    AudioArtifact(b"RIFFaudio"),
                    AdapterRef(provider.adapter_id, {"model": "large"}),
                )
            self.assertFalse(marker.exists())

    async def test_rejects_model_with_wrong_checksum_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            executable = executable_script(
                root,
                f"import pathlib\npathlib.Path({str(marker)!r}).touch()\n",
            )
            model = root / "model.bin"
            model.write_bytes(b"model-data")
            provider = WhisperCppSpeechProvider(
                executable,
                {"small": WhisperCppModel(model, "0" * 64)},
            )

            with self.assertRaisesRegex(ConfigurationError, "SHA-256"):
                await provider.transcribe(
                    AudioArtifact(b"RIFFaudio"),
                    AdapterRef(provider.adapter_id, {"model": "small"}),
                )
            self.assertFalse(marker.exists())

    async def test_times_out_and_terminates_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = executable_script(
                root,
                "import time\ntime.sleep(10)\n",
            )
            model = root / "model.bin"
            model.write_bytes(b"model-data")
            provider = WhisperCppSpeechProvider(
                executable,
                {"small": model},
                timeout_seconds=0.05,
            )

            with self.assertRaisesRegex(ProviderError, "timed out"):
                await provider.transcribe(
                    AudioArtifact(b"RIFFaudio"),
                    AdapterRef(provider.adapter_id, {"model": "small"}),
                )

    async def test_reports_bounded_process_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = executable_script(
                root,
                'import sys\nsys.stderr.write("x" * 2000)\nsys.exit(7)\n',
            )
            model = root / "model.bin"
            model.write_bytes(b"model-data")
            provider = WhisperCppSpeechProvider(executable, {"small": model})

            with self.assertRaises(ProviderError) as raised:
                await provider.transcribe(
                    AudioArtifact(b"RIFFaudio"),
                    AdapterRef(provider.adapter_id, {"model": "small"}),
                )
            self.assertIn("exited with 7", str(raised.exception))
            self.assertLessEqual(len(str(raised.exception)), 1050)

    async def test_rejects_unsafe_or_unknown_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = executable_script(root, SUCCESS_SCRIPT)
            model = root / "model.bin"
            model.write_bytes(b"model-data")
            provider = WhisperCppSpeechProvider(executable, {"small": model})

            with self.assertRaisesRegex(ConfigurationError, "language code"):
                await provider.transcribe(
                    AudioArtifact(b"RIFFaudio"),
                    AdapterRef(
                        provider.adapter_id,
                        {"model": "small", "language": "--model"},
                    ),
                )
            with self.assertRaisesRegex(ConfigurationError, "unknown settings"):
                await provider.transcribe(
                    AudioArtifact(b"RIFFaudio"),
                    AdapterRef(
                        provider.adapter_id,
                        {"model": "small", "arguments": ["--help"]},
                    ),
                )

    async def test_rejects_malformed_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = executable_script(
                root,
                'import pathlib, sys\na=sys.argv\np=pathlib.Path(a[a.index("--output-file")+1]+".json")\np.write_text("nope")\n',
            )
            model = root / "model.bin"
            model.write_bytes(b"model-data")
            provider = WhisperCppSpeechProvider(executable, {"small": model})

            with self.assertRaisesRegex(ProviderError, "invalid JSON"):
                await provider.transcribe(
                    AudioArtifact(b"RIFFaudio"),
                    AdapterRef(provider.adapter_id, {"model": "small"}),
                )

    def test_requires_existing_executable_and_valid_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.bin"
            model.write_bytes(b"model-data")
            with self.assertRaisesRegex(ConfigurationError, "does not exist"):
                WhisperCppSpeechProvider(root / "missing", {"small": model})

            executable = executable_script(root, SUCCESS_SCRIPT)
            with self.assertRaisesRegex(ConfigurationError, "64 hexadecimal"):
                WhisperCppSpeechProvider(
                    executable,
                    {"small": WhisperCppModel(model, "bad")},
                )
            with self.assertRaisesRegex(ConfigurationError, "path or"):
                WhisperCppSpeechProvider(
                    executable,
                    {"small": object()},  # type: ignore[dict-item]
                )
            with self.assertRaisesRegex(ConfigurationError, "timeout"):
                WhisperCppSpeechProvider(
                    executable,
                    {"small": model},
                    timeout_seconds=float("inf"),
                )


if __name__ == "__main__":
    unittest.main()
