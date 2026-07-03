from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "px4_sitl_observe.py"
spec = importlib.util.spec_from_file_location("px4_sitl_observe", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
observe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observe)


def test_ned_z_to_altitude_m_for_positive_down_ned() -> None:
    assert observe.ned_z_to_altitude_m(-2.1) == 2.1
    assert observe.ned_z_to_altitude_m(0.0) == 0.0
    assert observe.ned_z_to_altitude_m(0.02) == 0.0


def test_update_local_position_summary_uses_negative_z_for_max_altitude() -> None:
    summary = observe.empty_summary("udpin:127.0.0.1:14540", 30)

    observe.update_local_position_summary(summary, z=0.02, timestamp=1.0)
    observe.update_local_position_summary(summary, z=-2.1, timestamp=2.0)

    assert summary["sample_count"] == 2
    assert summary["first_z"] == 0.02
    assert summary["last_z"] == -2.1
    assert summary["min_z"] == -2.1
    assert summary["max_z"] == 0.02
    assert summary["max_altitude_m"] == 2.1
    assert summary["first_timestamp"] == 1.0
    assert summary["last_timestamp"] == 2.0


def test_observe_parser_defaults_and_output_args() -> None:
    args = observe.build_parser().parse_args([
        "--endpoint",
        "udpin:127.0.0.1:14540",
        "--duration-s",
        "30",
        "--output-json",
        "/tmp/summary.json",
        "--output-csv",
        "/tmp/samples.csv",
    ])

    assert args.endpoint == "udpin:127.0.0.1:14540"
    assert args.duration_s == 30
    assert args.output_json == "/tmp/summary.json"
    assert args.output_csv == "/tmp/samples.csv"
    assert args.include_attitude is False
    assert args.include_global_position is False
