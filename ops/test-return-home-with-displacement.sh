#!/usr/bin/env bash
# 正确时序：起飞 → 飞离 home → 返航，验证"距离缩短 ≠ 到达"。
#
# 为什么必须由脚本做，而不是手敲：
#   · 标定 TTL 只有 60 秒，过期后 goto/land 的坐标判定会被直接拒绝
#     （实测：goto 被拒，failure_reason=coordinate_calibration_unavailable,
#       calibration_status=stale）
#   · goto 本身要执行约 25 秒（等到达）
#   · 手敲命令的间隔会吞掉窗口，前面两次尝试都是这么失败的
#   所以这里把"发标定"和"立刻动作"写在同一个函数里。
#
# 前置：仿真 + Runtime 已由调用方起好，且三台在 LOAMER/armed=false。
#       若 UAV-02 处于 mode=LAND，PX4 会拒绝解锁 —— 那种情况必须重起仿真。

API=http://127.0.0.1:8765/api
NODE=UAV-02
CFG=simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json

# ⚠️ **必须 cd 到验收目录。**
#
# 第一版漏了这一步，脚本在 _ops/ 下运行，相对路径落到
# 2026UAVSwarm-worktrees/simulation/...，于是 sample_calibration.py 找不到：
#     python3: can't open file '.../2026UAVSwarm-worktrees/simulation/.../sample_calibration.py'
# 三次"发标定"全部静默失败 → goto 被拒 coordinate_calibration_unavailable。
#
# 而且这些子进程都带 2>&1 重定向，错误进了文件、终端只看到"标定读取失败"，
# 所以我一开始误以为是标定本身有问题。**必须在这里硬失败。**
cd /mnt/d/2026UAVSwarm/.runtime/acceptance-88-92-fresh-20261011 || {
  echo "  ❌ 验收目录不存在，无法继续"; exit 1;
}
echo "  工作目录: $PWD"
if [ ! -f simulation/px4_gazebo/scripts/sample_calibration.py ]; then
  echo "  ❌ 找不到 sample_calibration.py —— 工作目录不对，停止（不要用错误路径的结果下结论）"
  exit 1
fi

