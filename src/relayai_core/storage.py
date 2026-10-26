from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from time import time
from typing import Any

from .errors import ConfigurationError
from .models import PipelineDefinition, PipelineRun
from .serialization import export_pipeline, load_pipeline


async def _io(operation):
    """Finish database work before delivering cancellation to its caller."""
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class SQLiteStore:
    """Small async persistence boundary using one short-lived connection per call."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.path.is_symlink():
            raise ConfigurationError("database path cannot be a symlink")
        descriptor = os.open(
            self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            self._private_files()
            with connection:
                yield connection
        finally:
            connection.close()
            self._private_files()

    def _private_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.path) + suffix)
            if path.exists():
                try:
                    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                except FileNotFoundError:
                    # Another short-lived SQLite connection may checkpoint and
                    # remove its WAL/SHM files between existence check and open.
                    continue
                try:
                    os.fchmod(fd, 0o600)
                finally:
                    os.close(fd)

    async def initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(
            self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        os.fchmod(fd, 0o600)
        os.close(fd)

        def initialize_sync() -> None:
            with self._connect() as connection:
                connection.executescript(
                    """
                    PRAGMA journal_mode = WAL;
                    PRAGMA secure_delete = ON;
                    CREATE TABLE IF NOT EXISTS prepared_runs (
                        id TEXT PRIMARY KEY,
                        definition_json TEXT NOT NULL,
                        binding TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS pipelines (
                        id TEXT PRIMARY KEY,
                        definition_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS pipeline_runs (
                        id TEXT PRIMARY KEY,
                        pipeline_id TEXT NOT NULL,
                        receipt_json TEXT NOT NULL,
                        started_at REAL NOT NULL,
                        completed_at REAL
                    );
                    CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline_started
                    ON pipeline_runs (pipeline_id, started_at DESC);
                    """
                )

        await _io(initialize_sync)

    async def save_pipeline(self, pipeline: PipelineDefinition) -> None:
        definition = export_pipeline(pipeline)

        def save_sync() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO pipelines (id, definition_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        definition_json = excluded.definition_json,
                        updated_at = excluded.updated_at
                    """,
                    (pipeline.id, definition, time()),
                )

        await _io(save_sync)

    async def save_prepared(self, prepared) -> None:
        await self.save_run(prepared.run)
        definition = export_pipeline(prepared.pipeline)

        def save_sync() -> None:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO prepared_runs VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET definition_json=excluded.definition_json, binding=excluded.binding",
                    (prepared.run.id, definition, prepared.binding),
                )

        await _io(save_sync)

    async def get_prepared(self, run_id: str):
        from .engine import PreparedRun
        from .models import (
            DestinationReceipt,
            DestinationEffect,
            ExposureEvent,
            Exposure,
            RunStatus,
        )

        def get_sync():
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT p.definition_json, p.binding, r.receipt_json FROM prepared_runs p JOIN pipeline_runs r USING(id) WHERE id=?",
                    (run_id,),
                ).fetchone()
                return dict(row) if row is not None else None

        row = await _io(get_sync)
        if row is None:
            raise ConfigurationError("prepared run not found")
        data = json.loads(row["receipt_json"])
        data["status"] = RunStatus(data["status"])
        data["destinations"] = [
            DestinationReceipt(**{**item, "effect": DestinationEffect(item["effect"])})
            for item in data["destinations"]
        ]
        data["exposure_events"] = [
            ExposureEvent(**{**item, "exposure": Exposure(item["exposure"])})
            for item in data["exposure_events"]
        ]
        return PreparedRun(
            load_pipeline(row["definition_json"]), PipelineRun(**data), row["binding"]
        )

    async def claim_run(self, previous: str, run: PipelineRun) -> None:
        receipt = json.dumps(asdict(run), sort_keys=True)

        def claim_sync() -> None:
            with self._connect() as connection:
                cursor = connection.execute(
                    "UPDATE pipeline_runs SET receipt_json=?, completed_at=NULL WHERE id=? AND receipt_json=?",
                    (receipt, run.id, previous),
                )
                if cursor.rowcount != 1:
                    raise ConfigurationError(
                        "run is stale, already claimed, or not persisted"
                    )

        await _io(claim_sync)

    async def get_pipeline(self, pipeline_id: str) -> PipelineDefinition | None:
        def get_sync() -> str | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT definition_json FROM pipelines WHERE id = ?",
                    (pipeline_id,),
                ).fetchone()
                return None if row is None else str(row["definition_json"])

        document = await _io(get_sync)
        return None if document is None else load_pipeline(document)

    async def list_pipelines(self) -> tuple[PipelineDefinition, ...]:
        def list_sync() -> list[str]:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT definition_json FROM pipelines ORDER BY id"
                ).fetchall()
                return [str(row["definition_json"]) for row in rows]

        documents = await _io(list_sync)
        return tuple(load_pipeline(document) for document in documents)

    async def delete_pipeline(self, pipeline_id: str) -> bool:
        def delete_sync() -> bool:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM pipelines WHERE id = ?",
                    (pipeline_id,),
                )
                return cursor.rowcount > 0

        return await _io(delete_sync)

    async def save_run(self, run: PipelineRun) -> None:
        receipt = json.dumps(asdict(run), sort_keys=True)

        def save_sync() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO pipeline_runs (
                        id, pipeline_id, receipt_json, started_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        receipt_json = excluded.receipt_json,
                        completed_at = excluded.completed_at
                    """,
                    (
                        run.id,
                        run.pipeline_id,
                        receipt,
                        run.started_at,
                        run.completed_at,
                    ),
                )

        await _io(save_sync)

    async def get_run_receipt(self, run_id: str) -> dict[str, Any] | None:
        def get_sync() -> str | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT receipt_json FROM pipeline_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                return None if row is None else str(row["receipt_json"])

        document = await _io(get_sync)
        if document is None:
            return None
        try:
            value = json.loads(document)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("stored run receipt is invalid") from exc
        if not isinstance(value, dict):
            raise ConfigurationError("stored run receipt must be an object")
        return value

    async def list_run_receipts(
        self,
        *,
        pipeline_id: str | None = None,
        limit: int = 50,
    ) -> tuple[dict[str, Any], ...]:
        if limit < 1 or limit > 1000:
            raise ConfigurationError("run receipt limit must be between 1 and 1000")

        def list_sync() -> list[str]:
            query = "SELECT receipt_json FROM pipeline_runs"
            parameters: list[Any] = []
            if pipeline_id is not None:
                query += " WHERE pipeline_id = ?"
                parameters.append(pipeline_id)
            query += " ORDER BY started_at DESC LIMIT ?"
            parameters.append(limit)
            with self._connect() as connection:
                rows = connection.execute(query, parameters).fetchall()
                return [str(row["receipt_json"]) for row in rows]

        documents = await _io(list_sync)
        receipts: list[dict[str, Any]] = []
        for document in documents:
            try:
                value = json.loads(document)
            except json.JSONDecodeError as exc:
                raise ConfigurationError("stored run receipt is invalid") from exc
            if not isinstance(value, dict):
                raise ConfigurationError("stored run receipt must be an object")
            receipts.append(value)
        return tuple(receipts)

    async def delete_run_receipts(
        self,
        *,
        pipeline_id: str | None = None,
        completed_before: float | None = None,
    ) -> int:
        clauses: list[str] = []
        parameters: list[Any] = []
        if pipeline_id is not None:
            clauses.append("pipeline_id = ?")
            parameters.append(pipeline_id)
        if completed_before is not None:
            clauses.append("completed_at IS NOT NULL AND completed_at < ?")
            parameters.append(completed_before)
        if not clauses:
            raise ConfigurationError(
                "receipt deletion requires pipeline_id or completed_before"
            )

        def delete_sync() -> int:
            query = "DELETE FROM pipeline_runs WHERE " + " AND ".join(clauses)
            with self._connect() as connection:
                connection.execute("PRAGMA secure_delete=ON")
                connection.execute(
                    "DELETE FROM prepared_runs WHERE id IN (SELECT id FROM pipeline_runs WHERE "
                    + " AND ".join(clauses)
                    + ")",
                    parameters,
                )
                cursor = connection.execute(query, parameters)
                return cursor.rowcount

        return await _io(delete_sync)
