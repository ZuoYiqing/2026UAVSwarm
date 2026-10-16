#!/usr/bin/env bash
# 离线环境勘察（recon）—— 在每台目标机上跑一次，把报告带回来。
#
# 为什么先做这个，而不是先拷代码：
#   不摸清离线环境的家底就打包，几乎必然打错。本项目已经反复吃过"假设与现实不符"的
#   亏（CRLF、Python 版本、GPU 适配器变量）。所以第一步是**用一条命令把事实取回来**。
#
# 用法（无需 root，除了第 9 节标注 [需要 sudo] 的那一段）：
#     bash recon-offline-env.sh 2>&1 | tee recon-$(hostname)-$(date +%Y%m%d).txt
#   然后把生成的 txt 带回来。
#
# 它只读，不改任何东西，不联网，不装包。

set -u
hr()  { printf '\n=========== %s ===========\n' "$1"; }
have(){ command -v "$1" >/dev/null 2>&1; }

hr "0. 这台机器是谁"
printf '  hostname : %s\n' "$(hostname)"
printf '  user     : %s\n' "$(id -un)"
printf '  uid      : %s\n' "$(id -u)"
printf '  时间     : %s\n' "$(date -Is)"

hr "1. 系统与内核"
if [ -f /etc/os-release ]; then . /etc/os-release; printf '  OS       : %s\n' "$PRETTY_NAME"; fi
printf '  kernel   : %s\n' "$(uname -r)"
printf '  arch     : %s\n' "$(uname -m)"
printf '  glibc    : %s\n' "$(ldd --version 2>/dev/null | head -1)"
if [ -f /etc/nv_tegra_release ]; then printf '  L4T      : %s\n' "$(head -1 /etc/nv_tegra_release)"; fi

