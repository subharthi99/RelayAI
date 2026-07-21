from __future__ import annotations

import asyncio
import json
import subprocess
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
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


class FileDestination:
    adapter_id = "builtin.file"
    exposure = Exposure.LOCAL
    effect = DestinationEffect.LOCAL_WRITE

    def __init__(self, allowed_roots: Sequence[str | Path]) -> None:
        self._allowed_roots = tuple(Path(root).resolve() for root in allowed_roots)
        if not self._allowed_roots:
            raise ConfigurationError("file destination requires an allowlisted root")

    async def deliver(
        self, text: str, config: AdapterRef, run_metadata: dict[str, Any]
    ) -> DestinationReceipt:
        target = Path(_required_setting(config, "path")).expanduser().resolve()
        if not any(target.is_relative_to(root) for root in self._allowed_roots):
            raise ConfigurationError("file target is outside the allowlisted roots")
        mode = config.settings.get("mode", "overwrite")
        if mode not in {"overwrite", "append"}:
            raise ConfigurationError("file mode must be 'overwrite' or 'append'")

        def write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a" if mode == "append" else "w", encoding="utf-8") as file:
                file.write(text)

        await asyncio.to_thread(write)
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

    def __init__(self, endpoints: Mapping[str, str], timeout_seconds: float = 10) -> None:
        self._endpoints = dict(endpoints)
        self._timeout_seconds = timeout_seconds

    async def deliver(
        self, text: str, config: AdapterRef, run_metadata: dict[str, Any]
    ) -> DestinationReceipt:
        endpoint_id = _required_setting(config, "endpoint_id")
        try:
            endpoint = self._endpoints[endpoint_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"webhook endpoint '{endpoint_id}' is not allowlisted"
            ) from exc
        payload = json.dumps({"text": text, **run_metadata}).encode("utf-8")

        def send() -> int:
            request = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return response.status

        status_code = await asyncio.to_thread(send)
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
    ) -> None:
        self._commands = {key: tuple(value) for key, value in commands.items()}
        self._timeout_seconds = timeout_seconds
        if any(not command for command in self._commands.values()):
            raise ConfigurationError("allowlisted commands cannot be empty")

    async def deliver(
        self, text: str, config: AdapterRef, run_metadata: dict[str, Any]
    ) -> DestinationReceipt:
        command_id = _required_setting(config, "command_id")
        try:
            argv = self._commands[command_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"script command '{command_id}' is not allowlisted"
            ) from exc

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(text.encode("utf-8")),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace")[-500:]
            raise RuntimeError(
                f"allowlisted command '{command_id}' exited with "
                f"{process.returncode}: {message}"
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
