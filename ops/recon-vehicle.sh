#!/usr/bin/env bash
# 车辆 / 机载计算单元专用补充扫描
#
# 为什么要单独一份：同事那份报告测的是 CUDA / TensorRT / cuDNN / 网络，
# 缺的恰好是迁移最需要的几项 —— 磁盘设备树、ROS、CAN、Python 版本、
# 网口 IPv4、以及"能不能从外部登进来"。
#
# **全程只读**：不装包、不改配置、不启停任何服务、不写文件（除了 tee 到当前目录）。
# 唯一"有副作用"的是 candump 会短暂订阅 CAN —— 用 timeout 限死 3 秒，且只读不发送。
#
# 用法：
#     bash recon-vehicle.sh 2>&1 | tee ~/recon-vehicle-$(hostname)-$(date +%Y%m%d).txt

set -u
hr() { printf '\n=========== %s ===========\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

hr "0. 这台机器"
printf '  hostname : %s\n' "$(hostname)"
printf '  user     : %s  uid=%s\n' "$(id -un)" "$(id -u)"
printf '  time     : %s\n' "$(date -Is)"
if [ -f /etc/nv_tegra_release ]; then printf '  L4T      : %s\n' "$(head -1 /etc/nv_tegra_release)"; fi
if [ -f /etc/os-release ]; then . /etc/os-release; printf '  OS       : %s\n' "$PRETTY_NAME"; fi
printf '  arch     : %s\n' "$(uname -m)"
printf '  kernel   : %s\n' "$(uname -r)"

hr "1. 磁盘 —— 这是最要紧的一项"
echo "  --- 文件系统用量 ---"
df -hT 2>/dev/null | grep -vE 'tmpfs|udev|loop|snapfuse' | sed 's/^/    /'
echo "  --- 块设备树（重点看有没有 nvme0n1）---"
if have lsblk; then lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,LABEL 2>/dev/null | sed 's/^/    /'; fi
echo "  --- NVMe 设备节点 ---"
ls -1 /dev/nvme* 2>/dev/null | sed 's/^/    /' || echo "    (没有 /dev/nvme*)"
echo "  --- rootfs 在哪个设备 ---"
findmnt -no SOURCE,SIZE,USED,AVAIL,FSTYPE / 2>/dev/null | sed 's/^/    /'
echo "  --- eMMC / SD ---"
ls -1 /dev/mmcblk* 2>/dev/null | head -8 | sed 's/^/    /' || echo "    (无)"
echo "  --- 结论提示 ---"
if ls /dev/nvme* >/dev/null 2>&1; then
  echo "    ✅ 有 NVMe 设备。若它没挂在 / 或 /home 上，说明**尚未使用** ——"
  echo "       那正是 jetson-util/ssd-rootfs 要做的事（把 rootfs 迁到 SSD）。"
else
  echo "    ⚠️ 没有 NVMe 设备节点：盘可能没插、没装，或未被内核枚举。"
  echo "       系统只能靠 eMMC/SD —— 需要确认容量是否够装 Runtime + 模型。"
fi

hr "2. Python（决定 Runtime 能不能装在这台）"
printf '  python3      : %s\n' "$(python3 -V 2>&1)"
printf '  路径         : %s\n' "$(command -v python3)"
printf '  所有 python3.x: \n'
for p in /usr/bin/python3.*; do
  # 排除 -config / -dbg 这类配套二进制，只列真正的解释器
  case "$p" in
    *-config|*-dbg|*.py) continue ;;
  esac
  [ -x "$p" ] && printf '    %-30s %s\n' "$p" "$($p -V 2>&1)"
done
if have python3; then
  printf '  venv         : %s\n' "$(python3 -c 'import venv;print("有")' 2>&1 | tail -1)"
  printf '  pip3         : %s\n' "$(python3 -m pip -V 2>&1 | head -1)"
fi
echo "  ⚠️ 本项目要求 python >= 3.10。20.04 自带 3.8 → 需要另外装（离线）"

