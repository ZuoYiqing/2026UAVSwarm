#!/usr/bin/env python3
"""连续采样 UAV-01 的高度，判断它是在下降还是停住了。

为什么必须查：`armed=False` 但离地 9.95 m 是个必须解释的组合。
两种可能的处置完全不同：
  · 在下降 → 等它落地即可
  · 停住了 → 那是悬停且已 disarm，属于异常状态，要立刻处理

**不能靠"看起来在变"下结论**，要看时间序列。
"""
from __future__ import annotations

import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, "/mnt/d/2026UAVSwarm/simulation/px4_gazebo")
import harness  # noqa: E402
from pymavlink import mavutil  # noqa: E402

from pathlib import Path

manifest = harness.load_manifest(
    Path("/mnt/d/2026UAVSwarm/simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json")
)
vehicle = manifest["vehicles"][0]  # UAV-01
endpoint = f"udpin:127.0.0.1:{14540 + int(vehicle['px4_instance'])}"

conn = mavutil.mavlink_connection(endpoint, source_system=250, timeout=8)
conn.wait_heartbeat(timeout=10)

print("  采样 UAV-01 的高度（每 1 秒一次，共 12 次）")
print(f"  {'时刻':>6}  {'高度 m':>9}  {'北':>8}  {'东':>8}  {'armed':>6}  模式")
samples = []
start = time.monotonic()
for index in range(12):
    deadline = time.monotonic() + 1.0
    got = None
    while time.monotonic() < deadline:
        msg = conn.recv_match(type="LOCAL_POSITION_NED", blocking=True, timeout=0.5)
        if msg is not None:
            got = msg
    hb = conn.messages.get("HEARTBEAT")
    armed = bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) if hb else None
    mode = mavutil.mode_string_v10(hb) if hb else "?"
    if got is None:
        print(f"  {index:>5}s   （没有位置样本）")
        continue
    alt = -got.z
    samples.append(alt)
    print(f"  {index:>5}s  {alt:>9.2f}  {got.x:>8.2f}  {got.y:>8.2f}  {str(armed):>6}  {mode}")
conn.close()

print()
if len(samples) >= 4:
    deltas = [samples[i + 1] - samples[i] for i in range(len(samples) - 1)]
    avg = sum(deltas) / len(deltas)
    print(f"  高度变化: 首 {samples[0]:.2f} → 末 {samples[-1]:.2f}   平均 {avg:+.3f} m/s")
    if avg < -0.3:
        print("  → ✅ 在持续下降")
    elif abs(avg) <= 0.3 and abs(samples[-1]) > 1.0:
        print("  → ⚠️ 高度基本不变且离地 —— **悬停中，需要处理**")
    elif abs(samples[-1]) <= 0.5:
        print("  → ✅ 已在地面附近")
else:
    print("  ⚠️ 样本不足，无法判断趋势")
