#!/usr/bin/env python3
"""Measure three local origins without taking ownership of MAVLink endpoints."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calibration import capture_readonly_calibrations
from evidence import atomic_json
from harness import DEFAULT_MANIFEST_PATH, RUNTIME_ROOT, load_manifest, utc_now
from runtime_evidence import publish


#: 仿真启动时把"用的是哪一份 manifest"写在这里。
#: 为什么标定要靠它：**默认 manifest 是无相机那份**，而相机版仿真在世界里的模型名
#: 是 `x500_mono_cam_*`。若不问就按默认去找 `x500_*` 的位姿，会报
#: `gazebo_model_pose_missing` —— 一个看起来像"位姿丢了"、实际是"配置拿错了"的错。
#: 这个信息在启动时就已经写下，所以**读它，而不是要求调用方记住传参**。
STATE_PATH = RUNTIME_ROOT / "harness_state.json"


def resolve_manifest_path(
    explicit: Path | None,
    *,
    state_path: Path | None = None,
) -> Path:
    """决定用哪一份 manifest。

    优先级：**显式传入** > **harness state 记的那一份** > **默认值**。

    `explicit` 永远优先 —— 否则"我要标定另一份配置"这个正当需求就无法表达。
    state 读不出来（不存在 / 损坏 / 没有该字段）时退回默认值而**不抛异常**：
    本函数的职责只是挑一份配置，它的失败模式应当是"退回默认，
    让下游的仿真就绪检查去报真正的问题"。
    """
    if explicit is not None:
        return Path(explicit)
    path = STATE_PATH if state_path is None else state_path
    try:
        recorded = json.loads(Path(path).read_text(encoding="utf-8")).get("manifest_path")
    except (OSError, ValueError, AttributeError):
        recorded = None
    if recorded:
        return Path(str(recorded))
    return DEFAULT_MANIFEST_PATH


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="manifest 路径；省略时自动采用 harness state 里记录的、当前正在跑的那一份",
    )
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=RUNTIME_ROOT / "calibration/latest.json")
    parser.add_argument("--publish-runtime", help="Existing loopback API base; only calibration evidence is posted")
    args = parser.parse_args(argv)
    config = resolve_manifest_path(args.config)
    if not 2 <= args.duration <= 10:
        parser.error("duration must be between 2 and 10 seconds")
    try:
        calibrations = capture_readonly_calibrations(load_manifest(config), duration_s=args.duration)
        publications = [publish(args.publish_runtime, row, kind="calibration") for row in calibrations] if args.publish_runtime else []
        payload = {"status": "PASS", "mode": "read_only_no_mavlink", "checked_at": utc_now(),
                   "manifest_path": str(config),
                   "calibrations": calibrations, "publications": publications}
    except Exception as exc:
        payload = {"status": "FAIL", "checked_at": utc_now(), "manifest_path": str(config),
                   "error": f"{type(exc).__name__}:{exc}"}
    atomic_json(args.output, payload)
    print(json.dumps({k: v for k, v in payload.items() if k != "calibrations"}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
