from __future__ import annotations

import asyncio
import json
import os
import stat
from uuid import uuid4
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .processes import run_process, validate_timeout
from .openai_compatible import StandardLibraryHTTPTransport
from .models import (
    AdapterRef,
    DestinationEffect,
    DestinationReceipt,
    Exposure,
)


def _required_setting(config: AdapterRef, name: str) -> str:
    value = config.settings.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigurationError(
            f"destination '{config.instance_id}' requires string setting '{name}'"
        )
    return value


class ResultDestination:
    """Leaves final text on the run receipt for a calling host to consume."""

    adapter_id = "builtin.result"
    exposure = Exposure.LOCAL
    effect = DestinationEffect.PASSIVE

    def configuration_fingerprint(self):
        return "builtin.result/v1"

    async def deliver(
        self, text: str, config: AdapterRef, run_metadata: dict[str, Any]
    ) -> DestinationReceipt:
        if config.settings:
            raise ConfigurationError("builtin.result does not accept settings")
        return DestinationReceipt(
            destination_id=config.instance_id,
            adapter_id=self.adapter_id,
            status="succeeded",
            effect=self.effect,
            metadata={"character_count": len(text)},
        )


class FileDestination:
    adapter_id = "builtin.file"
    exposure = Exposure.LOCAL
    effect = DestinationEffect.LOCAL_WRITE

    def __init__(self, allowed_roots: Sequence[str | Path]) -> None:
        self._allowed_roots = tuple(Path(root).resolve() for root in allowed_roots)
        self._root_aliases = tuple(
            Path(os.path.abspath(Path(root).expanduser())) for root in allowed_roots
        )
        if not self._allowed_roots:
            raise ConfigurationError("file destination requires an allowlisted root")

    def configuration_fingerprint(self):
        return [str(root) for root in self._allowed_roots]

    async def deliver(
        self, text: str, config: AdapterRef, run_metadata: dict[str, Any]
    ) -> DestinationReceipt:
        if set(config.settings) - {"path", "mode"}:
            raise ConfigurationError("unknown file destination settings")
        target = Path(
            os.path.abspath(Path(_required_setting(config, "path")).expanduser())
        )
        match = next(
            (
                (root, target.relative_to(alias))
                for root, original in zip(self._allowed_roots, self._root_aliases)
                for alias in (root, original)
                if target.is_relative_to(alias)
            ),
            None,
        )
        if match is None:
            raise ConfigurationError("file target is outside the allowlisted roots")
        root, relative = match
        mode = config.settings.get("mode", "create")
        if mode not in {"create", "overwrite", "append"}:
            raise ConfigurationError("file mode must be create, overwrite, or append")

        def write() -> None:
            if os.name != "posix":
                raise ConfigurationError(
                    "secure file delivery currently requires POSIX"
                )
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            directory = os.open("/", flags)
            temporary = None
            try:
                parts = (*root.parts[1:], *relative.parts[:-1])
                for index, part in enumerate(parts):
                    try:
                        child = os.open(part, flags, dir_fd=directory)
                    except FileNotFoundError:
                        if index < len(root.parts) - 1:
                            raise ConfigurationError("allowlisted file root must exist")
                        os.mkdir(part, 0o700, dir_fd=directory)
                        child = os.open(part, flags, dir_fd=directory)
                    os.close(directory)
                    directory = child
                name = relative.name
                if not name:
                    raise ConfigurationError("file destination requires a file name")
                if mode in {"create", "append"}:
                    fd = os.open(
                        name,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_NOFOLLOW
                        | os.O_NONBLOCK
                        | (os.O_EXCL if mode == "create" else os.O_APPEND),
                        0o600,
                        dir_fd=directory,
                    )
                else:
                    temporary = f".relayai-{uuid4().hex}"
                    fd = os.open(
                        temporary,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=directory,
                    )
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    info = os.fstat(output.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ConfigurationError(
                            "target must be a regular file without hardlinks"
                        )
                    output.write(text)
                    output.flush()
                    os.fsync(output.fileno())
                if temporary is not None:
                    os.replace(
                        temporary, name, src_dir_fd=directory, dst_dir_fd=directory
                    )
                    temporary = None
            finally:
                if temporary is not None:
                    os.unlink(temporary, dir_fd=directory)
                os.close(directory)

        task = asyncio.create_task(asyncio.to_thread(write))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # A filesystem syscall already in progress cannot be revoked. Wait for
            # it to settle so no worker continues writing after cancellation returns.
            await task
            raise
        return DestinationReceipt(
            destination_id=config.instance_id,
            adapter_id=self.adapter_id,
            status="succeeded",
            effect=self.effect,
            metadata={"path": str(target)},
        )


class WebhookDestination:
    adapter_id = "builtin.webhook"
    exposure = Exposure.NETWORK
    effect = DestinationEffect.NETWORK

    def __init__(
        self, endpoints: Mapping[str, str], timeout_seconds: float = 10
    ) -> None:
        from urllib.parse import urlsplit

        validate_timeout(timeout_seconds)
        for url in endpoints.values():
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ConfigurationError(
                    "webhook endpoints require HTTPS without credentials, queries or fragments"
                )
        self._endpoints = dict(endpoints)
        self._timeout_seconds = timeout_seconds
        self._transport = StandardLibraryHTTPTransport()

    def configuration_fingerprint(self):
        return self._endpoints

    async def deliver(
        self, text: str, config: AdapterRef, run_metadata: dict[str, Any]
    ) -> DestinationReceipt:
        endpoint_id = _required_setting(config, "endpoint_id")
        if set(config.settings) != {"endpoint_id"}:
            raise ConfigurationError("unknown webhook destination settings")
        try:
            endpoint = self._endpoints[endpoint_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"webhook endpoint '{endpoint_id}' is not allowlisted"
            ) from exc
        payload = json.dumps({"text": text, **run_metadata}).encode("utf-8")

        status_code = await self._transport.post_webhook(
            endpoint,
            payload,
            self._timeout_seconds,
            run_metadata.get("idempotency_key", ""),
        )
        return DestinationReceipt(
            destination_id=config.instance_id,
            adapter_id=self.adapter_id,
            status="succeeded",
            effect=self.effect,
            metadata={"endpoint_id": endpoint_id, "status_code": status_code},
        )


class ScriptDestination:
    adapter_id = "builtin.script"
    exposure = Exposure.LOCAL
    effect = DestinationEffect.EXECUTE

    def __init__(
        self,
        commands: Mapping[str, Sequence[str]],
        timeout_seconds: float = 30,
        max_output_bytes: int = 1024 * 1024,
    ) -> None:
        self._commands = {key: tuple(value) for key, value in commands.items()}
        self._timeout_seconds = timeout_seconds
        validate_timeout(timeout_seconds)
        self._max_output_bytes = max_output_bytes
        if any(not command for command in self._commands.values()):
            raise ConfigurationError("allowlisted commands cannot be empty")
        if any(
            not Path(command[0]).is_absolute() for command in self._commands.values()
        ):
            raise ConfigurationError("script executable paths must be absolute")

    def configuration_fingerprint(self):
        return self._commands

    async def deliver(
        self, text: str, config: AdapterRef, run_metadata: dict[str, Any]
    ) -> DestinationReceipt:
        command_id = _required_setting(config, "command_id")
        if set(config.settings) != {"command_id"}:
            raise ConfigurationError("unknown script destination settings")
        try:
            argv = self._commands[command_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"script command '{command_id}' is not allowlisted"
            ) from exc

        returncode, stdout, stderr = await run_process(
            argv,
            input_bytes=text.encode("utf-8"),
            timeout=self._timeout_seconds,
            max_output_bytes=self._max_output_bytes,
        )
        if returncode != 0:
            raise RuntimeError(
                f"allowlisted command '{command_id}' exited with " f"{returncode}"
            )
        return DestinationReceipt(
            destination_id=config.instance_id,
            adapter_id=self.adapter_id,
            status="succeeded",
            effect=self.effect,
            metadata={
                "command_id": command_id,
                "stdout_bytes": len(stdout),
            },
        )
