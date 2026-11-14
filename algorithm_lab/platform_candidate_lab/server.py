"""Single-process loopback HTTP endpoint for Runtime's POST /candidate."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from .candidate import decide
from .contracts import MAX_JSON_BYTES, ContractError, parse_json
from .local_model import LocalInferenceClient


def _encoded(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def make_handler(client: LocalInferenceClient, *, allow_fake: bool = False):
    class CandidateHandler(BaseHTTPRequestHandler):
        server_version = "UAVSwarmCandidate/0.1"

        def _reply(self, status: int, value: dict) -> None:
            body = _encoded(value)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/health":
                self._reply(404, {"error": "NOT_FOUND"})
                return
            self._reply(200, {"status": "process_alive", "model_id": client.model})

        def do_POST(self) -> None:
            if self.path != "/candidate":
                self._reply(404, {"error": "NOT_FOUND"})
                return
            try:
                size = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._reply(411, {"error": "CONTENT_LENGTH_REQUIRED"})
                return
            if not 1 <= size <= MAX_JSON_BYTES:
                self._reply(413, {"error": "REQUEST_SIZE_INVALID"})
                return
            try:
                request = parse_json(self.rfile.read(size))
                response = decide(request, client, allow_fake=allow_fake)
            except ContractError as exc:
                self._reply(400, {"status": "no_candidate", "decision": None,
                                  "failure_reason_code": "INPUT_INVALID",
                                  "detail": str(exc), "execution_authorized": False})
                return
            self._reply(200, response)

        def log_message(self, format: str, *args: object) -> None:
            # Do not print the request body or local telemetry into a server log.
            pass

    return CandidateHandler


def serve(client: LocalInferenceClient, *, port: int = 8872,
          allow_fake: bool = False) -> None:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("PORT_INVALID")
    with HTTPServer(("127.0.0.1", port), make_handler(client, allow_fake=allow_fake)) as server:
        server.serve_forever(poll_interval=0.2)
