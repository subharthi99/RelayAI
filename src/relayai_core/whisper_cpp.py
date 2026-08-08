from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, ProviderError
from .models import AdapterRef, AudioArtifact, Exposure, TranscriptArtifact


_SUPPORTED_MEDIA_TYPES = {
    "audio/flac": ".flac",
    "audio/mp3": ".mp3",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
}
_ALLOWED_SETTINGS = {
    "model",
    "language",
    "translate",
    "threads",
    "temperature",
    "no_gpu",
}


@dataclass(frozen=True, slots=True)
class WhisperCppModel:
    path: Path
    sha256: str | None = None


class WhisperCppSpeechProvider:
    """Runs an allowlisted whisper.cpp CLI and parses its JSON output."""

    adapter_id = "local.whisper_cpp"
    exposure = Exposure.LOCAL

    def __init__(
        self,
        executable: str | Path,
        models: Mapping[str, str | Path | WhisperCppModel],
        *,
        timeout_seconds: float = 180,
        max_audio_bytes: int = 512 * 1024 * 1024,
        max_output_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        executable_path = Path(executable).expanduser().resolve()
        if not executable_path.is_file():
            raise ConfigurationError(
                f"whisper.cpp executable does not exist: {executable_path}"
            )
        if not os.access(executable_path, os.X_OK):
            raise ConfigurationError(
                f"whisper.cpp executable is not executable: {executable_path}"
            )
        if not models:
            raise ConfigurationError("whisper.cpp requires an allowlisted model")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ConfigurationError("timeout_seconds must be positive")
        if (
            isinstance(max_audio_bytes, bool)
            or not isinstance(max_audio_bytes, int)
            or isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or max_audio_bytes < 1
            or max_output_bytes < 1
        ):
            raise ConfigurationError("audio and output size limits must be positive")

        normalized_models: dict[str, WhisperCppModel] = {}
        for model_id, configured in models.items():
            if not isinstance(model_id, str) or not model_id:
                raise ConfigurationError("model IDs must be non-empty strings")
            if isinstance(configured, WhisperCppModel):
                model = configured
            elif isinstance(configured, (str, Path)):
                model = WhisperCppModel(Path(configured))
            else:
                raise ConfigurationError(
                    f"model '{model_id}' must be a path or WhisperCppModel"
                )
            if not isinstance(model.path, Path):
                raise ConfigurationError(f"model '{model_id}' path must be a Path")
            digest = model.sha256.lower() if model.sha256 is not None else None
            if digest is not None and (
                len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ConfigurationError(
                    f"model '{model_id}' SHA-256 must contain 64 hexadecimal characters"
                )
            normalized_models[model_id] = WhisperCppModel(
                model.path.expanduser().resolve(), digest
            )

        self._executable = executable_path
        self._models = normalized_models
        self._timeout_seconds = timeout_seconds
        self._max_audio_bytes = max_audio_bytes
        self._max_output_bytes = max_output_bytes

    async def transcribe(
        self, audio: AudioArtifact, config: AdapterRef
    ) -> TranscriptArtifact:
        _reject_unknown_settings(config.settings)
        if not audio.content:
            raise ConfigurationError("audio content cannot be empty")
        if len(audio.content) > self._max_audio_bytes:
            raise ConfigurationError("audio exceeds the configured local size limit")
        try:
            suffix = _SUPPORTED_MEDIA_TYPES[audio.media_type]
        except KeyError as exc:
            raise ConfigurationError(
                f"whisper.cpp does not support media type: {audio.media_type}"
            ) from exc

        model_id = _required_string(config.settings, "model")
        try:
            model = self._models[model_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"whisper.cpp model '{model_id}' is not allowlisted"
            ) from exc
        await self._verify_model(model_id, model)

        argv = self._arguments(config, model)
        with tempfile.TemporaryDirectory(prefix="relayai-whisper-") as directory:
            temp_root = Path(directory)
            audio_path = temp_root / f"input{suffix}"
            output_prefix = temp_root / "transcript"
            stderr_path = temp_root / "stderr.log"
            await asyncio.to_thread(audio_path.write_bytes, audio.content)

            command = [
                str(self._executable),
                *argv,
                "--file",
                str(audio_path),
                "--output-json",
                "--output-file",
                str(output_prefix),
                "--no-prints",
            ]
            with stderr_path.open("wb") as stderr_file:
                try:
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=stderr_file,
                    )
                except OSError as exc:
                    raise ProviderError(
                        f"could not start whisper.cpp: {type(exc).__name__}"
                    ) from exc
                try:
                    await asyncio.wait_for(
                        process.wait(), timeout=self._timeout_seconds
                    )
                except TimeoutError as exc:
                    process.kill()
                    await process.wait()
                    raise ProviderError("whisper.cpp timed out") from exc
                except asyncio.CancelledError:
                    process.kill()
                    await process.wait()
                    raise

            if process.returncode != 0:
                detail = await asyncio.to_thread(_read_tail, stderr_path, 1000)
                suffix_message = f": {detail}" if detail else ""
                raise ProviderError(
                    f"whisper.cpp exited with {process.returncode}{suffix_message}"
                )

            output_path = output_prefix.with_suffix(".json")
            document = await asyncio.to_thread(
                _read_limited, output_path, self._max_output_bytes
            )
            return _parse_transcript(document, model_id)

    async def _verify_model(
        self, model_id: str, model: WhisperCppModel
    ) -> None:
        if not model.path.is_file():
            raise ConfigurationError(
                f"whisper.cpp model does not exist: {model.path}"
            )
        if model.sha256 is not None:
            digest = await asyncio.to_thread(_sha256_file, model.path)
            if digest != model.sha256:
                raise ConfigurationError(
                    f"whisper.cpp model '{model_id}' failed SHA-256 verification"
                )

    def _arguments(
        self, config: AdapterRef, model: WhisperCppModel
    ) -> list[str]:
        arguments = ["--model", str(model.path)]
        language = config.settings.get("language")
        if language is not None:
            if not isinstance(language, str) or not re.fullmatch(
                r"(?:auto|[A-Za-z]{2,3}(?:-[A-Za-z]{2,8})?)", language
            ):
                raise ConfigurationError(
                    "language must be 'auto' or a language code"
                )
            arguments.extend(["--language", language])
        translate = config.settings.get("translate", False)
        if not isinstance(translate, bool):
            raise ConfigurationError("translate must be a boolean")
        if translate:
            arguments.append("--translate")
        threads = config.settings.get("threads")
        if threads is not None:
            if isinstance(threads, bool) or not isinstance(threads, int):
                raise ConfigurationError("threads must be an integer")
            if threads < 1 or threads > 128:
                raise ConfigurationError("threads must be between 1 and 128")
            arguments.extend(["--threads", str(threads)])
        temperature = config.settings.get("temperature")
        if temperature is not None:
            if isinstance(temperature, bool) or not isinstance(
                temperature, (int, float)
            ):
                raise ConfigurationError("temperature must be a number")
            if not 0 <= float(temperature) <= 1:
                raise ConfigurationError("temperature must be between 0 and 1")
            arguments.extend(["--temperature", str(float(temperature))])
        no_gpu = config.settings.get("no_gpu", False)
        if not isinstance(no_gpu, bool):
            raise ConfigurationError("no_gpu must be a boolean")
        if no_gpu:
            arguments.append("--no-gpu")
        return arguments


def _required_string(settings: Mapping[str, Any], name: str) -> str:
    value = settings.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"setting '{name}' must be a non-empty string")
    return value


