#!/usr/bin/env python3
"""Integrated 验收（真飞）：HTTP -> Policy Gate -> MAVLink -> PX4。

为什么单独写脚本而不是一串 curl：
  · 每步之间要等状态，还要把**证据**（policy 决策、ACK、完成证据）抓下来；
  · 三台必须互相隔离 —— 要断言"只动了目标机，另两台纹丝不动"；
  · 出问题时要在同一份输出里看到"哪一步、什么状态"，而不是靠回翻终端。

做的是 runbook 认可的序列：
  1) 前置：三台在地面、未解锁、标定可用
  2) smoke-takeoff（ARM → 起飞 → 观察高度 → 自动降落）—— 基线，验整条链
  3) takeoff -> hold-position -> return-home -> land —— 验三个新动作
  4) 每步之后核对：policy 决策存在、ACK 是真实结果、没有 stub 记录
  5) 始终核对另两台未被触碰
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

API = "http://127.0.0.1:8765/api"
TARGET = "UAV-01"
OTHERS = ("UAV-02", "UAV-03")


def get(path: str, timeout: float = 15.0):
    with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as reply:
        return json.load(reply)


def post(path: str, body: dict, timeout: float = 120.0):
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{API}{path}", data=payload, method="POST",
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
            return exc.code, {"raw": raw[:400]}


def snapshot() -> dict:
    data = get("/vehicle-snapshot")
    out = {}
    for vehicle in data.get("vehicles", []):
        tele = vehicle.get("telemetry") or {}
        spatial = vehicle.get("spatial") or {}
        raw = (spatial.get("raw_vehicle_local_pose") or {}).get("position_m") or {}
        out[vehicle["id"]] = {
            "armed": tele.get("armed"),
            "mode": tele.get("mode"),
            "alt_m": None if raw.get("z") is None else round(-raw["z"], 2),
            "cal": spatial.get("calibration_status"),
            "usable": spatial.get("public_position_usable"),
        }
    return out


def show_snapshot(label: str) -> dict:
    state = snapshot()
    print(f"  {label}")
    for node, row in sorted(state.items()):
        print(
            f"    {node}  armed={str(row['armed']):5} mode={str(row['mode']):9} "
            f"高={row['alt_m'] if row['alt_m'] is not None else '--':>6}  "
            f"标定={row['cal']} 可用={row['usable']}"
        )
    return state


def run_action(name: str, path: str, body: dict, budget_s: float) -> dict:
    """发一个动作，并**从 POST 响应本身**判定结果。

    ⚠️ 踩过的坑：这里原先写的是"POST 拿 action_id，再轮询
    `/api/actions/{id}` 直到终态"。实际上这个 API 是**同步**的 —— POST 的响应
    就是最终结果（含 `status` / `result` / `completion_evidence` / `ack_evidence`），
    没有任何待轮询的东西。于是轮询拿到空对象，脚本把**三次成功**误报成三次失败，
    尽管它们的结果码是 `px4_sitl_action_pass`。

    教训：判定必须读**响应里实际存在的字段**，而不是我以为存在的。
    `budget_s` 保留为 HTTP 超时（动作是阻塞的，真飞要等）。
    """
    print(f"\n{'=' * 74}\n{name}\n{'=' * 74}")
    print(f"  POST {path}  {json.dumps(body, ensure_ascii=False)}")
    status, reply = post(path, body, timeout=budget_s)
    print(f"  HTTP {status}")
    if not isinstance(reply, dict):
        print(f"  ❌ 响应不是对象: {str(reply)[:200]}")
        return {"ok": False, "reply": reply}
    if status >= 400:
        print(f"  ❌ 被拒: {json.dumps(reply, ensure_ascii=False)[:400]}")
        return {"ok": False, "reply": reply}

    print(f"  action_id : {reply.get('action_id')}")
    print(f"  status    : {reply.get('status')}   result: {reply.get('result')!r}")
    print(f"  code      : {reply.get('code')}")

    evidence = reply.get("completion_evidence") or reply.get("altitude_observation")
    if evidence:
        keys = ("observed", "samples", "sample_count", "max_altitude_m",
                "last_z", "max_drift_m", "tolerance_m", "final_distance_m",
                "min_distance_m", "initial_distance_m")
        brief = {k: evidence[k] for k in keys if k in evidence}
        print(f"  完成证据  : {json.dumps(brief, ensure_ascii=False)}")
    if reply.get("completion_state"):
        print(f"  completion_state: {reply['completion_state']}")
    if reply.get("failure_reason"):
        print(f"  ⚠️ failure_reason: {reply['failure_reason']}")

    acks = reply.get("ack_evidence") or []
    if acks:
        print(f"  ACK ({len(acks)} 条):")
        for ack in acks:
            print(f"    {str(ack.get('stage')):22} {str(ack.get('command_name')):32} "
                  f"{ack.get('result_name')}")

    policy = reply.get("policy_decision") or {}
    if policy:
        print(f"  Policy    : {policy.get('decision_code') or policy.get('decision') or '(有决策事件)'}")

    # 判定读**响应里的** status / accepted / result。
    ok = (
        str(reply.get("status") or "").lower() == "succeeded"
        and reply.get("accepted") is True
        and str(reply.get("result") or "").lower() != "fail"
    )
    return {"ok": ok, "reply": reply}


def publish_calibration(duration_s: float = 3.0) -> bool:
    """发布一次坐标标定，并确认 Runtime 收到。

    为什么脚本自己发布而不是要求操作者先跑：标定的 **TTL 只有 60 秒**
    （`calibration_valid_for_ms ≈ 59890`）。操作者先发布、再过来跑验收，
    中间那几十秒就把它过期了 —— 于是验收在"标定 stale"上直接拒绝起飞，
    看起来像验收失败，实际只是时序问题。
    所以：**在要飞的那一刻发布**，这本来就是 runbook 的用法（calib-loop 的意义即此）。
    """
    import subprocess

    print("  发布标定（采样 3 秒）…")
    proc = subprocess.run(
        ["wsl.exe", "-e", "bash", "-c",
         "cd /mnt/d/2026UAVSwarm && python3 simulation/px4_gazebo/scripts/"
         f"sample_calibration.py --duration {duration_s} --publish-runtime http://127.0.0.1:8765/api"],
        capture_output=True,
        # ⚠️ 必须显式指定编码与 errors：Windows 上 text=True 默认用 GBK 解码，
        # 而 WSL 输出里有非 GBK 字节时会抛 UnicodeDecodeError，**连带打挂整个脚本**
        # （实测：在读取线程里抛异常，主流程随后拿到不完整的返回值）。
        encoding="utf-8", errors="replace",
        timeout=180,
    )
    tail = (proc.stdout or "").strip().splitlines()
    for line in tail[-3:]:
        print(f"    {line[:220]}")
    if proc.returncode != 0:
        print(f"    ⚠️ 发布进程退出码 {proc.returncode}: {(proc.stderr or '')[:200]}")
    # 确认 Runtime 真的收到了（不能只看发布进程说 PASS）
    observed = snapshot()
    fresh = all(
        row["cal"] == "calibrated" and row["usable"] for row in observed.values()
    )
    for node, row in sorted(observed.items()):
        print(f"    {node}: 标定={row['cal']} 可用={row['usable']}")
    return fresh


def main() -> int:
    print("=" * 74)
    print("Integrated 验收：HTTP -> Policy Gate -> MAVLink -> PX4     目标 UAV-01")
    print("=" * 74)

    health = get("/health")
    print(f"  Runtime health: {health.get('status')} ({health.get('service')})")

    show_snapshot("初始状态")

    # 标定 60 秒就过期，所以在要飞之前发布，而不是指望操作者提前做好。
    print()
    if not publish_calibration():
        print("\n  ❌ 标定无法变为可用，不做真飞。")
        return 2

    before = show_snapshot("前置状态（三台应在地面、未解锁、标定可用）")

    problems = []
    for node, row in before.items():
        if row["armed"]:
            problems.append(f"{node} 已解锁 —— 起手就不是地面状态，中止")
        if row["cal"] != "calibrated" or not row["usable"]:
            problems.append(f"{node} 标定不可用（{row['cal']}）")
    if problems:
        for item in problems:
            print(f"  ⚠️ {item}")
        print("\n  ❌ 前置条件不满足，不做真飞。")
        return 2

    results = {}

    # --- 1) smoke-takeoff：整条链的最短证明 ---
    results["smoke-takeoff"] = run_action(
        "① smoke-takeoff（ARM → 起飞 → 观察高度 → 自动降落）",
        "/actions/smoke-takeoff", {"node_id": TARGET, "altitude_m": 3}, 150,
    )
    show_snapshot("smoke-takeoff 之后")

    # --- 2) takeoff -> hold -> return-home -> land ---
    results["takeoff"] = run_action(
        "② takeoff（正式起飞到 5 米）",
        "/actions/takeoff",
        {"node_id": TARGET, "altitude_m": 5, "observe_timeout_ms": 30000},
        90,
    )
    if results["takeoff"]["ok"]:
        results["hold-position"] = run_action(
            "③ hold-position（原地保持 4 秒，容差 2 米）",
            "/actions/hold-position",
            {"node_id": TARGET, "hold_s": 4, "tolerance_m": 2.0, "timeout_s": 30},
            90,
        )
        results["return-home"] = run_action(
            "④ return-home（返航，要求到 home 的三维距离确实缩小 ≥5 米）",
            "/actions/return-home",
            {"node_id": TARGET, "timeout_s": 60, "min_progress_m": 5.0},
            150,
        )
    else:
        print("\n  ⚠️ takeoff 未成功，跳过 hold / return-home（避免在不明确的状态上继续）")

    results["land"] = run_action(
        "⑤ land（降落并 disarm）", "/actions/land", {"node_id": TARGET}, 120,
    )

    after = show_snapshot("结束状态（三台都应在地面、未解锁）")

    # --- 3) 隔离性：另两台是否被动过 ---
    #
    # ⚠️ 判据不能用"高度数值相等"。实测：静止在地面的载具，物理引擎仍有
    # ±5 cm 的浮点抖动（-0.02 → -0.07），用相等比较会把**没动过的**飞机
    # 报成"变了"。真正的"被动过"是**语义上的**：解锁、离地、模式变化。
    print(f"\n{'=' * 74}\n隔离性（只应动过 {TARGET}）\n{'=' * 74}")
    isolated = True
    for node in OTHERS:
        a, b = before.get(node, {}), after.get(node, {})
        reasons = []
        if a.get("armed") != b.get("armed"):
            reasons.append(f"解锁状态变了 {a.get('armed')} -> {b.get('armed')}")
        if a.get("mode") != b.get("mode"):
            reasons.append(f"模式变了 {a.get('mode')} -> {b.get('mode')}")
        # "离地"用阈值判，容差远大于物理抖动
        for label, row in (("前", a), ("后", b)):
            alt = row.get("alt_m")
            if alt is not None and abs(alt) > 0.5:
                reasons.append(f"{label}次高度 {alt} m 明显离地")
        flag = "⚠️ 被动过" if reasons else "✅ 未被动过"
        print(f"  {node}: armed {a.get('armed')} -> {b.get('armed')}   "
              f"高度 {a.get('alt_m')} -> {b.get('alt_m')}   {flag}")
        for reason in reasons:
            print(f"        {reason}")
        isolated = isolated and not reasons

    # --- 4) 证据链 ---
    print(f"\n{'=' * 74}\n证据链\n{'=' * 74}")
    recent = get("/actions/recent?n=12")
    rows = recent if isinstance(recent, list) else (recent.get("actions") or [])
    rows = rows or []
    print(f"  最近动作 {len(rows)} 条:")
    for row in rows[:12]:
        print(f"    {str(row.get('node_id')):8} {str(row.get('action_type')):16} "
              f"{str(row.get('status')):12} {row.get('created_at') or row.get('timestamp') or ''}")
    stub = [r for r in rows if "stub" in json.dumps(r, ensure_ascii=False).lower()]
    print(f"  含 stub 的记录: {len(stub)}  {'✅' if not stub else '⚠️ 不该出现'}")
    try:
        decisions = get("/policy/decisions?n=8")
        drows = decisions if isinstance(decisions, list) else (decisions.get("decisions") or [])
        print(f"  Policy 决策 {len(drows or [])} 条:")
        for row in (drows or [])[:8]:
            print(f"    {str(row.get('node_id')):8} {str(row.get('action_type') or row.get('action')):16} "
                  f"{str(row.get('decision_code') or row.get('decision') or row.get('outcome'))}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Policy 决策查询失败: {exc}")

    # --- 汇总 ---
    print(f"\n{'=' * 74}\n汇总\n{'=' * 74}")
    ok = True
    for name, result in results.items():
        flag = "✅" if result.get("ok") else "❌"
        reply = result.get("reply") or {}
        status = reply.get("status") or reply.get("code") or "?"
        code = reply.get("code") or ""
        print(f"  {flag} {name:16} {status:12} {code}")
        ok = ok and bool(result.get("ok"))
    print(f"  {'✅' if isolated else '❌'} 隔离性           另两台未被动过")
    print(f"\n  {'✅ integrated 验收通过' if ok and isolated else '❌ integrated 验收未通过'}")
    return 0 if (ok and isolated) else 1


if __name__ == "__main__":
    raise SystemExit(main())
