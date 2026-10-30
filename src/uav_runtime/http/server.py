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
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from uav_runtime.http.routes import dispatch
from uav_runtime.http.routes import VEHICLE_REGISTRY

ALLOWED_ORIGINS = {
    "http://localhost:5178",
    "http://127.0.0.1:5178",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # 三维视图自身的来源。它在 5179 由 Vite 提供，并且是 5178 主控制台的
    # iframe 子页面；嵌入时它与父页面不同源，因此从这里发出的飞行动作请求
    # 属于跨域，必须在白名单里才不会被浏览器拦掉。
    # 5179 与 5178 同样只监听 127.0.0.1，无对外暴露。
    "http://localhost:5179",
    "http://127.0.0.1:5179",
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
            if self.command == "POST" and (parsed.path.startswith("/api/platform/") or parsed.path in {
                    "/api/simulation/evidence", "/api/coordinates/calibration"}):
                origin = self.headers.get("Origin")
                if origin is not None and origin not in ALLOWED_ORIGINS:
                    self._send_json(403, {"error": "origin_not_allowed"})
                    return
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    self._send_json(415, {"error": "json_content_type_required"})
                    return
            if self.command == "GET" and parsed.path == "/api/platform/events/stream":
                from uav_runtime.http import routes
                if routes.PLATFORM_GATEWAY is not None:
                    routes.PLATFORM_GATEWAY.stream_to(self, self.path)
                    return
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
        # A browser closing/refreshing aborts header writes as well as body
        # writes. Handle disconnects here, including 400/500 and OPTIONS, so
        # no second response is attempted on a closed socket.
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors_headers()
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

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


def main(argv=None) -> int:
    from uav_runtime.http import routes
    from uav_runtime.http.state_store import RuntimeStateStore
    from uav_runtime.runtime.vehicle_registry import VehicleRegistry
    from uav_runtime.platform.deployment import select_registry
    from uav_runtime.platform.gateway import PlatformGateway
    from uav_runtime.platform.ownership import TransportLease
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exclude-node", action="append", default=[])
    parser.add_argument("--vehicle-config")
    parser.add_argument("--platform-url")
    parser.add_argument("--platform-token-file", type=Path)
    args = parser.parse_args(argv)
    source = VehicleRegistry.from_json(args.vehicle_config) if args.vehicle_config else routes.VEHICLE_REGISTRY
    for excluded in args.exclude_node:
        source.get_vehicle(excluded)
    if args.exclude_node or args.vehicle_config:
        routes.VEHICLE_REGISTRY = select_registry(source, [h.config.node_id for h in source.list_vehicles()
                                                          if h.config.node_id not in args.exclude_node])
        routes.RUNTIME_STATE_STORE = RuntimeStateStore(vehicle_registry=routes.VEHICLE_REGISTRY)
    registry = routes.VEHICLE_REGISTRY
    gateway = None
    if args.platform_url:
        if not args.platform_token_file or "UAV-02" not in args.exclude_node:
            parser.error("platform gateway requires --exclude-node UAV-02 and --platform-token-file")
        token = args.platform_token_file.read_text(encoding="utf-8").strip()
        if len(token) < 32 or any(c.isspace() for c in token):
            parser.error("platform token must contain at least 32 non-whitespace characters")
        # Metadata-only fallback: never start this selected registry/session.
        # It keeps the registered remote node visible before its first report.
        remote_registry = select_registry(source, ["UAV-02"])
        remote_store = RuntimeStateStore(vehicle_registry=remote_registry)
        defaults = {"telemetry": remote_store.telemetry_latest(), "vehicles": {"vehicles": remote_registry.vehicle_rows()},
                    "runtime_snapshot": remote_store.runtime_snapshot(), "vehicle_snapshot": remote_store.vehicle_snapshot()}
        gateway = PlatformGateway(args.platform_url, token, default_projections=defaults)
        routes.PLATFORM_GATEWAY = gateway
    server = create_server()
    leases = []
    telemetry_enabled = os.environ.get("UAV_RUNTIME_TELEMETRY_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    try:
        if telemetry_enabled:
            for handle in registry.list_vehicles():
                if handle.config.enabled and handle.config.endpoint.startswith("udpin:127.0.0.1:"):
                    leases.append(TransportLease(handle.config.endpoint))
            registry.start_all()
        if gateway:
            gateway.start()
        print("uav_runtime_http_bridge listening on http://127.0.0.1:8765/api")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if gateway:
            gateway.close()
        registry.stop_all()
        for lease in leases:
            lease.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
