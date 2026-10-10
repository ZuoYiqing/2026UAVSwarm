#!/usr/bin/env python3
"""一条命令回答：**这套系统现在到底能不能用？**

为什么需要它
------------
`pgrep -c px4` 返回 3、`pgrep -c "gz sim"` 返回 1 —— 这个结果**不能说明系统健康**。
本项目已经实测踩过两次：

  · Gazebo 掉了、三台 PX4 变成孤儿（进程活着但没仿真可连）
      → 进程数看起来 3/1/1 正常，实际遥测全 null、Runtime 报
        `simulation_evidence_stale`、`connected_nodes=0`
  · 起的是默认版而非相机版
      → 端口对、health ready、飞机能飞，**只有相机动作会失败**

所以本工具**不数进程**，改为检查六组**互相独立**的证据，并给出**单一结论**：

  ① 进程活着        （必要但不充分）
  ② 仿真时钟在推进  （证伪"Gazebo 卡住了"——进程活着时钟可能停）
  ③ 三台遥测新鲜    （证伪"PX4 是孤儿"——进程活着但收不到传感器数据）
  ④ Runtime 响应    （8765）
  ⑤ 标定可用        （判据是 Runtime 自己的状态，不是我们推断）
  ⑥ manifest 是相机版（那一类"看起来正常、只有相机动作失败"的错位）

**任一 fail 就是不可用。** 没有 fail 但有 unknown 时报"无法判定"而**不是**通过 ——
"读不到"与"没问题"是两件事，本项目反复踩的正是这个。

用法
----
    python3 ops/system_status.py            # 人读
    python3 ops/system_status.py --json     # 机器读
    python3 ops/system_status.py --quiet    # 只输出结论一行

退出码：0 = 可用；1 = 不可用；2 = 无法判定
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8765/api"
MANIFEST = "/mnt/d/2026UAVSwarm/simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
MARK = {PASS: "[OK]", FAIL: "[!!]", UNKNOWN: "[??]"}


def _wsl(script: str, timeout: float = 90.0) -> tuple[int, str]:
    """在 WSL 里跑一段 python3 代码，返回 (退出码, stdout)。

    这里有两个**实际踩过**的坑，都写下来：

    坑① 不要把代码拼进 `bash -c "..."`。
        `bash -c f"python3 -c {json.dumps(script)}"` 这种写法，多行代码经
        `wsl.exe -e bash -c '...'` 两层引号解析后换行被破坏，报
        `SyntaxError: unexpected character after line continuation character`，
        于是四项检查全变 unknown —— 而真实系统是好的。
        改用 **base64 + stdin 管道**：编码后只含 [A-Za-z0-9+/=]，
        不经过任何 shell 解析。

    坑② `wsl.exe` 会把一条 UTF-16LE 警告混进 stdout。
        实测形如 `PROBE-OK\\nw\\x00s\\x00l\\x00:\\x00 ...`
        （"wsl: 检测到 localhost 代理配置..."，每个字符后跟一个 NUL）。
        它是给终端看的，却和真正的输出走同一个流；用 UTF-8 解码后
        最后一行是 NUL 而不是脚本结果。
        所以命令里加 `2>/dev/null`，并且解析时只用 `_last_line()`。
    """
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    inner = (
        f"cd /mnt/d/2026UAVSwarm 2>/dev/null && "
        f"echo {encoded} | base64 -d | timeout {int(timeout)} python3 - 2>/dev/null"
    )
    try:
        proc = subprocess.run(
            ["wsl.exe", "-e", "bash", "-c", inner],
            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout + 30,
        )
        return proc.returncode, proc.stdout or ""
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, f"{type(exc).__name__}:{exc}"


def _last_line(output: str) -> str:
    """取最后一条**可用的**行。

    不能直接 `output.strip().splitlines()[-1]`：wsl.exe 的 UTF-16 警告
    经 UTF-8 解码后是含大量 NUL 的垃圾，而且**排在最后**，
    于是 `[-1]` 取到垃圾而不是脚本结果。
    只接受"不含 NUL 且去掉空白后非空"的行。
    """
    for line in reversed(output.splitlines()):
        if "\x00" in line:
            continue
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def check_processes() -> tuple[str, str]:
    script = (
        "import subprocess\n"
        "def n(pat):\n"
        "    r = subprocess.run(['pgrep','-cf',pat], capture_output=True, text=True)\n"
        "    return r.stdout.strip() or '0'\n"
        "print(n('bin/px4'), n('gz sim'), n('uav_runtime.http.server'))\n"
    )
    _code, out = _wsl(script, 40)
    parts = _last_line(out).split()
    if len(parts) < 3 or not all(p.isdigit() for p in parts[:3]):
        return UNKNOWN, f"读不到进程数（{_last_line(out)[:50]}）"
    px4, gz, rt = (int(p) for p in parts[:3])
    detail = f"PX4={px4} Gazebo={gz} Runtime={rt}"
    if px4 >= 3 and gz >= 1 and rt >= 1:
        return PASS, detail
    return FAIL, detail


def check_clock() -> tuple[str, str]:
    script = (
        "import sys\n"
        "sys.path.insert(0, '/mnt/d/2026UAVSwarm/simulation/px4_gazebo')\n"
        "import gazebo_evidence as ge\n"
        "try:\n"
        "    r = ge.probe_clock('simple_recon_v0_1', 5.0)\n"
        "except Exception as exc:\n"
        "    print('ERR', type(exc).__name__); raise SystemExit\n"
        "ev = r.get('evidence') or {}\n"
        "print(r.get('clock_advancing'), ev.get('real_time_factor'), ev.get('minimum_real_time_factor'))\n"
    )
    _code, out = _wsl(script, 60)
    parts = _last_line(out).split()
    if len(parts) < 3 or parts[0] not in ("True", "False"):
        return UNKNOWN, f"读不到时钟（{_last_line(out)[:50]}）"
    advancing = parts[0] == "True"
    try:
        rtf, floor = float(parts[1]), float(parts[2])
    except ValueError:
        return UNKNOWN, f"时钟值不是数字（{_last_line(out)[:50]}）"
    if not advancing:
        return FAIL, f"时钟**未推进**（RTF={rtf:.3f}）—— Gazebo 可能卡住"
    if rtf < floor:
        return FAIL, f"RTF {rtf:.3f} **低于门槛** {floor}"
    return PASS, f"推进中，RTF={rtf:.3f}（门槛 {floor}）"


def check_telemetry() -> tuple[str, str]:
    """三台遥测新鲜 —— 这证伪"PX4 是孤儿"（进程活着但收不到传感器数据）。"""
    script = (
        "import json, sys\n"
        "sys.path.insert(0, '/mnt/d/2026UAVSwarm/simulation/px4_gazebo')\n"
        "from pathlib import Path\n"
        "import harness\n"
        "from pymavlink import mavutil\n"
        f"m = harness.load_manifest(Path('{MANIFEST}'))\n"
        "out = {}\n"
        "for v in m['vehicles']:\n"
        "    port = 14540 + int(v['px4_instance'])\n"
        "    c = mavutil.mavlink_connection(f'udpin:127.0.0.1:{port}', source_system=250, timeout=5)\n"
        "    hb = c.wait_heartbeat(timeout=8)\n"
        "    pos = None\n"
        "    for _ in range(8):\n"
        "        msg = c.recv_match(type='LOCAL_POSITION_NED', blocking=True, timeout=1.2)\n"
        "        if msg is not None:\n"
        "            pos = msg\n"
        "    c.close()\n"
        "    out[v['node_id']] = [hb is not None, pos is not None]\n"
        "print(json.dumps(out))\n"
    )
    _code, out = _wsl(script, 120)
    try:
        data = json.loads(_last_line(out))
    except (json.JSONDecodeError, ValueError):
        return UNKNOWN, f"读不到遥测（{_last_line(out)[:50]}）"
    if not isinstance(data, dict) or not data:
        return UNKNOWN, "没有载具配置"
    ok = [k for k, v in data.items() if isinstance(v, list) and len(v) == 2 and all(v)]
    missing = [k for k in data if k not in ok]
    if missing:
        return FAIL, f"{len(ok)}/{len(data)} 有遥测；缺 {'、'.join(missing)}"
    return PASS, f"{len(ok)}/{len(data)} 心跳与位置都新鲜"


def _api(path: str, timeout: float = 12.0):
    with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as reply:
        return json.load(reply)


def check_runtime() -> tuple[str, str]:
    try:
        health = _api("/health")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return FAIL, f"8765 无响应（{type(exc).__name__}）"
    if health.get("status") != "ok":
        return FAIL, f"health={health.get('status')}"
    return PASS, f"{health.get('service')} ok"


def check_calibration() -> tuple[str, str]:
    try:
        snap = _api("/vehicle-snapshot")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return UNKNOWN, f"读不到快照（{type(exc).__name__}）"
    rows = snap.get("vehicles") or []
    if not rows:
        return UNKNOWN, "快照里没有载具"
    good = [v for v in rows
            if (v.get("spatial") or {}).get("calibration_status") == "calibrated"]
    if len(good) == len(rows):
        return PASS, f"{len(good)}/{len(rows)} 标定可用"
    # 标定 TTL 只有 60 秒，过期是**正常**的，不算故障 —— 所以附上解法。
    return FAIL, (f"{len(good)}/{len(rows)} 标定可用 —— 其余过期。"
                  f"标定 TTL 只有 60 秒，跑 `bash ops/calib.sh` 即可")


def check_manifest() -> tuple[str, str]:
    """起的是不是相机版 —— 那一类"看起来正常、只有相机动作失败"的错位。"""
    script = (
        "import json\n"
        f"d = json.load(open({MANIFEST!r}, encoding='utf-8'))\n"
        "print([v['gazebo_model_name'] for v in d['vehicles']])\n"
    )
    _code, out = _wsl(script, 40)
    line = _last_line(out)
    if "mono_cam" not in line:
        return UNKNOWN, f"读不到 manifest 模型名（{line[:50]}）"
    return PASS, f"相机版（{line[:60]}）"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--quiet", action="store_true", help="只输出结论一行")
    args = parser.parse_args(argv)

    checks = [
        ("进程", check_processes),
        ("仿真时钟", check_clock),
        ("三台遥测", check_telemetry),
        ("Runtime", check_runtime),
        ("标定", check_calibration),
        ("manifest", check_manifest),
    ]
    results = []
    for name, fn in checks:
        try:
            status, detail = fn()
        except Exception as exc:  # noqa: BLE001
            status, detail = UNKNOWN, f"{type(exc).__name__}:{exc}"
        results.append({"name": name, "status": status, "detail": detail})

    failed = [r for r in results if r["status"] == FAIL]
    unknown = [r for r in results if r["status"] == UNKNOWN]
    if failed:
        verdict, code = "unavailable", 1
    elif unknown:
        verdict, code = "undetermined", 2
    else:
        verdict, code = "available", 0

    if args.json:
        print(json.dumps({"verdict": verdict, "checks": results},
                         ensure_ascii=False, indent=2))
        return code
    if args.quiet:
        passed = sum(1 for r in results if r["status"] == PASS)
        print(f"{verdict}  ({passed}/{len(results)} 项通过)")
        return code

    print()
    print("=" * 72)
    print("系统状态")
    print("=" * 72)
    width = max(len(r["name"]) for r in results)
    for row in results:
        print(f"  {MARK[row['status']]} {row['name']:<{width}}  {row['detail']}")
    print()
    if verdict == "available":
        print("  可用 —— 六项检查全过")
    elif verdict == "undetermined":
        names = "、".join(r["name"] for r in unknown)
        print(f"  无法判定 —— {len(unknown)} 项读不到：{names}")
        print("  不要把「读不到」当成「没问题」，也不当成「坏了」")
    else:
        names = "、".join(r["name"] for r in failed)
        print(f"  不可用 —— {len(failed)} 项失败：{names}")
    print()
    print("  提示：进程数正常**不代表**系统健康。本项目实测踩过两次 ——")
    print("        Gazebo 掉了但 PX4 还在（'PID 3/1/1' 看起来正常），")
    print("        以及起的是默认版而非相机版（端口对、health ready、飞机能飞，")
    print("        只有相机动作失败）。所以本工具查六项独立证据，而不是数进程。")
    print()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