hr "2. Python（最关键的一项）"
printf '  python3        : %s\n' "$(python3 -V 2>&1)"
printf '  路径           : %s\n' "$(command -v python3 2>/dev/null || echo '(无)')"
printf '  python(2.x?)   : %s\n' "$(python -V 2>&1 | head -1)"
printf '  pip3           : %s\n' "$(python3 -m pip -V 2>&1 | head -1)"
printf '  venv 模块      : %s\n' "$(python3 -c 'import venv;print("有")' 2>&1 | tail -1)"
printf '  ensurepip     : %s\n' "$(python3 -c 'import ensurepip;print("有")' 2>&1 | tail -1)"
echo "  所有已装的 python 版本:"
for p in /usr/bin/python3.* /usr/local/bin/python3.* /opt/*/bin/python3*; do
  [ -x "$p" ] && printf '    %-34s %s\n' "$p" "$($p -V 2>&1)"
done
echo "  ⚠️ 本项目要求 python >= 3.10（pyproject: requires-python）。"
echo "     Ubuntu 20.04 自带 3.8 → 若上面只看到 3.8，说明**必须自带解释器**。"

hr "3. GPU 与驱动（决定能不能跑三维视图）"
if have nvidia-smi; then
  nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv 2>/dev/null | sed 's/^/  /'
else
  echo "  ❌ 没有 nvidia-smi"
fi
if have lspci; then
  echo "  --- 显卡设备（lspci）---"
  lspci 2>/dev/null | grep -iE 'vga|3d|display' | sed 's/^/    /'
fi
echo "  --- OpenGL / 渲染 ---"
if have glxinfo; then
  glxinfo -B 2>/dev/null | head -12 | sed 's/^/    /'
else
  echo "    (没有 glxinfo；离线环境下可跳过 —— 三维视图用浏览器渲染，见第 7 节)"
fi
echo "  --- CUDA 工具链 ---"
printf '    nvcc: %s\n' "$(nvcc --version 2>/dev/null | tail -2 | head -1 || echo '(无)')"
printf '    /usr/local/cuda: %s\n' "$(ls -d /usr/local/cuda* 2>/dev/null | tr '\n' ' ' || echo '(无)')"

hr "4. 磁盘（Jetson 的瓶颈通常在这）"
df -hT 2>/dev/null | grep -vE 'tmpfs|udev|loop' | sed 's/^/  /'
echo "  --- 块设备 ---"
if have lsblk; then lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT 2>/dev/null | sed 's/^/    /'; fi
echo "  --- rootfs 在哪个设备上 ---"
findmnt -no SOURCE / 2>/dev/null | sed 's/^/    /'
echo "  ⚠️ Jetson 常见情况：系统跑在 64GB eMMC 上，另有一块 NVMe 未挂载/未使用。"
echo "     那正是 jetson-util 里 ssd-rootfs / ssd-backup-restore 要解决的事。"

hr "5. ROS（无人车侧已确认在跑 ROS）"
if [ -n "${ROS_DISTRO:-}" ]; then printf '  ROS_DISTRO(env): %s\n' "$ROS_DISTRO"; fi
for d in /opt/ros/*; do [ -d "$d" ] && printf '  已装 ROS: %s\n' "$(basename "$d")"; done
if have rosversion; then rosversion -d 2>/dev/null | sed 's/^/  rosversion -d: /'; fi
echo "  --- ROS 相关环境变量 ---"
env | grep -E '^(ROS_|AMENT_|COLCON_)' | sed 's/^/    /' || echo "    (无)"
echo "  --- ROS 包数量（粗估）---"
for d in /opt/ros/*; do
  [ -d "$d/share" ] && printf '    %s : %s 个包\n' "$(basename "$d")" "$(ls -1 "$d/share" 2>/dev/null | wc -l)"
done
echo "  --- 正在运行的 ROS 节点（若有）---"
if have rosnode; then timeout 8 rosnode list 2>/dev/null | head -20 | sed 's/^/    /' || echo "    (rosnode 无响应，可能 master 未起)"; fi

hr "6. 网络（离线环境里怎么连、连什么）"
echo "  --- 接口与地址 ---"
if have ip; then ip -brief addr 2>/dev/null | sed 's/^/    /'; fi
echo "  --- 默认路由 ---"
ip route 2>/dev/null | head -5 | sed 's/^/    /'
echo "  --- 无线（能不能连热点）---"
if have nmcli; then nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null | sed 's/^/    /'; fi
echo "  --- 监听端口（谁在跑）---"
if have ss; then ss -ltnup 2>/dev/null | head -25 | sed 's/^/    /'; fi

hr "7. 浏览器（三维视图靠它渲染）"
for b in google-chrome chromium chromium-browser firefox; do
  if have "$b"; then printf '  %-20s %s\n' "$b" "$("$b" --version 2>/dev/null | head -1)"; fi
done
echo "  ⚠️ 三维视图（simulation-3d）是 Vite + Three.js，在浏览器里跑。"
echo "     离线环境下 WebGL 能否启用取决于浏览器与驱动；本项决定它能不能显示。"

hr "8. 本项目需要但可能缺失的命令行工具"
for t in git curl python3 pip3 node npm ssh scp rsync gzip tar unzip make gcc; do
  if have "$t"; then
    printf '  %-8s ✅ %s\n' "$t" "$(command -v "$t")"
  else
    printf '  %-8s ❌ 缺失\n' "$t"
  fi
done
printf '  node/npm 版本: node=%s  npm=%s\n' "$(node -v 2>/dev/null || echo '-')" "$(npm -v 2>/dev/null || echo '-')"

hr "9. [需要 sudo] 完整硬件摘要"
if [ "$(id -u)" -eq 0 ]; then
  { lshw -short 2>/dev/null | head -30; } | sed 's/^/  /'
else
  echo "  （未以 root 运行，跳过）如需硬件摘要：sudo bash recon-offline-env.sh > recon-root.txt 2>&1"
fi

hr "10. 这台机器上有没有本项目/相关的东西"
for d in /opt /home /srv /data /mnt /media; do
  [ -d "$d" ] || continue
  found=$(find "$d" -maxdepth 4 -type d \( -iname '*uav*' -o -iname '*swarm*' -o -iname '*px4*' -o -iname '*gazebo*' -o -iname '*jetson*' \) 2>/dev/null | head -10)
  [ -n "$found" ] && { printf '  在 %s 下发现:\n' "$d"; printf '%s\n' "$found" | sed 's/^/    /'; }
done
echo "  （以上为空表示这台机器上还没有我们的东西）"

hr "报告结束"
echo "请把整份输出带回来。特别关注第 2 节（Python 版本）与第 4 节（磁盘）。"
