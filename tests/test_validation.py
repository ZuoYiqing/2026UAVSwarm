import pytest

from uav_runtime.utils.ids import make_agent_id
from uav_runtime.utils.validation import ensure_non_empty, require_keys


def test_make_agent_id() -> None:
    assert make_agent_id(2) == "uav-2"


def test_make_agent_id_invalid() -> None:
    with pytest.raises(ValueError):
        make_agent_id(0)


def test_require_keys() -> None:
    require_keys({"a": 1, "b": 2}, {"a", "b"})


def test_require_keys_missing() -> None:
    with pytest.raises(ValueError):
        require_keys({"a": 1}, {"a", "b"})


def test_ensure_non_empty() -> None:
    ensure_non_empty("x", field="name")


def test_ensure_non_empty_invalid() -> None:
    with pytest.raises(ValueError):
        ensure_non_empty(" ", field="name")
