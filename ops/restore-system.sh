#!/usr/bin/env bash
# 恢复三机相机版仿真 + Runtime 到可用状态。
#
# 背景：Gazebo 掉了，三台 PX4 变成孤儿（进程活着但没仿真可连），
# Runtime 报 simulation_evidence_stale、connected_nodes=0、遥测全 null。
#
# 顺序不能反：
#   1. 先停 Runtime —— 它占着 14540-14542，不停它仿真起不来
#   2. 再停仿真（含孤儿 PX4）
#   3. 从**主仓库**起相机版，带 GPU 适配器变量（不设它 RTF 会掉到 0.18）
#   4. 最后起 Runtime（必须 setsid，普通 nohup 会随父 shell 被回收）
set -u

REPO=/mnt/d/2026UAVSwarm
CFG=simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
OPS=/mnt/d/2026UAVSwarm-worktrees/_ops

step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✅ %s\033[0m\n' "$1"; }
bad()  { printf '  \033[31m❌ %s\033[0m\n' "$1"; }

cd "$REPO" || { echo "找不到 $REPO"; exit 1; }

step "1/5 停 Runtime"
pkill -f 'uav_runtime.http.server' 2>/dev/null && ok "已发出停止信号" || echo "  （本来就没在跑）"
sleep 3
pgrep -f 'uav_runtime.http.server' >/dev/null 2>&1 && bad "仍在运行" || ok "已停止"

step "2/5 停仿真（含孤儿 PX4）"
bash simulation/px4_gazebo/scripts/stop_three_uav.sh >/tmp/stop.log 2>&1
sleep 3
# ⚠️ `pgrep -cf X || echo 0` 是错的：pgrep 找不到时**既无输出又返回非零**，
# 于是 `|| echo 0` 会额外再打印一个 0，命令替换拿到 "0\n0"，
# 下一行 `[ "$n" -gt 0 ]` 就报 "integer expression expected"。
# 正确写法是 `$(pgrep -cf X 2>/dev/null || true)` 再用 `${n:-0}` 兜底。
count() { local n; n=$(pgrep -cf "$1" 2>/dev/null || true); echo "${n:-0}"; }
left=0
for pat in 'bin/px4' 'gz sim'; do
  n=$(count "$pat")
  [ "$n" -gt 0 ] && { bad "$pat 仍有 $n 个"; left=1; }
done
if [ "$left" -eq 1 ]; then
  echo "  仍有残留 —— 逐个核对命令行后再终止"
  for pid in $(pgrep -f 'bin/px4' 2>/dev/null); do
    cmd=$(ps -o args= -p "$pid" 2>/dev/null)
    case "$cmd" in
      *px4_sitl_default*) kill -TERM "$pid" 2>/dev/null && echo "    TERM $pid" ;;
      *) echo "    跳过 $pid（命令行不匹配）" ;;
    esac
  done
  sleep 4
fi
for p in 14540 14541 14542; do
  if ss -lunp 2>/dev/null | grep -q ":$p "; then bad "$p 仍占用"; else ok "$p 空闲"; fi
done

step "3/5 起相机版仿真"
if [ ! -f "$CFG" ]; then bad "找不到 $CFG"; exit 1; fi
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA nohup bash \
  simulation/px4_gazebo/scripts/start_three_uav.sh --headless --config "$CFG" \
  >/tmp/sim_restart.log 2>&1 &
echo "  已启动，等待就绪（最多 90 秒）…"
ready=0
for i in $(seq 1 45); do
  n=$(count 'bin/px4')
  g=$(count 'gz sim')
  if [ "$n" -ge 3 ] && [ "$g" -ge 1 ]; then ready=1; break; fi
  sleep 2
done
if [ "$ready" -eq 1 ]; then
  ok "PX4=$(count 'bin/px4') Gazebo=$(count 'gz sim')"
else
  bad "超时未就绪 —— 见 /tmp/sim_restart.log"
  tail -20 /tmp/sim_restart.log | sed 's/^/    /'
  exit 1
fi
echo "  再等 15 秒让 MAVLink 实例开始外发…"
sleep 15

step "4/5 起 Runtime"
PYTHONPATH="$REPO/src" setsid nohup python3 -u -m uav_runtime.http.server \
  >/tmp/rt_restart.log 2>&1 </dev/null &
for i in $(seq 1 15); do
  if curl -sf --max-time 3 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    ok "8765 已响应"; break
  fi
  sleep 2
done
curl -sf --max-time 5 http://127.0.0.1:8765/api/health | sed 's/^/    /' || bad "8765 无响应"

step "5/5 发布标定 + 健康检查"
echo "  发布标定（TTL 只有 60 秒，所以现在发一次确认链路）…"
timeout 90 python3 simulation/px4_gazebo/scripts/sample_calibration.py \
  --duration 2 --publish-runtime http://127.0.0.1:8765/api >/tmp/cal_restart.json 2>&1
python3 -c "
import json
try:
    d = json.load(open('/tmp/cal_restart.json', encoding='utf-8'))
    print('    status  :', d.get('status'))
    print('    manifest:', d.get('manifest_path'))
except Exception as exc:
    print('    读取失败:', exc)
"
echo
echo "  三台实时状态:"
timeout 90 python3 "$OPS/live-state-json.py" 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read().strip().splitlines()[-1])
except Exception as exc:
    print('    读不到:', exc); raise SystemExit
for node, row in sorted(d.items()):
    print(f\"    {node}  armed={row.get('armed')}  mode={row.get('mode')}  alt={row.get('alt')}\")
"
