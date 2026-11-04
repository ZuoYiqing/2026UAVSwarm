"""Opt-in read-only Runtime health exporter. No flight POST or MAVLink access."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import time

from uav_runtime.http.telemetry_evidence import PATH, VALID_MS
from uav_runtime.platform.contract import PlatformError, canonical, timestamp
from uav_runtime.platform.transport import JsonClient


def export_once(client, destination: Path, *, scene_id: str, run_id: str):
    code, payload = client.request("GET", PATH)
    if (code != 200 or payload.get("contract_version") != "1.0" or payload.get("scene_id") != scene_id
            or payload.get("run_id") != run_id or payload.get("valid_for_ms") != VALID_MS
            or payload.get("execution_authorized") is not False or payload.get("flight_command_sent") is not False):
        raise PlatformError("runtime_telemetry_binding_mismatch")
    timestamp(payload.get("source_timestamp"))
    rows = payload.get("vehicles")
    if (not isinstance(rows, list) or len(rows) != 3 or any(not isinstance(row, dict) for row in rows)
            or {row.get("node_id") for row in rows} != {"UAV-01", "UAV-02", "UAV-03"}
            or any(type(row.get(flag)) is not bool for row in rows for flag in ("heartbeat_fresh", "telemetry_fresh"))):
        raise PlatformError("runtime_telemetry_nodes_invalid")
    data = canonical(payload)  # Finite JSON; preserve all source/sample times verbatim.
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=destination.name + ".", suffix=".tmp", delete=False) as out:
            temporary = Path(out.name)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()  # Only this invocation's owned temporary file.
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--interval", type=float, default=0, help="0=once; 0.5 recommended for live dynamic telemetry")
    args = parser.parse_args(argv)
    if args.interval != 0 and not 0.1 <= args.interval <= 2:
        parser.error("--interval must be 0 or between 0.1 and 2 seconds")
    client = JsonClient(args.url, timeout=1, max_bytes=1024 * 1024)
    try:
        while True:
            try:
                export_once(client, args.output, scene_id=args.scene_id, run_id=args.run_id)
            except Exception as exc:
                print(f"runtime telemetry export failed: {type(exc).__name__}", file=sys.stderr)
                if not args.interval:
                    return 1
                # Keep old source age on failure. No synthetic fresh/unknown envelope.
            if not args.interval:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
