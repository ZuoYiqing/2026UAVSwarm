"""Windows loopback model relay bound only to the WSL virtual adapter."""
from __future__ import annotations

import argparse
import hmac
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, IPv4Interface
import json
from pathlib import Path
import subprocess
import sys
from threading import Lock

from uav_runtime.http.model_preview_config import (
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    MODEL_PORT,
    is_private_bridge_address,
    parse_model_timeout,
    read_model_token,
)


_READS = {"/health", "/v1/models"}
_COMPLETION = "/v1/chat/completions"
_MAX_BYTES = 65536


def _windows_wsl_adapter(gateway: IPv4Address) -> IPv4Interface:
    # Check the actual interface, never a Wi-Fi/Ethernet address supplied at launch.
    command = (
        "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | "
        "Where-Object { $_.InterfaceAlias -like 'vEthernet (WSL*' } | "
        "Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            timeout=8, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rows = json.loads(result) if result.strip() else []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if row["IPAddress"] == str(gateway):
                return IPv4Interface(f"{gateway}/{row['PrefixLength']}")
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("could not verify the Windows WSL adapter") from exc
    raise ValueError("listen address is not assigned to the Windows WSL virtual adapter")


class _RelayServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def __init__(
        self, address: tuple[str, int], *, peer: str, token: str, timeout_s: float, upstream_port: int = MODEL_PORT,
    ) -> None:
        self.peer = peer
        self.authorization = f"Bearer {token}".encode("ascii")
        self.timeout_s = timeout_s
        self.upstream_port = upstream_port
        self.slot = Lock()
        super().__init__(address, _RelayHandler)

    def verify_request(self, request, client_address) -> bool:
        return client_address[0] == self.peer


class _RelayHandler(BaseHTTPRequestHandler):
    timeout = 5.0

    def do_GET(self) -> None:  # noqa: N802
        self._relay()

    def do_POST(self) -> None:  # noqa: N802
        self._relay()

    def _relay(self) -> None:
        target = self.server
        auth = self.headers.get_all("Authorization", [])
        if len(auth) != 1 or not hmac.compare_digest(auth[0].encode("latin1"), target.authorization):
            self._reply(401, b'{"error":"model_relay_unauthorized"}')
            return
        if not ((self.command == "GET" and self.path in _READS)
                or (self.command == "POST" and self.path == _COMPLETION)):
            self._reply(404, b'{"error":"model_relay_path_not_allowed"}')
            return
        body = None
        if self.command == "POST":
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get_all("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
                self._reply(415, b'{"error":"model_relay_json_required"}')
                return
            if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal()
                    or len(lengths[0]) > 5 or not 1 <= (length := int(lengths[0])) <= _MAX_BYTES):
                self._reply(400, b'{"error":"model_relay_invalid_length"}')
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self._reply(400, b'{"error":"model_relay_incomplete_body"}')
                return
        acquired = self.command != "POST" or target.slot.acquire(blocking=False)
        if not acquired:
            self._reply(503, b'{"error":"model_relay_busy"}')
            return
        connection = HTTPConnection("127.0.0.1", target.upstream_port, timeout=target.timeout_s)
        try:
            # Do not forward credentials, origin, host, or other caller headers.
            headers = {"Content-Type": "application/json"} if body is not None else {}
            connection.request(self.command, self.path, body, headers)
            with connection.getresponse() as response:
                raw = response.read(_MAX_BYTES + 1)
                if response.status != 200 or len(raw) > _MAX_BYTES:
                    raise OSError("model upstream rejected the request")
            self._reply(200, raw)
        except (OSError, HTTPException):
            self._reply(502, b'{"error":"model_relay_upstream_unavailable"}')
        finally:
            connection.close()
            if self.command == "POST":
                target.slot.release()

    def _reply(self, status: int, raw: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionError):
            pass

    def log_message(self, *_args) -> None:
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", type=IPv4Address, required=True)
    parser.add_argument("--wsl-peer", type=IPv4Address, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--timeout-s", type=parse_model_timeout, default=DEFAULT_MODEL_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("run the model relay on the Windows host")
    try:
        if not all(map(is_private_bridge_address, (args.gateway, args.wsl_peer))) or args.gateway == args.wsl_peer:
            raise ValueError("gateway and WSL peer must be distinct private IPv4 addresses")
        adapter = _windows_wsl_adapter(args.gateway)
        if (args.wsl_peer not in adapter.network
                or args.wsl_peer in (adapter.network.network_address, adapter.network.broadcast_address)):
            raise ValueError("WSL peer is not a host on the verified WSL adapter subnet")
        token = read_model_token(args.token_file)
        with _RelayServer((str(args.gateway), MODEL_PORT), peer=str(args.wsl_peer), token=token,
                          timeout_s=args.timeout_s) as relay:
            print(f"WSL model relay listening at {args.gateway}:{MODEL_PORT} for {args.wsl_peer}", flush=True)
            try:
                relay.serve_forever()
            except KeyboardInterrupt:
                pass
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
