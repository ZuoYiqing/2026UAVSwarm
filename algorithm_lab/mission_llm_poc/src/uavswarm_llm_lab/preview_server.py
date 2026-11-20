"""Loopback-only HTTP adapter for evidence preview, not a Runtime endpoint."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from time import perf_counter
from urllib.error import URLError

from .contracts import ContractError, parse_json
from .local_model_client import ModelError
from .scene_selection_preview import evaluate_scene_preview, record_bytes, scoped_buildings


PREVIEW_PATH = "/lab/semantic-preview"
HEALTH_PATH = PREVIEW_PATH + "/health"
CONSOLE_ORIGINS = frozenset({"http://127.0.0.1:5178", "http://localhost:5178"})
MAX_BODY_BYTES = 4096
SERVICE = "uavswarm_lab_semantic_preview"


def make_preview_server(catalog: dict, client, *, model_alias: str, port: int = 18118) -> ThreadingHTTPServer:
    """Bind the experiment locally. The caller owns its lifetime and model process."""
    scoped_buildings(catalog)
    prediction = Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(6)
            super().setup()

        def log_message(self, *args):
            # Do not log potentially user-authored text or inbound URLs.
            pass

        def _headers(self, status: int, size: int):
            self.send_response(status)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Vary", "Origin")
            origins = self.headers.get_all("Origin", [])
            if len(origins) == 1 and origins[0] in CONSOLE_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origins[0])
            if status == 204:
                self.send_header("Access-Control-Allow-Methods", "POST")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
            else:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()

        def _json(self, http_status: int, **body):
            payload = json.dumps({"service": SERVICE, "api_version": "0.1",
                                  "execution_authorized": False, **body},
                                 ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._headers(http_status, len(payload))
            self.wfile.write(payload)

        def _error(self, status: int, reason: str):
            self._json(status, error={"reason_code": reason})

        def _allows(self) -> bool:
            port_number = self.server.server_port
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1 or hosts[0] not in {f"127.0.0.1:{port_number}", f"localhost:{port_number}"}:
                self._error(403, "PREVIEW_HOST_DENIED")
                return False
            origins = self.headers.get_all("Origin", [])
            if origins and (len(origins) != 1 or origins[0] not in CONSOLE_ORIGINS):
                self._error(403, "PREVIEW_ORIGIN_DENIED")
                return False
            return True

        def do_OPTIONS(self):
            if not self._allows():
                return
            if self.path != PREVIEW_PATH or self.headers.get("Access-Control-Request-Method") != "POST":
                return self._error(404, "PREVIEW_ROUTE_NOT_FOUND")
            self._headers(204, 0)

        def do_GET(self):
            if not self._allows():
                return
            if self.path != HEALTH_PATH:
                return self._error(404, "PREVIEW_ROUTE_NOT_FOUND")
            self._json(200, status="ready", model_alias=model_alias, model_status="not_checked")

        def do_POST(self):
            if not self._allows():
                return
            if self.path != PREVIEW_PATH:
                return self._error(404, "PREVIEW_ROUTE_NOT_FOUND")
            if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
                return self._error(415, "PREVIEW_JSON_REQUIRED")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 5:
                return self._error(400, "PREVIEW_LENGTH_REQUIRED")
            size = int(lengths[0])
            if not 1 <= size <= MAX_BODY_BYTES:
                return self._error(413, "PREVIEW_BODY_SIZE")
            try:
                raw_body = self.rfile.read(size)
                if len(raw_body) != size:
                    return self._error(400, "PREVIEW_BODY_INVALID")
                request = parse_json(raw_body.decode("utf-8"))
            except (ContractError, UnicodeError, TimeoutError):
                return self._error(400, "PREVIEW_BODY_INVALID")
            if not isinstance(request, dict) or set(request) != {"objective"}:
                return self._error(400, "PREVIEW_REQUEST_INVALID")
            if not prediction.acquire(blocking=False):
                return self._error(429, "PREVIEW_BUSY")
            started = perf_counter()
            try:
                preview, raw = evaluate_scene_preview(request["objective"], catalog, client, model_alias=model_alias)
            except ContractError as exc:
                reason = str(exc)
                if reason in {"UNSUPPORTED_PREVIEW_OBJECTIVE", "INVALID_PREVIEW_OBJECTIVE"}:
                    return self._error(422, reason)
                return self._error(502, "MODEL_RESPONSE_REJECTED")
            except ModelError as exc:
                cause = exc.__cause__
                if isinstance(cause, TimeoutError) or isinstance(getattr(cause, "reason", None), TimeoutError):
                    return self._error(504, "MODEL_TIMEOUT")
                if isinstance(cause, (URLError, OSError)):
                    return self._error(503, "MODEL_UNAVAILABLE")
                return self._error(502, "MODEL_RESPONSE_REJECTED")
            finally:
                prediction.release()
            self._json(200, mode="live", elapsed_ms=round((perf_counter() - started) * 1000),
                       preview=preview, evidence_json=record_bytes(raw).decode("utf-8"))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
