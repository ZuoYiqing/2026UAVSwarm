"""Loopback companion service. Fake is the default; SITL is explicit."""
from __future__ import annotations

import argparse
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .contract import PlatformError, canonical, identifier
from .service import PlatformService
from .store import TaskStore
from .transport import JsonClient


class PlatformHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service, token, evidence_dispatch=None):
        self.service, self.token, self.evidence_dispatch = service, token, evidence_dispatch
        super().__init__(address, PlatformHandler)


class PlatformHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def log_message(self, *_args):
        pass  # In particular, never log bearer credentials or task bodies.

    def _send(self, status, body):
        data = canonical(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        try:
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + self.server.token):
                self._send(401, {"error": "authentication_required"})
                return
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if any(len(values) != 1 for values in query.values()):
                raise PlatformError("invalid_query")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 65536:
                raise PlatformError("request_too_large", 413)
            body = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(body, dict):
                raise PlatformError("object_required")
            service = self.server.service
            path, method = parsed.path.rstrip("/"), self.command
            if method == "GET" and path == "/api/platform/status":
                self._send(200, service.status())
            elif method == "POST" and path == "/api/platform/link/heartbeat":
                if set(body) - {"contract_version"}:
                    raise PlatformError("invalid_heartbeat")
                self._send(200, service.heartbeat())
            elif method == "POST" and path == "/api/platform/tasks":
                task, created = service.submit(body)
                self._send(202 if created else 200, {"task": task, "idempotent_replay": not created})
            elif path.startswith("/api/platform/tasks/"):
                parts = path.split("/")
                task_id = identifier(parts[4])
                if method == "GET" and len(parts) == 5:
                    self._send(200, {"task": service.store.task(task_id)})
                elif method == "POST" and len(parts) == 6 and parts[5] == "cancel":
                    self._send(202, {"task": service.cancel(task_id)})
                elif method == "POST" and len(parts) == 6 and parts[5] == "reconcile":
                    if set(body) != {"operator_id", "execution_id"}:
                        raise PlatformError("invalid_reconciliation")
                    self._send(200, {"task": service.reconcile(task_id, body["operator_id"], body["execution_id"])})
                else:
                    raise PlatformError("not_found", 404)
            elif method == "GET" and path in {"/api/platform/events", "/api/platform/events/stream"}:
                if set(query) - {"after_seq", "store_id"}:
                    raise PlatformError("invalid_query")
                if query.get("store_id", [service.store.store_id])[0] != service.store.store_id:
                    raise PlatformError("event_store_changed", 409)
                cursor = int(query.get("after_seq", ["0"])[0])
                if path.endswith("/stream"):
                    self._stream(cursor)
                else:
                    self._send(200, service.store.events(cursor))
            elif self.server.evidence_dispatch and ((method == "POST" and path in {
                    "/api/simulation/evidence", "/api/coordinates/calibration"})
                    or (method == "GET" and path in {"/api/preflight", "/api/telemetry/latest"})):
                # Diagnostics/acceptance sources are kept separate from model
                # observations. No raw action endpoint is exposed here.
                if path == "/api/coordinates/calibration" and body.get("node_id") != service.node_id:
                    raise PlatformError("node_mismatch", 409)
                status, result = self.server.evidence_dispatch(method, path, body=body, query=parsed.query)
                self._send(status, result)
            else:
                raise PlatformError("not_found", 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as exc:
            status = exc.status if isinstance(exc, PlatformError) else 400 if isinstance(exc, (ValueError, TypeError, KeyError)) else 500
            error = exc.code if isinstance(exc, PlatformError) else "invalid_request" if status == 400 else "internal_error"
            try:
                self._send(status, {"error": error})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

    def _stream(self, cursor):
        service = self.server.service
        service.store.events(cursor)  # Validate before writing headers.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        while not service.stop.is_set():
            page = service.store.events(cursor)
            for event in page["events"]:
                self.wfile.write(f"id: {event['seq']}\nevent: platform_event\ndata: {canonical(event)}\n\n".encode())
                cursor = event["seq"]
            self.wfile.write(b": keepalive\n\n")
            self.wfile.flush()
            if not page["has_more"]:
                with service.store.changed:
                    service.store.changed.wait(timeout=1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-id", default="UAV-02", choices=["UAV-02"])
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--store-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--execution-mode", choices=["fake", "sitl"], default="fake")
    parser.add_argument("--vehicle-config", default="config/vehicles.sitl.json")
    parser.add_argument("--candidate-url")
    parser.add_argument("--run-id", help="Simulation-managed run identity; required for SITL")
    args = parser.parse_args(argv)
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32 or any(c.isspace() for c in token):
        parser.error("token-file must contain at least 32 non-whitespace characters")
    if args.execution_mode == "sitl" and not args.run_id:
        parser.error("--run-id is required for SITL; use the active harness run_id")
    store = TaskStore(args.store_dir)
    candidate = JsonClient(args.candidate_url) if args.candidate_url else None
    actions = None
    if args.execution_mode == "sitl":
        from .deployment import SitlActions
        actions = SitlActions(args.node_id, args.vehicle_config, str(args.store_dir / "actions.audit.jsonl"))
    service = PlatformService(store, node_id=args.node_id, mode=args.execution_mode,
                              execute=actions.execute if actions else None, observe=actions.observe if actions else None,
                              candidate=(lambda body: candidate.request("POST", body=body)) if candidate else None, run_id=args.run_id)
    server = PlatformHttpServer(("127.0.0.1", args.port), service, token,
                                actions.routes.dispatch if actions else None)
    try:
        if actions:
            actions.registry.start_all()
        service.start()
        print(f"platform_service node={args.node_id} mode={args.execution_mode} port={args.port}")
        while True:
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                if actions and not service.status()["safe_to_stop"]:
                    print("refusing unsafe stop: fresh landed/disarmed evidence and no active task required")
                    continue
            break
    finally:
        service.stop.set()
        with store.changed:
            store.changed.notify_all()
        if service.worker:
            service.worker.join(timeout=1)
        server.server_close()
        if actions:
            actions.registry.stop_all()
            actions.lease.close()
        if service.worker is None or not service.worker.is_alive():
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