hr '3. ROS —— 厂家说"传感器在 ros 上跑"，我们要确认'
if [ -n "${ROS_DISTRO:-}" ]; then printf '  ROS_DISTRO(env) : %s\n' "$ROS_DISTRO"; fi
for d in /opt/ros/*; do [ -d "$d" ] && printf '  /opt/ros/%-14s %s 个包\n' "$(basename "$d")" "$(ls -1 "$d/share" 2>/dev/null | wc -l)"; done
if [ ! -d /opt/ros ]; then echo "  ❌ /opt/ros 不存在 —— 这台可能没装 ROS，或装在别处"; fi
echo "  --- ROS 环境变量 ---"
env | grep -E '^(ROS_|AMENT_|COLCON_|RMW_)' | sed 's/^/    /' || echo "    (无)"
echo "  --- rosnode / rostopic 可用吗 ---"
for t in rosnode rostopic ros2; do
  if have "$t"; then echo "    ✅ $t: $(command -v $t)"; else echo "    ❌ $t 不在 PATH"; fi
done
echo "  --- 正在跑的节点（若有 master）---"
if have rosnode; then timeout 8 rosnode list 2>/dev/null | head -25 | sed 's/^/    /' || echo "    (rosnode 无响应)"; fi
if have ros2; then timeout 8 ros2 node list 2>/dev/null | head -25 | sed 's/^/    /' || echo "    (ros2 无响应)"; fi

hr "4. 工作空间与厂家软件（找 scout / 车的启动脚本）"
for d in ~/catkin_ws ~/ros_ws ~/ws ~/scout* /opt/*scout* ~/*scout* /home/*/catkin_ws /home/*/scout*; do
  [ -d "$d" ] && printf '  发现: %s\n' "$d"
done
echo "  --- 家目录顶层 ---"
ls -1 ~ 2>/dev/null | head -30 | sed 's/^/    /'
echo "  --- 找 launch 文件（限两层，避免扫太久）---"
find ~ -maxdepth 3 -name '*.launch' -o -maxdepth 3 -name '*.launch.py' 2>/dev/null | head -15 | sed 's/^/    /'
echo "  ⚠️ 关键问题：车的底盘/雷达/相机是怎么起来的？开机自启的？还是手动跑某个脚本？"

hr "5. CAN 总线（报告里 can0 是 UP —— 车控很可能走这里）"
if have ip; then
  ip -details -statistics link show 2>/dev/null | awk '/^[0-9]+: can/{p=1} p&&/can |bitrate|state/{print "    "$0} /^[0-9]+: (eth|wlan|lo|docker)/{p=0}' | head -30
fi
echo "  --- candump 是否可用（只订阅 3 秒，不发送）---"
if have candump; then
  echo "    尝试 candump -T 3000 can0 ..."
  timeout 5 candump -T 3000 can0 2>&1 | head -10 | sed 's/^/      /' || echo "      (无数据或不可用)"
else
  echo "    ❌ candump 不可用（can-utils 未装）"
fi

hr "6. 网络（决定我们怎么远程连、Runtime 怎么连飞控）"
if have ip; then
  echo "  --- IPv4 地址 ---"
  ip -4 addr show 2>/dev/null | awk '/^[0-9]+: /{ifc=$2} /inet /{print "    " ifc "  " $2}' | sed 's/:$//'
  echo "  --- 路由 ---"
  ip -4 route 2>/dev/null | head -10 | sed 's/^/    /'
  echo "  --- 接口状态（UP/DOWN 很说明问题）---"
  ip -brief link show 2>/dev/null | sed 's/^/    /'
fi
echo "  --- 监听端口 ---"
if have ss; then ss -ltn 2>/dev/null | head -20 | sed 's/^/    /'; fi
echo "  --- SSH 服务在跑吗（我们能登进来吗）---"
if have ss; then ss -ltn 2>/dev/null | grep -q ':22 ' && echo "    ✅ 22 端口在监听" || echo "    ❌ 22 未监听"; fi
printf '    sshd 进程: %s\n' "$(pgrep -c sshd 2>/dev/null || echo 0)"

hr "7. 串口 / 数传（MAVLink 走串口时要看）"
ls -1 /dev/ttyTHS* /dev/ttyUSB* /dev/ttyACM* /dev/ttyS* 2>/dev/null | head -20 | sed 's/^/    /'
echo "  --- 当前登录用户能访问的串口组 ---"
id -nG 2>/dev/null | sed 's/^/    groups: /'
echo "  --- dmesg 里的串口/USB 识别（需权限，可能为空）---"
dmesg 2>/dev/null | grep -iE 'ttyACM|ttyUSB|ftdi|cp210|ch341' | tail -8 | sed 's/^/    /' || echo "    (无权限或无设备)"

hr "8. 现有与"我们"相关的东西"
for d in /opt /home /srv /data /var/opt; do
  [ -d "$d" ] || continue
  found=$(find "$d" -maxdepth 4 -type d \( -iname '*uav*' -o -iname '*swarm*' -o -iname '*runtime*' -o -iname '*px4*' \) 2>/dev/null | grep -viE 'python|node_modules|\.cache' | head -8)
  [ -n "$found" ] && { echo "  在 $d 下:"; printf '%s\n' "$found" | sed 's/^/    /'; }
done

hr "9. 远程控制与显示能力"
printf '  SSH 可用     : %s\n' "$(have ssh && echo yes || echo no)"
printf '  图形界面     : %s\n' "$( [ -n "${DISPLAY:-}" ] && echo "DISPLAY=$DISPLAY" || echo "无 DISPLAY（headless）" )"
printf '  桌面环境     : %s\n' "$( [ -d /usr/share/xsessions ] && ls -1 /usr/share/xsessions | tr '\n' ' ' || echo 无 )"
printf '  浏览器       : %s\n' "$(for b in firefox chromium chromium-browser google-chrome; do command -v $b >/dev/null 2>&1 && echo -n "$b "; done)"
echo "  ⚠️ 若这台是 headless（车上常见），控制台要靠另一台机器的浏览器远程访问，"
echo "     或用 ssh -L 端口转发把 5178/5179 映射出来。"

hr "10. 结论要点（人工判读用）"
echo "  请把本文件带回来。最要紧的是第 1 节（有没有 NVMe / 还剩多少空间）"
echo "  与第 3 节（ROS 到底装没装）、第 5 节（CAN）、第 6 节（怎么远程连）。"
