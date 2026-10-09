#!/usr/bin/env python3
"""补验 `return-home`：起飞 -> goto 走远 -> hold -> 返航 -> 降落。

为什么单独做：上一次 integrated 验收里 `return_home` 报
`return_home_not_converging`，但那是**测试设计问题** —— 起飞是垂直的，
飞机全程在 home 正上方（`initial_distance_m = 0.108`），
判据"到 home 的距离缩小 ≥ min_progress_m"根本没有可收敛的距离。

这次先 `goto` 把它送出去，再返航，判据才有意义。
顺带把 `goto` 与 `hold_position` 一起再走一遍（一次飞行验三个动作）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

API = "http://127.0.0.1:8765/api"
TARGET = "UAV-01"
#: 往北 30 m —— 明显超过 min_progress_m=5，且不靠近任何建筑（spawn 在原点）
GOTO_NORTH_M = 30.0


def get(path, timeout=15.0):
    with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as reply:
        return json.load(reply)


def post(path, body, timeout=180.0):
    request = urllib.request.Request(
        f"{API}{path}", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status, json.load(reply)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:300]}


def state():
    data = get("/vehicle-snapshot")
    out = {}
    for vehicle in data.get("vehicles", []):
        tele = vehicle.get("telemetry") or {}
        spatial = vehicle.get("spatial") or {}
        raw = (spatial.get("raw_vehicle_local_pose") or {}).get("position_m") or {}
        out[vehicle["id"]] = {
            "armed": tele.get("armed"), "mode": tele.get("mode"),
            "n": raw.get("x"), "e": raw.get("y"),
            "alt": None if raw.get("z") is None else -raw["z"],
            "cal": spatial.get("calibration_status"),
        }
    return out


def show(label):
    snap = state()
    print(f"  {label}")
    for node, row in sorted(snap.items()):
        alt = row["alt"]
        print(f"    {node}  armed={str(row['armed']):5} mode={str(row['mode']):9} "
              f"高={alt if alt is None else round(alt, 2):>6}  "
              f"N={row['n'] if row['n'] is None else round(row['n'], 1):>7} "
              f"E={row['e'] if row['e'] is None else round(row['e'], 1):>7}  {row['cal']}")
    return snap


def publish_calibration():
    print("  发布标定（TTL 只有 60 秒，所以现在发布）…")
    proc = subprocess.run(
        ["wsl.exe", "-e", "bash", "-c",
         "cd /mnt/d/2026UAVSwarm && python3 simulation/px4_gazebo/scripts/"
         "sample_calibration.py --duration 2 --publish-runtime http://127.0.0.1:8765/api"],
        capture_output=True, encoding="utf-8", errors="replace", timeout=120,
    )
    snap = state()
    fresh = all(r["cal"] == "calibrated" for r in snap.values())
    print(f"    标定可用: {fresh}")
    return fresh


def act(label, path, body, timeout=180.0):
    print(f"\n--- {label} ---")
    print(f"  POST {path} {json.dumps(body, ensure_ascii=False)}")
    status, reply = post(path, body, timeout)
    if not isinstance(reply, dict):
        print(f"  ❌ 响应异常 HTTP {status}")
        return False, {}
    print(f"  HTTP {status}  status={reply.get('status')}  result={reply.get('result')!r}")
    print(f"  code={reply.get('code')}  completion_state={reply.get('completion_state')}")
    ev = reply.get("completion_evidence") or {}
    if ev:
        keys = [k for k in ("observed", "samples", "sample_count", "max_altitude_m",
                            "max_drift_m", "tolerance_m", "initial_distance_m",
                            "final_distance_m", "min_distance_m", "arrival_error_m")
                if k in ev]
        print(f"  证据: {json.dumps({k: ev[k] for k in keys}, ensure_ascii=False)}")
    if reply.get("failure_reason"):
        print(f"  ⚠️ failure_reason={reply['failure_reason']}")
    for ack in (reply.get("ack_evidence") or [])[:4]:
        print(f"    ACK {str(ack.get('stage')):18} {ack.get('result_name')}")
    ok = (str(reply.get("status") or "").lower() == "succeeded"
          and reply.get("accepted") is True
          and str(reply.get("result") or "").lower() != "fail")
    return ok, reply


def main() -> int:
    print("=" * 74)
    print("补验 return-home：takeoff -> goto(北 30m) -> hold -> return-home -> land")
    print("=" * 74)

    before = show("初始状态（三台应在地面、未解锁）")
    for node, row in before.items():
        if row["armed"]:
            print(f"\n  ❌ {node} 已解锁，中止。")
            return 2

    if not publish_calibration():
        print("\n  ❌ 标定不可用，中止。")
        return 2
    show("发布标定后")

    results = {}

    ok, _ = act("① takeoff 到 6 米", "/actions/takeoff",
                {"node_id": TARGET, "altitude_m": 6, "observe_timeout_ms": 30000}, 90)
    results["takeoff"] = ok
    if not ok:
        print("\n  ❌ 起飞失败，中止（不在不明确的状态上继续）。")
        return 1

    ok, goto_reply = act(f"② goto 往北 {GOTO_NORTH_M:.0f} 米（离开 home 才有返航可言）",
                         "/actions/goto",
                         {"node_id": TARGET, "north_m": GOTO_NORTH_M, "east_m": 0.0,
                          "down_m": -6.0, "arrival_tolerance_m": 2.0, "hold_s": 0},
                         120)
    results["goto"] = ok
    show("goto 之后（应明显远离原点）")

    ok, _ = act("③ hold-position 保持 4 秒",
                "/actions/hold-position",
                {"node_id": TARGET, "hold_s": 4, "tolerance_m": 3.0, "timeout_s": 30}, 90)
    results["hold-position"] = ok

    ok, rh_reply = act("④ return-home（这次有真实距离可收敛）",
                       "/actions/return-home",
                       {"node_id": TARGET, "timeout_s": 90, "min_progress_m": 5.0}, 180)
    results["return-home"] = ok
    show("return-home 之后（应回到原点附近）")

    ok, _ = act("⑤ land", "/actions/land", {"node_id": TARGET}, 120)
    results["land"] = ok

    after = show("结束状态（三台应在地面、未解锁）")

    print(f"\n{'=' * 74}\n汇总\n{'=' * 74}")
    all_ok = True
    for name, passed in results.items():
        print(f"  {'✅' if passed else '❌'} {name}")
        all_ok = all_ok and passed

    print(f"\n  隔离性检查:")
    isolated = True
    for node in ("UAV-02", "UAV-03"):
        a, b = before[node], after[node]
        if a["armed"] != b["armed"] or a["mode"] != b["mode"]:
            print(f"    ⚠️ {node} armed/mode 变了")
            isolated = False
        else:
            print(f"    ✅ {node} 未被动过")

    ended_safe = all(not row["armed"] for row in after.values())
    print(f"  {'✅' if ended_safe else '❌'} 三台均已 disarm")

    verdict = all_ok and isolated and ended_safe
    print(f"\n  {'✅ 补验通过' if verdict else '❌ 补验未通过'}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
