from __future__ import annotations

import asyncio
import hmac
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from .errors import ConfigurationError
from .serialization import export_pipeline
from .storage import SQLiteStore


def _run_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    destinations = receipt.get("destinations", [])
    warnings = receipt.get("warnings", [])
    return {
        "id": receipt.get("id"),
        "pipeline_id": receipt.get("pipeline_id"),
        "status": receipt.get("status"),
        "started_at": receipt.get("started_at"),
        "completed_at": receipt.get("completed_at"),
        "warning_count": len(warnings) if isinstance(warnings, list) else 0,
        "destination_statuses": [
            {
                "destination_id": item.get("destination_id"),
                "status": item.get("status"),
            }
            for item in destinations
            if isinstance(item, dict)
        ],
    }


def create_server(
    store: SQLiteStore,
    token: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Create an authenticated read-only API bound to the IPv4 loopback."""

    if host != "127.0.0.1":
        raise ConfigurationError("the local API must bind to 127.0.0.1")
    if len(token) < 32:
        raise ConfigurationError("the local API bearer token must be at least 32 characters")
    if port < 0 or port > 65535:
        raise ConfigurationError("port must be between 0 and 65535")

    class Handler(BaseHTTPRequestHandler):
        server_version = "RelayAI"
        sys_version = ""

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(
            self,
            status: HTTPStatus,
            payload: dict[str, Any] | list[Any],
        ) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            authorization = self.headers.get("Authorization", "")
            prefix = "Bearer "
            if not authorization.startswith(prefix):
                return False
            return hmac.compare_digest(authorization[len(prefix) :], token)

        def _not_found(self) -> None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/health":
                self._json(
                    HTTPStatus.OK,
                    {"status": "ok", "version": __version__},
                )
                return
            if not self._authorized():
                self._json(
                    HTTPStatus.UNAUTHORIZED,
                    {"error": "unauthorized"},
                )
                return
            try:
                if path == "/v1/pipelines":
                    pipelines = asyncio.run(store.list_pipelines())
                    self._json(
                        HTTPStatus.OK,
                        [
                            {
                                "id": item.id,
                                "name": item.name,
                                "schema_version": item.schema_version,
                                "local_only": item.policy.local_only,
                            }
                            for item in pipelines
                        ],
                    )
                    return
                if path.startswith("/v1/pipelines/"):
                    pipeline_id = unquote(path.removeprefix("/v1/pipelines/"))
                    if not pipeline_id or "/" in pipeline_id:
                        self._not_found()
                        return
                    pipeline = asyncio.run(store.get_pipeline(pipeline_id))
                    if pipeline is None:
                        self._not_found()
                        return
                    self._json(
                        HTTPStatus.OK,
                        json.loads(export_pipeline(pipeline)),
                    )
                    return
                if path == "/v1/runs":
                    query = parse_qs(parsed.query, keep_blank_values=False)
                    pipeline_id = query.get("pipeline_id", [None])[0]
                    try:
                        limit = int(query.get("limit", ["50"])[0])
                    except ValueError:
                        self._json(
                            HTTPStatus.BAD_REQUEST,
                            {"error": "limit_must_be_an_integer"},
                        )
                        return
                    receipts = asyncio.run(
                        store.list_run_receipts(
                            pipeline_id=pipeline_id,
                            limit=limit,
                        )
                    )
                    self._json(
                        HTTPStatus.OK,
                        [_run_summary(receipt) for receipt in receipts],
                    )
                    return
                if path.startswith("/v1/runs/"):
                    run_id = unquote(path.removeprefix("/v1/runs/"))
                    if not run_id or "/" in run_id:
                        self._not_found()
                        return
                    receipt = asyncio.run(store.get_run_receipt(run_id))
                    if receipt is None:
                        self._not_found()
                        return
                    self._json(HTTPStatus.OK, receipt)
                    return
                self._not_found()
            except ConfigurationError as exc:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_request", "message": str(exc)},
                )

    return ThreadingHTTPServer((host, port), Handler)
