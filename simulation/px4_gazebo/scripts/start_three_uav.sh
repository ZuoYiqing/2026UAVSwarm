#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/../harness.py" start "$@"

# 起完三机后自动续期公共坐标。
#
# 为什么放在这里：三维视图只在拿到"新鲜"的公共坐标证据后才画载具，而那份证据
# 有有效期（当前 60 秒）。以前这要靠操作者记得每分钟手工跑一次
# sample_calibration.py —— 演示最容易忘的就是这一步，而后果是三架飞机从画面上
# 消失，看起来像系统故障。
#
# 这个循环只读 Gazebo 位姿与 PX4 的 vehicle_local_position，不发任何飞控指令；
# 仿真停止（harness state 消失或 run_id 变化）时它会自己退出。
#
# 想回到"纯仿真、不自动标定"的旧行为：UAV_SIM_NO_AUTOCALIB=1
if [ "${UAV_SIM_NO_AUTOCALIB:-}" = "1" ]; then
  echo "start_three_uav: UAV_SIM_NO_AUTOCALIB=1, calibration loop skipped"
  exit 0
fi

exec python3 "${SCRIPT_DIR}/calibration_loop.py"
