#!/usr/bin/env python3
"""核实三方提出的关键问题：**PX4 记录的 HOME_POSITION 在哪里，是否等于降落点？**

为什么值得查
------------
Runtime 负责人在三方讨论里提出（另外两方同意）：

> RETURN_HOME 准入不要求已靠近 pad，但**必须核验 PX4 HOME_POSITION 与目标 pad 一致**，
> 因为 RTL 可能自行降落。

三条线索都指向同一件事：

· `RETURN_HOME` 发的是**进入 RTL**，而 RTL 语义是"回 **PX4 自己的 home**"
· "完成"判据用的是 **calibration 的 scene_ned 中心**（站点几何），**不是 PX4 home**
· 屋顶事故的完整链条正是：**位置未到站** → 报返航成功 → `LAND` →
  PX4 在"当前位置正下方"降落 → 那是屋顶

**所以"要求到达 A、而飞机去了 B，却只看 A"是这起事故的结构。**
本脚本回答：**A 与 B 在实测里是不是同一个点。**

做法：直连 MAVLink 读 `HOME_POSITION`（不抢 Runtime 的口——只读遥测）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/d/2026UAVSwarm/simulation/px4_gazebo")

import harness  # noqa: E402
from pymavlink import mavutil  # noqa: E402

MANIFEST = Path("/mnt/d/2026UAVSwarm/simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json")


def read_home(conn) -> dict:
    """读 HOME_POSITION 与当前位置。

    HOME_POSITION (msg 242) 字段：
        latitude/longitude (deg*1e7), altitude (mm, AMSL), local_x/y/z (m, NED)
    local_x/y/z 是我们关心的 —— 它就是 RTL 要回去的点（相对 EKF 原点）。
    """
    home = None
    pos = None
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        msg = conn.recv_match(blocking=True, timeout=1.5)
        if msg is None:
            continue
        kind = msg.get_type()
        if kind == "HOME_POSITION":
            home = msg
        elif kind == "LOCAL_POSITION_NED":
            pos = msg
        if home is not None and pos is not None:
            break
    out = {}
    if home is not None:
        out["home"] = {
            "local_north_m": getattr(home, "local_x", None),
            "local_east_m": getattr(home, "local_y", None),
            "local_down_m": getattr(home, "local_z", None),
            "lat_deg": (getattr(home, "latitude", 0) or 0) / 1e7,
            "lon_deg": (getattr(home, "longitude", 0) or 0) / 1e7,
            "alt_mm": getattr(home, "altitude", None),
        }
    if pos is not None:
        out["current"] = {
            "north_m": round(pos.x, 3),
            "east_m": round(pos.y, 3),
            "down_m": round(pos.z, 3),
        }
    return out


def main() -> int:
    manifest = harness.load_manifest(MANIFEST)
    print("=" * 74)
    print("PX4 HOME_POSITION vs 站点几何（calibration scene_ned 中心）")
    print("=" * 74)

    # 站点几何来自 calibration（仿真侧采样得到的 scene_ned 平移）
    calib = {}
    cal_path = Path("/mnt/d/2026UAVSwarm/.runtime/px4_gazebo/calibration/latest.json")
    if cal_path.is_file():
        try:
            data = json.loads(cal_path.read_text(encoding="utf-8"))
            for row in data.get("calibrations") or []:
                calib[row.get("node_id")] = row
        except (OSError, ValueError) as exc:
            print(f"  ⚠️ 读 calibration 失败: {exc}")

    spawns = {v["node_id"]: v.get("spawn_ned") for v in manifest["vehicles"]}

    for vehicle in manifest["vehicles"]:
        node = vehicle["node_id"]
        port = 14540 + int(vehicle["px4_instance"])
        print(f"\n  --- {node}（udpin:127.0.0.1:{port}）---")
        conn = None
        try:
            conn = mavutil.mavlink_connection(f"udpin:127.0.0.1:{port}",
                                              source_system=250, timeout=6)
            hb = conn.wait_heartbeat(timeout=8)
            if hb is None:
                print("    ❌ 收不到心跳")
                continue
            data = read_home(conn)
        except Exception as exc:  # noqa: BLE001
            print(f"    ❌ {type(exc).__name__}: {exc}")
            continue
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

        home = data.get("home")
        current = data.get("current")
        if home:
            print(f"    PX4 HOME (local NED) : N={home['local_north_m']} "
                  f"E={home['local_east_m']} D={home['local_down_m']}")
            print(f"    PX4 HOME (lat/lon)   : {home['lat_deg']:.7f}, {home['lon_deg']:.7f}"
                  f"  alt={home['alt_mm']}mm")
        else:
            print("    ⚠️ 没收到 HOME_POSITION 消息")
        if current:
            print(f"    当前位置 (local NED) : N={current['north_m']} "
                  f"E={current['east_m']} D={current['down_m']}")

        spawn = spawns.get(node) or {}
        print(f"    manifest spawn_ned   : N={spawn.get('x_m')} E={spawn.get('y_m')} "
              f"D={spawn.get('z_m')}")

        row = calib.get(node) or {}
        trans = row.get("translation_scene_ned_m") or {}
        if trans:
            # scene_ned = vehicle_local_ned + translation
            print(f"    calibration 平移     : N={trans.get('north'):.4f} "
                  f"E={trans.get('east'):.4f} D={trans.get('down'):.4f}")
            if home and home.get("local_north_m") is not None:
                hx, hy = float(home["local_north_m"]), float(home["local_east_m"])
                # PX4 home 换算到 scene_ned
                sx = hx + float(trans["north"])
                sy = hy + float(trans["east"])
                print(f"    → PX4 HOME 在 scene_ned: N={sx:.3f} E={sy:.3f}")
                # 站点中心（几何）= spawn（三个 pad 的中心就是 spawn 点）
                cx, cy = float(spawn.get("x_m", 0)), float(spawn.get("y_m", 0))
                dist = ((sx - cx) ** 2 + (sy - cy) ** 2) ** 0.5
                print(f"    → 站点中心 (spawn)     : N={cx:.3f} E={cy:.3f}")
                print(f"    → **水平差 {dist:.3f} m**"
                      f"  {'✅ 一致' if dist < 0.75 else '⚠️ 不一致（超过候选容差 0.75 m）'}")
        else:
            print("    （没有 calibration 数据，无法换算到 scene_ned）")

    print()
    print("=" * 74)
    print("判读")
    print("=" * 74)
    print("  · RTL 回的是 **PX4 的 HOME_POSITION**，不是 calibration 的站点中心。")
    print("  · 所以两者不一致时，'要求到达 A、飞机去了 B' 是结构性的 ——")
    print("    而在拿到站点证据之前，判据只看 A，看不出飞机去了 B。")
    print("  · 这正是三方要求'RETURN_HOME 准入时核验 HOME_POSITION 与目标 pad 一致'的原因。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
