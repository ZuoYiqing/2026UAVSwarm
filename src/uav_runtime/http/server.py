"""Local development HTTP server for the Runtime HTTP Bridge.

Run with:
    python -m uav_runtime.http.server

This server intentionally uses only stdlib HTTP primitives.  It exposes a fixed
/api allowlist for the local swarm-console frontend and never runs arbitrary
commands supplied by the browser.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from uav_runtime.http.routes import dispatch
from uav_runtime.http.routes import RUNTIME_STATE_STORE
from uav_runtime.adapters.px4_telemetry_collector import Px4TelemetryCollector

ALLOWED_ORIGINS = {
    "http://localhost:5178",
    "http://127.0.0.1:5178",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


class RuntimeHttpBridgeHandler(BaseHTTPRequestHandler):
    """HTTP bridge handler for local frontend development.

    CORS is restricted to local Vite development origins.  This is not a public
    service and should not be deployed on an untrusted network without adding
    authentication, authorization, TLS, and explicit operational controls.
    """

    server_version = "UavRuntimeHttpBridge/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        self._send_json(204, {})

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._handle_json_request()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self._handle_json_request()

    def _handle_json_request(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._read_json_body() if self.command == "POST" else {}
            status, payload = dispatch(self.command, parsed.path, body=body, query=parsed.query)
            self._send_json(status, payload)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
        except Exception as exc:  # keep local bridge failures visible as JSON
            self._send_json(500, {"error": "internal_error", "detail": type(exc).__name__})

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise json.JSONDecodeError("expected object", raw, 0)
        return data

    def _send_json(self, status: int, payload: Any) -> None:
        body = b"" if status == 204 else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt: str, *args: object) -> None:
        # Keep test output and local console readable; operators can add structured
        # access logging later if this bridge grows beyond local development.
        return


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), RuntimeHttpBridgeHandler)


def main() -> int:
    server = create_server()
    collector: Px4TelemetryCollector | None = None
    telemetry_enabled = os.environ.get("UAV_RUNTIME_TELEMETRY_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    if telemetry_enabled:
        # 14030 is deliberately separate from the 14540 command/smoke endpoint.
        # A single UDP listen port must not be consumed by independent receivers.
        endpoint = os.environ.get("UAV_RUNTIME_TELEMETRY_ENDPOINT", "udpin:127.0.0.1:14030")
        collector = Px4TelemetryCollector(RUNTIME_STATE_STORE, endpoint=endpoint)
        collector.start()
    print("uav_runtime_http_bridge listening on http://127.0.0.1:8765/api")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if collector is not None:
            collector.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