def _reject_unknown_settings(settings: Mapping[str, Any]) -> None:
    unknown = set(settings) - _ALLOWED_SETTINGS
    if unknown:
        raise ConfigurationError(
            f"local.whisper_cpp contains unknown settings: {sorted(unknown)}"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_limited(path: Path, maximum: int) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ProviderError("whisper.cpp did not produce JSON output") from exc
    if size > maximum:
        raise ProviderError("whisper.cpp JSON output exceeded the size limit")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ProviderError("could not read whisper.cpp JSON output") from exc


def _read_tail(path: Path, maximum: int) -> str:
    try:
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(max(0, size - maximum))
            return file.read(maximum).decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def _parse_transcript(document: bytes, model_id: str) -> TranscriptArtifact:
    try:
        payload = json.loads(document)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderError("whisper.cpp returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ProviderError("whisper.cpp JSON output must be an object")
    segments = payload.get("transcription")
    if not isinstance(segments, list):
        raise ProviderError("whisper.cpp JSON output has no transcription array")
    texts: list[str] = []
    for segment in segments:
        if not isinstance(segment, Mapping) or not isinstance(
            segment.get("text"), str
        ):
            raise ProviderError("whisper.cpp returned a malformed segment")
        texts.append(segment["text"])
    text = "".join(texts).strip()
    if not text:
        raise ProviderError("whisper.cpp produced an empty transcript")
    result = payload.get("result", {})
    language = result.get("language") if isinstance(result, Mapping) else None
    if language is not None and not isinstance(language, str):
        raise ProviderError("whisper.cpp result language must be a string")
    return TranscriptArtifact(
        text=text,
        language=language,
        provider_metadata={"model_id": model_id, "segment_count": len(segments)},
    )
