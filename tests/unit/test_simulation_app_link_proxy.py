"""Loopback application faults leave MAVLink and sensor ports outside the proxy."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

SIM_DIR = Path("simulation/px4_gazebo").resolve()
sys.path.insert(0, str(SIM_DIR))

import app_link_proxy  # noqa: E402


def test_control_file_is_bound_to_run_and_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "link.json"
    assert app_link_proxy.read_state(path, "run-a")["mode"] == "down"
    first = app_link_proxy.set_state(path, run_id="run-a", mode="up")
    assert first["generation"] == 1
    assert app_link_proxy.read_state(path, "run-b")["mode"] == "down"
    with pytest.raises(ValueError, match="link_run_id_mismatch"):
        app_link_proxy.set_state(path, run_id="run-b", mode="up")
    second = app_link_proxy.set_state(path, run_id="run-a", mode="delay", delay_ms=50)
    assert second["generation"] == 2
    with pytest.raises(ValueError, match="link_delay_mismatch"):
        app_link_proxy.set_state(path, run_id="run-a", mode="delay", delay_ms=0)


def test_mavlink_ports_cannot_be_application_proxy_ports(tmp_path: Path) -> None:
    for listen, target in ((14541, 8766), (8767, 14541), (8766, 8766)):
        with pytest.raises(ValueError, match="application_link_must_not_use_mavlink_port"):
            app_link_proxy.ApplicationLinkProxy(
                state_path=tmp_path / "link.json", run_id="run-a",
                listen_port=listen, target_port=target,
            )


def test_link_cut_closes_existing_stream_and_restore_reconnects(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while data := await reader.read(1024):
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        backend = await asyncio.start_server(echo, "127.0.0.1", 0)
        target_port = backend.sockets[0].getsockname()[1]
        state_path = tmp_path / "link.json"
        app_link_proxy.set_state(state_path, run_id="run-a", mode="up")
        proxy = app_link_proxy.ApplicationLinkProxy(
            state_path=state_path, run_id="run-a", listen_port=0, target_port=target_port,
        )
        await proxy.start()
        assert proxy.server is not None
        listen_port = proxy.server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", listen_port)
            writer.write(b"authorized-task-unchanged")
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(25), 1) == b"authorized-task-unchanged"

            app_link_proxy.set_state(state_path, run_id="run-a", mode="down")
            assert await asyncio.wait_for(reader.read(), 1) == b""
            writer.close()
            await writer.wait_closed()

            blocked_reader, blocked_writer = await asyncio.open_connection("127.0.0.1", listen_port)
            assert await asyncio.wait_for(blocked_reader.read(), 1) == b""
            blocked_writer.close()
            await blocked_writer.wait_closed()

            app_link_proxy.set_state(state_path, run_id="run-a", mode="delay", delay_ms=50)
            reader, writer = await asyncio.open_connection("127.0.0.1", listen_port)
            started = time.monotonic()
            writer.write(b"ok")
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(2), 1) == b"ok"
            assert time.monotonic() - started >= .08  # Both application directions delayed.
            writer.close()
            await writer.wait_closed()
        finally:
            await proxy.close()
            backend.close()
            await backend.wait_closed()

    asyncio.run(scenario())
