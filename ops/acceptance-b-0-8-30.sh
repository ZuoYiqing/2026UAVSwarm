#!/usr/bin/env bash
# 0/8/30 秒在线验收：验证 B 的修复（静态几何不再随 health TTL 过期）。
#
# 判据（Runtime 侧提出的，我认可）：
#   T=0  : ground_context 可读 + 动态 health 新鲜
#   T=8  : ground_context **仍可读**；动态 health 应已变为 unknown（它确实会过期）
#   T=30 : ground_context **仍可读**；动态 health 仍 unknown
#   标定 TTL 60 秒 → T=30 时标定仍有效；超过 60 秒后 ground_context 变 null 才是对的
#
# ⚠️ **只发布一次**。发布之后不再刷新任何证据 —— 那正是本条修复要证明的：
#    静态几何不需要被反复重发。
#
# ⚠️ 启动 Runtime 必须用**验收目录自己的 src**。
#    上一轮失败的原因就是 PYTHONPATH 被展开成了主仓库的 src，跑的是旧代码、
#    /api/preflight 返回 404。这里在脚本内部用 $PWD，不经 Windows shell 展开。

ACC=/mnt/d/2026UAVSwarm/.runtime/acceptance-88-92-fresh-20261011
CFG="$ACC/simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json"
API=http://127.0.0.1:8765/api
LOG=/tmp/b_acceptance

