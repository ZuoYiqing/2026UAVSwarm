from __future__ import annotations

from pathlib import Path

import pytest

from uav_runtime.core.mission import Mission
from uav_runtime.core.scene import Scene


_REPOSITORY_AUDIT_PATH = (
    Path(__file__).resolve().parents[1] / "audit" / "runtime.audit.jsonl"
)


def _audit_file_state() -> tuple[bool, bytes]:
    if not _REPOSITORY_AUDIT_PATH.exists():
        return False, b""
    return True, _REPOSITORY_AUDIT_PATH.read_bytes()


@pytest.fixture(scope="session", autouse=True)
def repository_audit_must_remain_unchanged():  # type: ignore[no-untyped-def]
    """Turn any test write to the Git-managed audit log into a suite failure."""
    before = _audit_file_state()
    yield
    after = _audit_file_state()
    assert after == before, (
        "pytest modified the repository audit/runtime.audit.jsonl; "
        "all test audit output must use tmp_path"
    )


@pytest.fixture(autouse=True)
def isolate_runtime_audit(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """No pytest path may append to the formal repository audit JSONL."""
    audit_path = tmp_path / "audit" / "runtime.audit.jsonl"
    monkeypatch.setenv("UAV_RUNTIME_AUDIT_PATH", str(audit_path))
    # Routes is imported during collection by several test modules, before this
    # fixture can set the environment.  Redirect that already-bound constant too.
    import uav_runtime.http.routes as routes

    monkeypatch.setattr(routes, "AUDIT_PATH", str(audit_path))
    yield audit_path


@pytest.fixture
def demo_mission() -> Mission:
    return Mission(name="demo", goals=["search"])


@pytest.fixture
def demo_scene() -> Scene:
    return Scene(area=(30, 30), agents=3, obstacles=[])
