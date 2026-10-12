#!/usr/bin/env python3
"""查三台当前状态 —— 起飞超时后必须确认飞机到底在哪。

为什么不用之前那条命令：
  `telemetry.local_position` 在快照里是空 {}，说明**键名和我假设的不同**。
  与其继续猜，这里先把 `telemetry` 的**真实键名**列出来。
"""
from __future__ import annotations

import json
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

API = "http://127.0.0.1:8765/api"

def get(path, timeout=15):
    with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as r:
        return json.load(r)

print("=" * 68)
print("三台状态")
print("=" * 68)
try:
    snap = get("/vehicle-snapshot")
except Exception as exc:
    print(f"  ❌ 读不到快照: {type(exc).__name__}: {exc}")
    raise SystemExit(1)

for v in snap.get("vehicles") or []:
    print(f"\n  --- {v.get('id')}  connected={v.get('connected')} ---")
    t = v.get("telemetry") or {}
    if not t:
        print("      telemetry 为空")
    else:
        print(f"      键名: {sorted(t.keys())}")
        for k in ("armed", "mode", "flight_mode", "landed_state",
                  "altitude_m", "relative_altitude_m", "system_id", "stale"):
            if k in t:
                print(f"      {k}: {t[k]}")
        # 位置可能在任意一层，全都翻出来
        for k in ("local_position", "position", "global_position", "attitude_deg"):
            val = t.get(k)
            if isinstance(val, dict) and val:
                print(f"      {k}: {json.dumps(val, ensure_ascii=False)}")
            elif val is not None:
                print(f"      {k}: {val}")
    sp = v.get("spatial") or {}
    if sp:
        print(f"      spatial: 标定={sp.get('calibration_status')} usable={sp.get('public_position_usable')}")

print()
print("=" * 68)
print("最近动作（判起飞到底做了什么）")
print("=" * 68)
try:
    rec = get("/actions/recent")
    rows = rec if isinstance(rec, list) else (rec.get("actions") or rec.get("items") or [])
    if not rows:
        print("  （空）  原始键:", sorted(rec.keys()) if isinstance(rec, dict) else type(rec))
    for r in rows[-6:]:
        if not isinstance(r, dict):
            print(f"  {type(r).__name__}: {str(r)[:90]}")
            continue
        print(f"\n  action_id={r.get('action_id')}  键名={sorted(r.keys())[:14]}")
        for k in ("action", "action_type", "status", "result", "failure_reason",
                  "calibration_status", "completion_state", "node_id", "timestamp"):
            if k in r:
                print(f"      {k}: {r[k]}")
        ce = r.get("completion_evidence")
        if isinstance(ce, dict):
            print(f"      completion_evidence: {json.dumps(ce, ensure_ascii=False)[:260]}")
except Exception as exc:
    print(f"  ❌ {type(exc).__name__}: {exc}")
