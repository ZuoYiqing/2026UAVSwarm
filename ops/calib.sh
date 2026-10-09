#!/usr/bin/env bash
# 标定发布工具
#
# 用法:
#   bash calib.sh            # 发布一次（默认 duration 2s）
#   bash calib.sh loop       # 循环发布，保持标定常新（Ctrl+C 停止）
#   bash calib.sh once 6     # 发布一次，采样 6 秒
#
# 背景:
#   标定的 valid_for_ms 现为 60000ms（60 秒）。过期后 Runtime 会把
#   calibration_status 置为 stale，前端就拒绝显示飞机（这是设计，
#   防止用过期坐标把飞机画在错误位置）。
#
#   注：这里原先写的是"约 5000ms（5 秒）"，是过时信息 —— 5 秒太短，
#   每次刷新都刚好过期，因此早已上调为 60 秒。日常演示用 calib-once
#   就够；只有长时间盯着界面看才需要 calib-loop。
#
#   另外：本脚本要求**仿真已经启动**。它按 node_id 在
#   .runtime/px4_gazebo/harness_state.json 里找飞机记录，该文件由仿真
#   启动时写出、停止时消失。仿真没跑时本脚本会报
#   `calibration_process_missing` —— 那不是 Runtime 的问题，是仿真没起。
#
# 本脚本只做只读采样，不抢 MAVLink 端口，不发送任何飞控命令。

set -u

REPO=/mnt/d/2026UAVSwarm
API=http://127.0.0.1:8765/api

cd "$REPO" || { echo "找不到 $REPO"; exit 1; }

# --- 配置选择（2026-10-09 新增）-----------------------------------------------
#
# ⚠️ 踩过的坑：本脚本原先不传 --config，于是 sample_calibration.py 用**默认**
#    manifest（three_uav_sitl.json，模型 x500_0/1/2）。若实际在跑的是**相机版**
#    （x500_mono_cam_0/1/2），它会报：
#
#        ValueError: gazebo_model_pose_missing
#
#    因为它在世界里找不到 x500_0 的位姿 —— 而世界里是 x500_mono_cam_0。
#
# 修法不是"再加一个需要记住的变量"，而是**自动读实际在跑的配置**：
# harness state 里就记着 manifest_path，那是启动时写下的权威值。
# 仍可用 UAV_SIM_CONFIG 显式覆盖。
STATE="$REPO/.runtime/px4_gazebo/harness_state.json"

detect_config() {
  if [ -n "${UAV_SIM_CONFIG:-}" ]; then
    echo "$UAV_SIM_CONFIG"
    return
  fi
  if [ -f "$STATE" ]; then
    local detected
    detected=$(python3 -c "
import json
try:
    print(json.load(open('$STATE', encoding='utf-8')).get('manifest_path') or '')
except Exception:
    print('')
" 2>/dev/null)
    if [ -n "$detected" ]; then
      echo "$detected"
      return
    fi
  fi
  # 没有状态文件（仿真没跑）时给默认值；下面的前置检查会报"仿真未就绪"。
  echo "simulation/px4_gazebo/config/three_uav_sitl.json"
}

SIM_CONFIG="$(detect_config)"
CONFIG_ARG=()
if [ -f "$REPO/$SIM_CONFIG" ] || [ -f "$SIM_CONFIG" ]; then
  CONFIG_ARG=(--config "$SIM_CONFIG")
fi
echo "  配置: $SIM_CONFIG"

# 前置检查
if ! curl -sf --max-time 3 "$API/health" >/dev/null 2>&1; then
  echo "❌ Runtime 未就绪（$API/health 无响应）"
  echo "   请先在另一个终端启动:"
  echo "   cd $REPO && PYTHONPATH=$REPO/src python3 -m uav_runtime.http.server"
  exit 1
fi

if [ "$(pgrep -c px4 2>/dev/null || echo 0)" -lt 3 ]; then
  echo "❌ 仿真未就绪（PX4 进程不足 3 个）"
  echo "   请先启动: cd $REPO && bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless"
  exit 1
fi

publish_once() {
  local duration="${1:-2}"
  python3 simulation/px4_gazebo/scripts/sample_calibration.py \
    "${CONFIG_ARG[@]}" \
    --duration "$duration" \
    --publish-runtime "$API" 2>&1 | python3 -c "
import json, sys
raw = sys.stdin.read().strip()
try:
    d = json.loads(raw)
except Exception:
    print('  解析失败:', raw[:200]); sys.exit(1)
if d.get('status') != 'PASS':
    print('  ❌ FAIL:', d.get('error')); sys.exit(1)
rows = d.get('publications', [])
ok = sum(1 for r in rows if r.get('http_status') == 200)
valid = [r['response']['calibration']['valid_for_ms'] for r in rows
         if r.get('http_status') == 200 and 'calibration' in r.get('response', {})]
win = min(valid) if valid else 0
print(f'  ✅ 已发布 {ok}/{len(rows)} 台，有效期 {win}ms')
"
}

MODE="${1:-once}"

if [ "$MODE" = "loop" ]; then
  # 刷新间隔。
  #
  # 标定有效期 60 秒（见 simulation/px4_gazebo/calibration.py）。
  # 用 20 秒刷新：留出 3 倍余量，每秒开销平摊后很轻，且"飞机消失"的窗口
  # 完全不会出现。旧代码用 sleep 1（即每 3 秒刷一次）在 TTL=5s 时代是必须的，
  # 现在纯属浪费 —— 每轮要拉起 px4-listener 读 uORB。
  #
  # 想更省可以用 CALIB_INTERVAL=50 覆盖；想更稳用 CALIB_INTERVAL=10。
  INTERVAL="${CALIB_INTERVAL:-20}"
  echo "循环发布中，每 ${INTERVAL} 秒刷新一次（标定有效期 60 秒；Ctrl+C 停止）..."
  trap 'echo; echo "已停止"; exit 0' INT TERM
  while true; do
    printf '%s ' "$(date +%H:%M:%S)"
    publish_once 2 || true
    sleep "$INTERVAL"
  done
else
  DUR="${2:-2}"
  echo "发布一次（采样 ${DUR}s）..."
  publish_once "$DUR"
fi
