#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 启动三机。**这个命令必须照常返回** —— 验收脚本和运维流程依赖"start 退出之后再
# 拉起 Runtime"这个顺序。不要把续期循环 exec 进来：那会让 start 永不返回，
# 调用方会卡住。
python3 "${SCRIPT_DIR}/../harness.py" start "$@"

if [ "${UAV_SIM_NO_AUTOCALIB:-}" = "1" ]; then
  echo "start_three_uav: UAV_SIM_NO_AUTOCALIB=1, calibration loop skipped"
  exit 0
fi

# 三机就绪后，把公共坐标的续期交给一个**分离的**后台进程。
#
# 为什么需要续期：三维视图只在拿到"新鲜"的公共坐标证据后才画载具，而那份证据
# 有有效期（当前 60 秒）。以前这靠操作者记得每分钟手工跑 sample_calibration.py，
# 忘跑就是演示到一半三架飞机从画面上消失。
#
# 为什么分离（setsid + nohup）：
#   · 不挂在调用方终端上，关窗口不影响它；
#   · 它自己会在仿真停止时退出（harness state 消失或 run_id 变化），
#     所以 stop_three_uav.sh 不需要额外信号；
#   · 同一 run 只允许一个续期进程，由 calibration_loop.py 的 pid 文件保证。
LOG="${UAV_SIM_CALIB_LOG:-/tmp/uavswarm-calibration-loop.log}"
setsid nohup python3 "${SCRIPT_DIR}/calibration_loop.py" >"${LOG}" 2>&1 &
echo "start_three_uav: calibration loop detached; log ${LOG}"