step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✅ %s\033[0m\n' "$1"; }
bad()  { printf '  \033[31m❌ %s\033[0m\n' "$1"; }
warn() { printf '  \033[33m⚠️  %s\033[0m\n' "$1"; }

# 发一次标定，并确认 Runtime 侧真的收到且新鲜。
#
# ⚠️ 这里**必须硬失败**：第一版把输出重定向到文件后只检查 JSON，
#    而失败原因（找不到文件）藏在文件里，终端只报"标定读取失败"，
#    误导我以为标定流程本身有问题。现在非零退出或非 PASS 都直接停下。
publish_calib() {
  if ! python3 simulation/px4_gazebo/scripts/sample_calibration.py \
        --duration 2 --publish-runtime "$API" >/tmp/cal.json 2>/tmp/cal.err; then
    printf '  \033[31m❌ 标定命令失败\033[0m\n'
    sed 's/^/      /' /tmp/cal.err | head -5
    return 1
  fi
  python3 - <<'PY'
import json, sys
try:
    d = json.load(open("/tmp/cal.json", encoding="utf-8"))
except Exception as exc:
    print(f"    ❌ 标定输出不是 JSON: {exc}")
    print("       前 200 字节:", open("/tmp/cal.json", encoding="utf-8", errors="replace").read()[:200])
    sys.exit(1)
pubs = d.get("publications") or []
ok = sum(1 for p in pubs if p.get("http_status") == 200)
print(f"    标定 status={d.get('status')}  发布 {ok}/{len(pubs)}")
sys.exit(0 if d.get("status") == "PASS" and ok == len(pubs) and ok > 0 else 1)
PY
}

# 发标定并在失败时停止整个脚本
require_calib() {
  if ! publish_calib; then
    bad "标定未成功发布 —— 停止（继续下去只会得到 coordinate_calibration_unavailable）"
    exit 1
  fi
}

# 动作前统一检查：mode 必须是 LOITER（LAND 模式下 PX4 拒绝解锁）
check_mode() {
  python3 - "$1" <<'PY'
import json, sys, urllib.request
node = sys.argv[1]
with urllib.request.urlopen("http://127.0.0.1:8765/api/vehicle-snapshot", timeout=12) as r:
    snap = json.load(r)
v = next((x for x in snap.get("vehicles") or [] if x.get("id") == node), None)
if v is None:
    print(f"    ❌ 快照里没有 {node}"); raise SystemExit(1)
t = v.get("telemetry") or {}
mode = t.get("mode")
armed = t.get("armed")
print(f"    {node}: armed={armed}  mode={mode}")
if mode == "LAND":
    print("    ❌ mode=LAND —— PX4 会拒绝解锁，必须重起仿真"); raise SystemExit(1)
PY
}

step "1. 动作前检查（mode 必须是 LOITER）"
check_mode "$NODE" || exit 1

step "2. 发标定 → 立刻起飞到 10 m"
require_calib
curl -s -X POST "$API/actions/takeoff" -H 'Content-Type: application/json' \
  -d "{\"node_id\":\"$NODE\",\"altitude_m\":10}" -o /tmp/tk.json
python3 - <<'PY'
import json
d = json.load(open("/tmp/tk.json", encoding="utf-8"))
ce = d.get("completion_evidence") or {}
print(f"    takeoff: {d.get('status')}  result={d.get('result')}  "
      f"failure={d.get('failure_reason')}")
print(f"      max_alt={d.get('max_altitude_m')}  last_alt={ce.get('last_altitude_m')}  "
      f"samples={ce.get('sample_count')}")
if d.get("status") != "succeeded":
    print("    ⚠️ 起飞没成功；不要继续 goto —— 把这段发回集成方")
PY
if ! python3 -c "
import json,sys
d=json.load(open('/tmp/tk.json',encoding='utf-8'))
sys.exit(0 if d.get('status')=='succeeded' else 1)
"; then
  bad "起飞未成功，停止（不继续 goto）"
  exit 1
fi

step "3. ⭐ 起飞完【立刻】重发标定 → 马上 goto 到 N=15"
require_calib
curl -s -X POST "$API/actions/goto" -H 'Content-Type: application/json' \
  -d "{\"node_id\":\"$NODE\",\"north_m\":15,\"east_m\":0,\"altitude_m\":10}" -o /tmp/gt.json
python3 - <<'PY'
import json
d = json.load(open("/tmp/gt.json", encoding="utf-8"))
ce = d.get("completion_evidence") or {}
print(f"    goto: {d.get('status')}  result={d.get('result')}  "
      f"failure={d.get('failure_reason')}  calib={d.get('calibration_status')}")
print(f"      last_error_m={ce.get('last_error_m')}  min_error_m={ce.get('min_error_m')}  "
      f"samples={ce.get('samples')}")
tr = d.get("target_scene_ned_m")
if tr:
    print(f"      目标 scene_ned: {tr}")
PY

step "4. ⭐ 返航（距 home 应约 15 m —— 这才是那条判据的关键）"
python3 - <<'PY'
import json
try:
    d = json.load(open("/tmp/gt.json", encoding="utf-8"))
except Exception:
    d = {}
ce = d.get("completion_evidence") or {}
err = ce.get("last_error_m")
print(f"    goto 后距目标 = {err}")
if isinstance(err, (int, float)) and err > 1.0:
    print("    ⚠️ 没到达目标 —— 飞机可能没离开 home，返航测试会再次空过")
PY
require_calib
curl -s -X POST "$API/actions/return-home" -H 'Content-Type: application/json' \
  -d "{\"node_id\":\"$NODE\"}" -o /tmp/rh.json
python3 - <<'PY'
import json
d = json.load(open("/tmp/rh.json", encoding="utf-8"))
ce = d.get("completion_evidence") or {}
print(f"\n    return_home: {d.get('status')}  result={d.get('result')}  "
      f"failure={d.get('failure_reason')}")
for k in ("reason", "initial_distance_m", "final_distance_m", "distance_reduction_m",
          "arrival_samples", "home_tolerance_m", "min_progress_m",
          "autonomous_execution_may_continue", "completion_goal"):
    if k in ce:
        print(f"      {k}: {ce.get(k)}")
ini = ce.get("initial_distance_m")
print()
if isinstance(ini, (int, float)):
    if ini > 5.0:
        print(f"    ⭐ 起点距 home = {ini:.2f} m —— **这次真的测到了那条判据**")
        if ce.get("reason") == "arrived_at_home" and (ce.get("arrival_samples") or 0) > 0:
            print("       判据是'到达容差内稳定样本'，不是'距离缩短' ✅")
    else:
        print(f"    ⚠️ 起点距 home 只有 {ini:.3f} m —— 飞机没离开，这条**又空过**了")
PY

step "5. 各台 armed 状态（01/03 必须始终 False）"
python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8765/api/vehicle-snapshot", timeout=12) as r:
    snap = json.load(r)
for v in snap.get("vehicles") or []:
    t = v.get("telemetry") or {}
    print(f"    {v.get('id')}: armed={t.get('armed')}  mode={t.get('mode')}")
PY
