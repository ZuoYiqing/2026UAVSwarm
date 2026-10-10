#!/usr/bin/env python3
"""直连 MAVLink 读三台的实时 armed/mode/位置，输出**一行 JSON**。

为什么单独成一个文件：它原先是以 heredoc 内嵌在别的脚本里的
（`python3 - <<'PYEOF'`），那种写法在 `wsl.exe -e bash -c '...'` 的嵌套引号里
会静默失败 —— 返回空输出，于是调用方把「读不到」当成了「飞机没落地」，
得出一个**看起来很像真的**错误结论。独立成文件就没有这个问题。

**输出约定**（调用方必须按这个约定判定）：
    {"UAV-01": {"armed": false, "mode": "LOITER", "alt": 0.02, "n": 23.5, "e": 0.3}, ...}
若某台读不到，该台的 `armed`/`alt` 等为 `null`。

⚠️ **`null` 表示"读不到"，不表示"没落地"。** 调用方在字段为 null 时
必须报 `unknown`，**不得**判定为失败或成功 —— 把缺失当否定是本项目
反复踩过的那类错误。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/2026UAVSwarm/simulation/px4_gazebo")

import harness  # noqa: E402
from pymavlink import mavutil  # noqa: E402

MANIFEST = Path("/mnt/d/2026UAVSwarm/simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json")


def main() -> int:
    manifest = harness.load_manifest(MANIFEST)
    out: dict[str, dict] = {}
    for vehicle in manifest["vehicles"]:
        node = vehicle["node_id"]
        row: dict[str, object] = {"armed": None, "mode": None, "alt": None, "n": None, "e": None}
        conn = None
        try:
            port = 14540 + int(vehicle["px4_instance"])
            conn = mavutil.mavlink_connection(f"udpin:127.0.0.1:{port}", source_system=250, timeout=6)
            hb = conn.wait_heartbeat(timeout=8)
            if hb is not None:
                row["armed"] = bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                row["mode"] = mavutil.mode_string_v10(hb)
            position = None
            for _ in range(10):
                msg = conn.recv_match(type="LOCAL_POSITION_NED", blocking=True, timeout=1.5)
                if msg is not None:
                    position = msg
            if position is not None:
                row["alt"] = round(-position.z, 3)
                row["n"] = round(position.x, 2)
                row["e"] = round(position.y, 2)
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}:{exc}"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
        out[node] = row
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
