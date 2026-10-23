"""Ground HTTP facade. Only this leg is impaired by Simulation's proxy."""
from __future__ import annotations

import threading
import urllib.request

from .contract import PlatformError
from .transport import JsonClient


class PlatformGateway:
    def __init__(self, base: str, token: str):
        self.client = JsonClient(base, token, max_bytes=8 * 1024 * 1024)
        self.stop = threading.Event()
        self.thread = None

    def relay(self, method, path, body=None, query=""):
        if method not in {"GET", "POST"} or not path.startswith("/api/platform/"):
            raise PlatformError("not_found", 404)
        return self.client.request(method, path + ("?" + query if query else ""), body if method == "POST" else None)

    def publish_diagnostic(self, path, body):
        if path not in {"/api/simulation/evidence", "/api/coordinates/calibration"}:
            raise PlatformError("not_found", 404)
        return self.client.request("POST", path, body)

    def start(self):
        self.thread = threading.Thread(target=self._heartbeat, daemon=True, name="ground-platform-link")
        self.thread.start()

    def stream_to(self, handler, path):
        request = urllib.request.Request(self.client.base + path,
                                         headers={"Authorization": "Bearer " + self.client.token})
        sent_headers = False
        try:
            with self.client.opener.open(request, timeout=3) as response:
                handler.send_response(200)
                handler.send_header("Content-Type", "text/event-stream")
                handler.send_header("Cache-Control", "no-cache")
                handler._send_cors_headers()
                handler.end_headers()
                sent_headers = True
                while not self.stop.is_set():
                    line = response.readline(65537)
                    if not line:
                        break
                    if len(line) > 65536:
                        break
                    handler.wfile.write(line)
                    handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:
            if not sent_headers:
                handler._send_json(503, {"error": "platform_link_unavailable"})

    def _heartbeat(self):
        while not self.stop.is_set():
            try:
                self.client.request("POST", "/api/platform/link/heartbeat", {"contract_version": "1.0"})
            except Exception:
                pass  # The platform's monotonic lease expires; never fake ack.
            self.stop.wait(1)
