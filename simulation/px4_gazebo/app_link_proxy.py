"""Loopback TCP fault boundary for ground Runtime <-> one platform Agent.

Only the application stream passes through this proxy. PX4 MAVLink and Gazebo
sensor transport must never use its listen/target ports. Payloads, including
Bearer authorization, are forwarded without interpretation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any


MODES = {"up", "down", "delay"}
MAX_DELAY_MS = 2000
MAVLINK_PORTS = {14540, 14541, 14542}


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535 or port in MAVLINK_PORTS:
        raise argparse.ArgumentTypeError("application_port_invalid_or_mavlink_reserved")
    return port


def read_state(path: Path, run_id: str) -> dict[str, Any]:
    """A missing, malformed or cross-run control file means the link is down."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mode = data["mode"]
        delay_ms = data["delay_ms"]
        if (not isinstance(data, dict) or data.get("version") != "1.0"
                or data.get("run_id") != run_id or mode not in MODES
                or type(delay_ms) is not int or not 0 <= delay_ms <= MAX_DELAY_MS
                or (mode == "delay" and delay_ms == 0)
                or (mode != "delay" and delay_ms != 0)):
            raise ValueError("link_state_invalid")
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return {"version": "1.0", "run_id": run_id, "mode": "down", "delay_ms": 0}


def set_state(path: Path, *, run_id: str, mode: str, delay_ms: int = 0) -> dict[str, Any]:
    if not run_id or mode not in MODES or type(delay_ms) is not int or not 0 <= delay_ms <= MAX_DELAY_MS:
        raise ValueError("link_control_invalid")
    if (mode == "delay") != (delay_ms > 0):
        raise ValueError("link_delay_mismatch")
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("run_id") != run_id:
            raise ValueError("link_run_id_mismatch")
        generation = int(existing["generation"]) + 1
    else:
        generation = 1
    result = {"version": "1.0", "run_id": run_id, "generation": generation,
              "mode": mode, "delay_ms": delay_ms}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return result


class ApplicationLinkProxy:
    def __init__(self, *, state_path: Path, run_id: str, listen_port: int, target_port: int):
        if (not run_id or listen_port == target_port or listen_port in MAVLINK_PORTS
                or target_port in MAVLINK_PORTS):
            raise ValueError("application_link_must_not_use_mavlink_port")
        self.state_path = state_path
        self.run_id = run_id
        self.listen_port = listen_port
        self.target_port = target_port
        self.server: asyncio.AbstractServer | None = None
        self._connections: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._connect, "127.0.0.1", self.listen_port)

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        for task in list(self._connections):
            task.cancel()
        if self._connections:
            await asyncio.gather(*self._connections, return_exceptions=True)

    async def _pump(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(65536):
            state = read_state(self.state_path, self.run_id)
            if state["mode"] == "down":
                return
            if state["mode"] == "delay":
                await asyncio.sleep(state["delay_ms"] / 1000)
            if read_state(self.state_path, self.run_id)["mode"] == "down":
                return
            writer.write(data)
            await writer.drain()

    async def _watch_cut(self) -> None:
        while read_state(self.state_path, self.run_id)["mode"] != "down":
            await asyncio.sleep(.05)

    async def _connect(self, client_reader: asyncio.StreamReader,
                       client_writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        server_writer: asyncio.StreamWriter | None = None
        workers: list[asyncio.Task[Any]] = []
        try:
            if read_state(self.state_path, self.run_id)["mode"] == "down":
                return
            server_reader, server_writer = await asyncio.open_connection("127.0.0.1", self.target_port)
            workers = [
                asyncio.create_task(self._pump(client_reader, server_writer)),
                asyncio.create_task(self._pump(server_reader, client_writer)),
                asyncio.create_task(self._watch_cut()),
            ]
            await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
        except (OSError, ConnectionError):
            pass
        finally:
            for worker in workers:
                worker.cancel()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            client_writer.close()
            if server_writer is not None:
                server_writer.close()
            await asyncio.gather(
                client_writer.wait_closed(),
                *( [server_writer.wait_closed()] if server_writer is not None else []),
                return_exceptions=True,
            )
            if task is not None:
                self._connections.discard(task)


async def serve(*, state_path: Path, run_id: str, listen_port: int, target_port: int) -> None:
    proxy = ApplicationLinkProxy(state_path=state_path, run_id=run_id,
                                 listen_port=listen_port, target_port=target_port)
    await proxy.start()
    try:
        assert proxy.server is not None
        await proxy.server.serve_forever()
    finally:
        await proxy.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--state-path", type=Path, required=True)
    serve_parser.add_argument("--run-id", required=True)
    serve_parser.add_argument("--listen-port", type=_port, required=True)
    serve_parser.add_argument("--target-port", type=_port, required=True)
    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("--state-path", type=Path, required=True)
    set_parser.add_argument("--run-id", required=True)
    set_parser.add_argument("--mode", choices=sorted(MODES), required=True)
    set_parser.add_argument("--delay-ms", type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == "set":
        print(json.dumps(set_state(args.state_path, run_id=args.run_id,
                                   mode=args.mode, delay_ms=args.delay_ms)))
    else:
        asyncio.run(serve(state_path=args.state_path, run_id=args.run_id,
                          listen_port=args.listen_port, target_port=args.target_port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
