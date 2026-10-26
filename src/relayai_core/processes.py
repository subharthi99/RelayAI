"""Bounded subprocess I/O with cancellation and process-group cleanup."""

from __future__ import annotations

import asyncio
import math
import os
import signal
from pathlib import Path

from .errors import ConfigurationError, ProviderError


def validate_timeout(value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ConfigurationError("timeout must be finite and positive")


async def run_process(
    argv,
    *,
    input_bytes=b"",
    timeout=30,
    max_output_bytes=1024 * 1024,
    output_path: Path | None = None,
    max_file_bytes=16 * 1024 * 1024,
):
    validate_timeout(timeout)
    if type(max_output_bytes) is not int or max_output_bytes < 1:
        raise ConfigurationError("process output limit must be positive")
    if os.name != "posix":
        raise ConfigurationError(
            "safe process-group execution currently requires POSIX"
        )
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    total = 0

    async def read(stream):
        nonlocal total
        chunks = []
        while chunk := await stream.read(16384):
            total += len(chunk)
            if total > max_output_bytes:
                raise ProviderError("process output exceeded the size limit")
            chunks.append(chunk)
        return b"".join(chunks)

    async def feed():
        try:
            process.stdin.write(input_bytes)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()
            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

    async def monitor():
        while True:
            if output_path is not None:
                try:
                    if output_path.stat().st_size > max_file_bytes:
                        raise ProviderError(
                            "process JSON output exceeded the size limit"
                        )
                except FileNotFoundError:
                    pass
            await asyncio.sleep(0.01)

    tasks = [
        asyncio.create_task(read(process.stdout)),
        asyncio.create_task(read(process.stderr)),
        asyncio.create_task(feed()),
        asyncio.create_task(process.wait()),
    ]
    watcher = asyncio.create_task(monitor())
    group = asyncio.gather(*tasks)
    try:
        done, _ = await asyncio.wait(
            [group, watcher], timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            raise ProviderError("process timed out")
        if watcher in done:
            await watcher
        result = await group
        return process.returncode, result[0], result[1]
    finally:
        # Kill the entire session even when its original leader has exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        group.cancel()
        watcher.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(group, watcher, *tasks, return_exceptions=True)
        await process.wait()