mkdir -p "$LOG"
step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✅ %s\033[0m\n' "$1"; }
bad()  { printf '  \033[31m❌ %s\033[0m\n' "$1"; }

count() { local n; n=$(pgrep -cf "$1" 2>/dev/null || true); echo "${n:-0}"; }

step "0. 前置：系统必须是停的"
"  PX4=$(count 'bin/px4')  Gazebo=$(count 'gz sim')  Runtime=$(count 'uav_runtime.http.server')"

step "1. 起仿真（相机版 + GPU 适配器变量，必须）"
cd "$ACC" || exit 1
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA nohup bash \
  simulation/px4_gazebo/scripts/start_three_uav.sh --headless --config "$CFG" \
  >"$LOG/sim.log" 2>&1 &
ready=0
for i in $(seq 1 45); do
  n=$(count 'bin/px4'); g=$(count 'gz sim')
  p=$(ss -lunp 2>/dev/null | grep -c ':1458[0-2] ')
  if [ "$n" -ge 3 ] && [ "$g" -ge 1 ] && [ "$p" -ge 3 ]; then ready=1; break; fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  # ⚠️ 第一版这里超时后**继续往下跑**，于是后面全是下游症状（标定 FAIL、
  #    preflight reason 里一堆 unavailable），看起来像"B 没修好"。
  #    那是错的归因 —— 仿真根本没起来。所以这里必须**硬停并打印日志**。
  bad "仿真没起来 —— 停止，不继续（否则会把下游症状误判成 B 的失败）"
  echo "  当前: PX4=$(count 'bin/px4') Gazebo=$(count 'gz sim') 端口=$(ss -lunp 2>/dev/null | grep -c ':1458[0-2] ')/3"
  echo "  --- sim.log ---"
  head -20 "$LOG/sim.log" | sed 's/^/    /'
  exit 1
fi
ok "PX4=$(count 'bin/px4') Gazebo=$(count 'gz sim') 已绑端口=$(ss -lunp 2>/dev/null | grep -c ':1458[0-2] ')/3"
sleep 10

step "2. 量 RTF（确认 GPU 变量生效）"
timeout 60 python3 - <<'PY'
import sys
sys.path.insert(0, "simulation/px4_gazebo")
import gazebo_evidence as ge
r = ge.probe_clock("simple_recon_v0_1", 5.0)
ev = r.get("evidence") or {}
rtf = ev.get("real_time_factor")
print(f"  RTF={rtf if rtf is None else round(rtf,4)}  门槛={ev.get('minimum_real_time_factor')}  "
      f"advancing={r.get('clock_advancing')}")
PY

step "3. 起 Runtime（用验收目录自己的 src —— 上一轮就是这里出的错）"
PYTHONPATH="$ACC/src" setsid nohup python3 -u -m uav_runtime.http.server \
  >"$LOG/rt.log" 2>&1 < /dev/null &
for i in $(seq 1 20); do
  curl -sf --max-time 3 "$API/health" >/dev/null 2>&1 && break
  sleep 2
done
ok "8765 已响应"

echo "  ⭐ 关键自检：/api/preflight 存在吗（只在 #88 里有；404 说明跑的是旧代码）"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$API/preflight?node_id=UAV-02" 2>/dev/null)
if [ "$code" = "200" ]; then
  ok "/api/preflight → 200（跑的是正确版本）"
else
  bad "/api/preflight → HTTP $code —— **跑的是旧代码，本轮无效**"
  echo "     停掉重来，不要用这个结果下结论"
  pkill -f 'uav_runtime.http.server' 2>/dev/null
  exit 1
fi

step "4. 发布证据 —— **只发这一次**"
echo "  4a) 标定"
timeout 120 python3 simulation/px4_gazebo/scripts/sample_calibration.py \
  --duration 2 --publish-runtime "$API" >"$LOG/calib.json" 2>&1
python3 -c "
import json
d=json.load(open('$LOG/calib.json',encoding='utf-8'))
print('    status:', d.get('status'))
"
echo "  4b) integrated health（含 ground_reference）"
curl -sf --max-time 10 "$API/telemetry/latest" -o "$LOG/telemetry.json"
timeout 180 python3 simulation/px4_gazebo/scripts/health_three_uav.py \
  --mode integrated --config "$CFG" \
  --runtime-telemetry "$LOG/telemetry.json" \
  --publish-runtime "$API" \
  --output "$LOG/health.json" --runtime-output "$LOG/runtime_evidence.json" >"$LOG/health.log" 2>&1
python3 -c "
import json
d=json.load(open('$LOG/health.json',encoding='utf-8'))
print('    status:', d.get('status'), ' ground_reference_status:', (d.get('evidence') or {}).get('ground_reference_status'))
"

step "5. ⭐ 0/8/30 秒观察（发布之后**不再刷新**任何证据）"
T0=$(date +%s)
for target in 0 8 30; do
  now=$(date +%s); wait=$(( target - (now - T0) ))
  [ "$wait" -gt 0 ] && sleep "$wait"
  echo
  echo "  ---------- T = ${target}s（实际 $(( $(date +%s) - T0 ))s）----------"
  python3 - "$API" "$target" <<'PY'
import json, sys, urllib.request, urllib.error
api, target = sys.argv[1], sys.argv[2]

def get(path, timeout=20):
    with urllib.request.urlopen(f"{api}{path}", timeout=timeout) as r:
        return json.load(r)

try:
    p = get("/preflight?node_id=UAV-02")
except Exception as exc:
    print(f"    ❌ preflight 读取失败: {type(exc).__name__}: {exc}")
    raise SystemExit

print(f"    preflight.status      : {p.get('status')}")
print(f"    execution_authorized  : {p.get('execution_authorized')}")
print(f"    flight_command_sent   : {p.get('flight_command_sent')}")
print(f"    reason_codes          : {p.get('reason_codes')}")

gc = p.get("ground_context")
print(f"    **ground_context**    : {'✅ 可读' if gc else '❌ null'}")
if gc:
    gr = gc.get("ground_reference") or {}
    print(f"        surface_id={gr.get('surface_id')} ground_down_m={gr.get('ground_down_m')} "
          f"world_sha256={str(gr.get('world_sha256'))[:16]}")
    print(f"        run_id={gc.get('run_id')}")

he = p.get("home_evidence")
print(f"    home_evidence         : {'✅ 可读' if he else '❌ null'}")

sh = p.get("simulation_health")
if sh:
    print(f"    simulation_health     : {json.dumps(sh, ensure_ascii=False)[:150]}")

try:
    s = get("/simulation/status")
    print(f"    evidence_fresh        : {s.get('evidence_fresh')}  age_ms={s.get('evidence_age_ms')}  "
          f"valid_for_ms={s.get('evidence_valid_for_ms')}")
except Exception:
    pass
try:
    snap = get("/vehicle-snapshot")
    v = next((x for x in (snap.get("vehicles") or []) if x.get("id") == "UAV-02"), None)
    if v:
        sp = v.get("spatial") or {}
        print(f"    标定                  : {sp.get('calibration_status')} age={sp.get('calibration_age_ms')}ms")
except Exception:
    pass
PY
done

step "6. 结论判读"
echo "  期望：T=0/8/30 三个点 **ground_context 都可读**（标定 TTL 60 秒内）"
echo "        而 evidence_fresh 在 T=8/30 应为 False（动态健康确实过期了 —— 那是对的）"
echo
echo "  若 T=8 或 T=30 的 ground_context 又变 null，则 B 未修好。"
