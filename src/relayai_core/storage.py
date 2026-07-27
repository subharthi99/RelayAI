from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from time import time
from typing import Any

from .errors import ConfigurationError
from .models import PipelineDefinition, PipelineRun
from .serialization import export_pipeline, load_pipeline


class SQLiteStore:
    """Small async persistence boundary using one short-lived connection per call."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        def initialize_sync() -> None:
            with self._connect() as connection:
                connection.executescript(
                    """
                    PRAGMA journal_mode = WAL;
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

        await asyncio.to_thread(initialize_sync)

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

        await asyncio.to_thread(save_sync)

    async def get_pipeline(self, pipeline_id: str) -> PipelineDefinition | None:
        def get_sync() -> str | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT definition_json FROM pipelines WHERE id = ?",
                    (pipeline_id,),
                ).fetchone()
                return None if row is None else str(row["definition_json"])

        document = await asyncio.to_thread(get_sync)
        return None if document is None else load_pipeline(document)

    async def list_pipelines(self) -> tuple[PipelineDefinition, ...]:
        def list_sync() -> list[str]:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT definition_json FROM pipelines ORDER BY id"
                ).fetchall()
                return [str(row["definition_json"]) for row in rows]

        documents = await asyncio.to_thread(list_sync)
        return tuple(load_pipeline(document) for document in documents)

    async def delete_pipeline(self, pipeline_id: str) -> bool:
        def delete_sync() -> bool:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM pipelines WHERE id = ?",
                    (pipeline_id,),
                )
                return cursor.rowcount > 0

        return await asyncio.to_thread(delete_sync)

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

        await asyncio.to_thread(save_sync)

    async def get_run_receipt(self, run_id: str) -> dict[str, Any] | None:
        def get_sync() -> str | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT receipt_json FROM pipeline_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                return None if row is None else str(row["receipt_json"])

        document = await asyncio.to_thread(get_sync)
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

        documents = await asyncio.to_thread(list_sync)
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
                cursor = connection.execute(query, parameters)
                return cursor.rowcount

        return await asyncio.to_thread(delete_sync)
