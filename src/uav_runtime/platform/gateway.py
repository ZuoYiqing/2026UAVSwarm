"""Ground HTTP facade. Only this leg is impaired by Simulation's proxy."""
from __future__ import annotations

import threading
import copy
import time
import urllib.request

from .contract import PlatformError, canonical, timestamp
from .transport import JsonClient
from .view import VIEW_VALID_MS, aged_view, validate_projections


class PlatformGateway:
    def __init__(self, base: str, token: str, *, default_projections=None, monotonic=time.monotonic, clock=time.time):
        self.client = JsonClient(base, token, max_bytes=8 * 1024 * 1024)
        self.stop = threading.Event()
        self.thread = None
        self.view_thread = None
        self._view_lock = threading.Lock()
        self._view = None
        self._view_received = None
        self._view_source_age_ms = 0
        self._view_failed = True
        self._defaults = copy.deepcopy(default_projections or {})
        self._monotonic, self._clock = monotonic, clock

    def refresh_view(self):
        try:
            code, view = self.client.request("GET", "/api/platform/view")
            canonical(view)  # Reject non-finite values before caching any projection.
            if (code != 200 or view.get("contract_version") != "1.0" or view.get("node_id") != "UAV-02"
                    or view.get("execution_authorized") is not False or view.get("execution_mode") not in {"sitl", "fake"}
                    or not isinstance(view.get("store_id"), str)
                    or type(view.get("valid_for_ms")) is not int or not 0 < view["valid_for_ms"] <= VIEW_VALID_MS):
                raise PlatformError("platform_view_invalid", 502)
            age_ms = (self._clock() - timestamp(view.get("source_timestamp"))) * 1000
            if age_ms < -500:
                raise PlatformError("platform_view_timestamp_invalid", 502)
            if view["execution_mode"] == "sitl":
                if not isinstance(view.get("run_id"), str) or not view["run_id"]:
                    raise PlatformError("platform_view_run_id_required", 502)
                validate_projections(view.get("projections"))
            elif view.get("projections") is not None:
                raise PlatformError("fake_platform_view_cannot_publish_px4", 502)
            with self._view_lock:
                self._view, self._view_received = copy.deepcopy(view), self._monotonic()
                self._view_source_age_ms, self._view_failed = max(0, age_ms), False
        except Exception:
            with self._view_lock:
                self._view_failed = True
            raise

    def cached_view(self):
        with self._view_lock:
            view, received = copy.deepcopy(self._view), self._view_received
            failed, source_age = self._view_failed, self._view_source_age_ms
        elapsed = 0 if received is None else max(0, int((self._monotonic() - received) * 1000))
        age = elapsed + source_age
        fresh = (not failed and view is not None and view["execution_mode"] == "sitl"
                 and age <= view["valid_for_ms"])
        projections = (view or {}).get("projections") or self._defaults
        stale_after = (projections.get("telemetry") or {}).get("stale_after_ms", VIEW_VALID_MS)
        projections = aged_view(projections, elapsed_ms=age, fresh=fresh, stale_after_ms=stale_after)
        return {"contract_version": "1.0", "node_id": "UAV-02", "fresh": bool(fresh),
                "observation_status": "available" if fresh else "unknown",
                "store_id": (view or {}).get("store_id"), "run_id": (view or {}).get("run_id"),
                "source_timestamp": (view or {}).get("source_timestamp"), "age_ms": None if received is None else age,
                "reason": None if fresh else "platform_view_unavailable" if failed else "platform_view_stale",
                "runtime_telemetry": copy.deepcopy((view or {}).get("runtime_telemetry")),
                "projections": projections}

    def read_preflight(self):
        # This diagnostic may spend two bounded waits reading HOME and RTL.
        client = JsonClient(self.client.base, self.client.token, timeout=6, max_bytes=8 * 1024 * 1024)
        return client.request("GET", "/api/preflight?node_id=UAV-02")

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
        self.view_thread = threading.Thread(target=self._poll_view, daemon=True, name="ground-platform-view")
        self.view_thread.start()

    def close(self):
        self.stop.set()
        for worker in (self.thread, self.view_thread):
            if worker:
                worker.join(timeout=3)

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
                # The platform's monotonic lease expires; never fake ack.
                pass
            self.stop.wait(1)

    def _poll_view(self):
        # Read timeout/large JSON must not delay the independent ground lease.
        while not self.stop.is_set():
            try:
                self.refresh_view()
            except Exception:
                pass  # refresh_view already marks its last observation unknown.
            self.stop.wait(1)
