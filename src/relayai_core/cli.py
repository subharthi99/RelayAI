from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .api import create_server
from .destinations import FileDestination, ResultDestination
from .engine import PipelineEngine
from .errors import ConfigurationError, RelayAIError
from .models import AudioArtifact
from .registry import AdapterRegistry
from .serialization import export_pipeline, load_pipeline
from .storage import SQLiteStore
from .whisper_cpp import WhisperCppModel, WhisperCppSpeechProvider


_LOCAL_AUDIO_TYPES = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
}
_MAX_LOCAL_AUDIO_BYTES = 512 * 1024 * 1024


def _read_pipeline(path: str) -> Any:
    try:
        document = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"cannot read pipeline file: {exc}") from exc
    return load_pipeline(document)


def _write_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _named_values(values: Sequence[str], option: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, configured = value.partition("=")
        if not separator or not name or not configured:
            raise ConfigurationError(f"{option} must use NAME=VALUE")
        if name in result:
            raise ConfigurationError(f"duplicate {option} name: {name}")
        result[name] = configured
    return result


def _read_audio(path_value: str) -> AudioArtifact:
    path = Path(path_value)
    try:
        if not path.is_file():
            raise ConfigurationError(f"audio file does not exist: {path}")
        size = path.stat().st_size
    except OSError as exc:
        raise ConfigurationError(f"cannot inspect audio file: {exc}") from exc
    if size < 1:
        raise ConfigurationError("audio file cannot be empty")
    if size > _MAX_LOCAL_AUDIO_BYTES:
        raise ConfigurationError("audio file exceeds the 512 MiB local limit")
    try:
        media_type = _LOCAL_AUDIO_TYPES[path.suffix.lower()]
    except KeyError as exc:
        raise ConfigurationError(
            "local audio must be FLAC, MP3, OGG, or WAV"
        ) from exc
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(f"cannot read audio file: {exc}") from exc
    return AudioArtifact(content, media_type)


def _pipeline_summary(pipeline: Any) -> dict[str, Any]:
    refinement_adapter = (
        pipeline.refinement.adapter.adapter_id
        if pipeline.refinement.adapter is not None
        else None
    )
    return {
        "schema_version": pipeline.schema_version,
        "id": pipeline.id,
        "name": pipeline.name,
        "description": pipeline.description,
        "capture": {
            "activation": pipeline.capture.activation,
            "source": pipeline.capture.source,
        },
        "transcription": {
            "adapter_id": pipeline.transcription.adapter_id,
            "uses_credential_reference": pipeline.transcription.credential_id is not None,
        },
        "context_adapters": [item.adapter_id for item in pipeline.context],
        "refinement": {
            "enabled": pipeline.refinement.enabled,
            "adapter_id": refinement_adapter,
            "prompt_id": pipeline.refinement.prompt_id,
            "uses_credential_reference": (
                pipeline.refinement.adapter is not None
                and pipeline.refinement.adapter.credential_id is not None
            ),
        },
        "policy": {
            "local_only": pipeline.policy.local_only,
            "confirm_network_destinations": (
                pipeline.policy.confirm_network_destinations
            ),
            "confirm_executable_destinations": (
                pipeline.policy.confirm_executable_destinations
            ),
        },
        "destinations": [
            {"id": item.instance_id, "adapter_id": item.adapter_id}
            for item in pipeline.destinations
        ],
    }


async def _database(args: argparse.Namespace) -> int:
    store = SQLiteStore(args.database)
    await store.initialize()
    if args.database_command == "init":
        _write_json({"database": str(Path(args.database)), "status": "initialized"})
        return 0
    if args.database_command == "import":
        pipeline = _read_pipeline(args.pipeline)
        await store.save_pipeline(pipeline)
        _write_json({"id": pipeline.id, "status": "imported"})
        return 0
    if args.database_command == "list":
        pipelines = await store.list_pipelines()
        _write_json([_pipeline_summary(item) for item in pipelines])
        return 0
    if args.database_command == "export":
        pipeline = await store.get_pipeline(args.pipeline_id)
        if pipeline is None:
            raise ConfigurationError(f"pipeline not found: {args.pipeline_id}")
        document = export_pipeline(pipeline)
        if args.output is None:
            print(document)
        else:
            output = Path(args.output)
            try:
                output.write_text(document + "\n", encoding="utf-8")
            except OSError as exc:
                raise ConfigurationError(f"cannot write pipeline file: {exc}") from exc
            _write_json({"id": pipeline.id, "output": str(output), "status": "exported"})
        return 0
    raise AssertionError(f"unknown database command: {args.database_command}")


def _parse_before(value: str) -> float:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ConfigurationError(
            "--before must be an ISO-8601 timestamp, for example 2026-07-26T00:00:00Z"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


async def _history(args: argparse.Namespace) -> int:
    store = SQLiteStore(args.database)
    await store.initialize()
    if args.history_command == "list":
        receipts = await store.list_run_receipts(
            pipeline_id=args.pipeline_id,
            limit=args.limit,
        )
        _write_json(receipts)
        return 0
    if args.history_command == "show":
        receipt = await store.get_run_receipt(args.run_id)
        if receipt is None:
            raise ConfigurationError(f"run not found: {args.run_id}")
        _write_json(receipt)
        return 0
    if args.history_command == "purge":
        if not args.yes:
            raise ConfigurationError("history purge requires --yes")
        completed_before = _parse_before(args.before) if args.before else None
        deleted = await store.delete_run_receipts(
            pipeline_id=args.pipeline_id,
            completed_before=completed_before,
        )
        _write_json({"deleted": deleted, "status": "purged"})
        return 0
    raise AssertionError(f"unknown history command: {args.history_command}")


async def _run_local(args: argparse.Namespace) -> int:
    model_paths = _named_values(args.model, "--model")
    checksums = _named_values(args.model_sha256, "--model-sha256")
    unknown_checksums = set(checksums) - set(model_paths)
    if unknown_checksums:
        raise ConfigurationError(
            "--model-sha256 references unknown models: "
            f"{sorted(unknown_checksums)}"
        )
    if args.prepare_only and args.approve_destination:
        raise ConfigurationError(
            "--approve-destination cannot be used with --prepare-only"
        )
    models = {
        model_id: WhisperCppModel(Path(path), checksums.get(model_id))
        for model_id, path in model_paths.items()
    }

    registry = AdapterRegistry()
    registry.speech.add(
        WhisperCppSpeechProvider(
            args.whisper_cli,
            models,
            timeout_seconds=args.timeout_seconds,
        )
    )
    registry.destinations.add(ResultDestination())
    if args.allow_file_root:
        registry.destinations.add(FileDestination(args.allow_file_root))

    pipeline = _read_pipeline(args.pipeline)
    audio = _read_audio(args.audio)
    store = SQLiteStore(args.database)
    await store.initialize()
    await store.save_pipeline(pipeline)

    engine = PipelineEngine(registry)
    prepared = await engine.prepare(pipeline, audio)
    if args.prepare_only:
        run = prepared.run
    else:
        run = await engine.dispatch(
            prepared,
            approved_destination_ids=args.approve_destination,
        )
    await store.save_run(run)
    _write_json(asdict(run))
    return 0


def _serve(args: argparse.Namespace) -> int:
    token = os.environ.get(args.token_env)
    if token is None:
        raise ConfigurationError(
            f"local API token is missing from environment variable {args.token_env}"
        )
    store = SQLiteStore(args.database)
    asyncio.run(store.initialize())
    server = create_server(store, token, port=args.port)
    address, port = server.server_address
    _write_json(
        {
            "database": str(Path(args.database)),
            "listen": f"http://{address}:{port}",
            "status": "serving",
        }
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="relayai",
        description="Manage RelayAI pipeline definitions and local receipts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    pipeline = commands.add_parser("pipeline", help="validate and inspect pipeline files")
    pipeline_commands = pipeline.add_subparsers(dest="pipeline_command", required=True)
    validate = pipeline_commands.add_parser("validate", help="validate a pipeline file")
    validate.add_argument("path")
    inspect = pipeline_commands.add_parser("inspect", help="show a safe pipeline summary")
    inspect.add_argument("path")

    database = commands.add_parser("database", help="manage the local pipeline database")
    database.add_argument("--database", required=True)
    database_commands = database.add_subparsers(
        dest="database_command",
        required=True,
    )
    database_commands.add_parser("init", help="initialize the database")
    import_command = database_commands.add_parser("import", help="import a pipeline")
    import_command.add_argument("pipeline")
    database_commands.add_parser("list", help="list stored pipelines")
    export = database_commands.add_parser("export", help="export a stored pipeline")
    export.add_argument("pipeline_id")
    export.add_argument("--output")

    history = commands.add_parser("history", help="inspect or purge run receipts")
    history.add_argument("--database", required=True)
    history_commands = history.add_subparsers(dest="history_command", required=True)
    history_list = history_commands.add_parser("list", help="list run receipts")
    history_list.add_argument("--pipeline-id")
    history_list.add_argument("--limit", type=int, default=50)
    history_show = history_commands.add_parser("show", help="show a run receipt")
    history_show.add_argument("run_id")
    history_purge = history_commands.add_parser("purge", help="delete selected receipts")
    history_purge.add_argument("--pipeline-id")
    history_purge.add_argument("--before")
    history_purge.add_argument("--yes", action="store_true")

    run = commands.add_parser(
        "run",
        help="execute a local whisper.cpp pipeline from an audio file",
    )
    run.add_argument("--pipeline", required=True)
    run.add_argument("--audio", required=True)
    run.add_argument("--database", required=True)
    run.add_argument("--whisper-cli", required=True)
    run.add_argument(
        "--model",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="allowlist a pipeline model name and local model path",
    )
    run.add_argument(
        "--model-sha256",
        action="append",
        default=[],
        metavar="NAME=HEX",
        help="verify an allowlisted model before every execution",
    )
    run.add_argument(
        "--allow-file-root",
        action="append",
        default=[],
        metavar="PATH",
        help="allow builtin.file destinations below this root",
    )
    run.add_argument(
        "--approve-destination",
        action="append",
        default=[],
        metavar="ID",
        help="approve a configured protected destination instance",
    )
    run.add_argument(
        "--prepare-only",
        action="store_true",
        help="transcribe and refine without delivering to destinations",
    )
    run.add_argument("--timeout-seconds", type=float, default=180)

    serve = commands.add_parser("serve", help="start the authenticated local read API")
    serve.add_argument("--database", required=True)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--token-env", default="RELAYAI_API_TOKEN")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "pipeline":
            pipeline = _read_pipeline(args.path)
            if args.pipeline_command == "validate":
                _write_json(
                    {
                        "id": pipeline.id,
                        "path": str(Path(args.path)),
                        "schema_version": pipeline.schema_version,
                        "status": "valid",
                    }
                )
            else:
                _write_json(_pipeline_summary(pipeline))
            return 0
        if args.command == "database":
            return asyncio.run(_database(args))
        if args.command == "history":
            return asyncio.run(_history(args))
        if args.command == "run":
            return asyncio.run(_run_local(args))
        if args.command == "serve":
            return _serve(args)
        parser.error(f"unknown command: {args.command}")
    except (RelayAIError, OSError) as exc:
        print(f"relayai: error: {exc}", file=sys.stderr)
        return 2
    return 1
