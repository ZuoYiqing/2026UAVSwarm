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

hr "11. 能力评级与建议用途"

# 判定依据全部来自本项目实测，不是猜的：
#   · 仿真：相机版三机在 RTX 4050 上 RTF 0.84~0.94；不设 GPU 适配器变量只有 0.175，
#     而只有核显的机器会掉到同一量级 → 没有独显就没有可用的仿真。
#   · Runtime：pyproject 要求 python >= 3.10（Ubuntu 20.04 自带 3.8，不够）。
#   · 前端：主控台纯静态；三维要 WebGL，旧核显驱动（如 2018 年的 Intel 驱动）有白屏风险。
PY_OK=no
PV=0.0
if command -v python3 >/dev/null 2>&1; then
  PV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)
  case "$PV" in
    3.10|3.11|3.12|3.13|3.14) PY_OK=yes ;;
  esac
fi
GPU_NV=no
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi >/dev/null 2>&1 && GPU_NV=yes
fi
MEM_GB=$(awk '/MemTotal/{printf "%d", $2/1048576}' /proc/meminfo 2>/dev/null)
MEM_GB=${MEM_GB:-0}
# ⚠️ `df -BG --output=avail /` 会给出 **1K 块数**（不是 GB），而且
# `tr -dc '0-9'` 会把 "块数 可用" 两列粘成一个天文数字（实测拿到 1007199372GB）。
# 用 --output=avail 的固定列 + 显式去单位，才稳。
DISK_GB=$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -d ' G')
DISK_GB=${DISK_GB:-0}
case "$DISK_GB" in ''|*[!0-9]*) DISK_GB=0 ;; esac
ARCH=$(uname -m)

# ⚠️ 在 WSL 里，这两个数**不代表真机**：MemTotal 是 WSL2 的内存上限，
# 而浏览器装在 Windows 侧、WSL 里看不到。所以检测到 WSL 时要明确标注，
# 免得把"WSL 的限制"当成"这台机器的能力"。
IS_WSL=no
grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null && IS_WSL=yes

echo "  事实: python3=$PV (>=3.10? $PY_OK)  nvidia-smi=$GPU_NV  RAM=${MEM_GB}GB  /可用=${DISK_GB}GB  arch=$ARCH"
if [ "$IS_WSL" = yes ]; then
  echo "  ⚠️ 这是 WSL：RAM 是 WSL2 的上限、浏览器在 Windows 侧（这里看不到）。"
  echo "     判断这台**整机**能不能跑仿真/显示，请以 Windows 侧为准（用 recon-windows.ps1）。"
fi
echo
echo "  --- 各能力判定 ---"
if [ "$GPU_NV" = yes ] && [ "$MEM_GB" -ge 16 ] && [ "$ARCH" = x86_64 ]; then
  echo "  [能]   跑仿真 (PX4+Gazebo 相机版三机) —— 有独显且内存够"
else
  echo "  [不能] 跑仿真 —— 缺独显或内存不足；核显会掉到 RTF ~0.18（门槛 0.20）"
fi
if [ "$PY_OK" = yes ]; then
  echo "  [能]   跑 Runtime (uav_runtime) —— python $PV 满足 >=3.10"
else
  echo "  [不能] 跑 Runtime —— python $PV 不满足 >=3.10（需自带解释器或另装）"
fi
if command -v python3 >/dev/null 2>&1; then
  echo "  [能]   跑前端静态服务 —— python3 可起 http.server"
fi
HAS_BROWSER=no
if command -v firefox >/dev/null 2>&1 || command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
  HAS_BROWSER=yes
fi
if [ "$HAS_BROWSER" = yes ]; then
  echo "  [能]   显示控制台 —— 有浏览器（三维另需 WebGL，见第 7 节）"
elif [ "$IS_WSL" = yes ]; then
  echo "  [?]    显示控制台 —— WSL 内看不到浏览器；Windows 侧通常有，以 recon-windows.ps1 为准"
else
  echo "  [!]    显示控制台 —— 未发现浏览器，需安装或换机器"
fi
if [ "$GPU_NV" = yes ] && [ "$ARCH" = x86_64 ]; then
  echo "  [能]   当'模拟无人平台' —— 可装 PX4 SITL 假装一台机"
fi

echo
echo "  --- 建议用途（按优先级）---"
if [ "$IS_WSL" = yes ]; then
  # WSL 的结论**不能代表整机**：RAM 是 WSL2 上限、浏览器在 Windows 侧、
  # nvidia-smi 看到的是透传的 GPU。所以这里不下结论，明确指向 Windows 侧。
  echo "    ⚠️ 不下结论：WSL 视图不代表整机。"
  echo "       请以 Windows 侧为准：powershell -File ops\\recon-windows.ps1"
  echo "       上面那些 [能]/[不能] 只反映 WSL 这个运行环境，不是这台机器的能力。"
elif [ "$ARCH" = aarch64 ]; then
  echo "    1) 机载计算 / 真机侧 Runtime（需 python>=3.10）  2) 模型推理（CUDA/TensorRT）"
  echo "    x 不要指望它跑仿真：Gazebo 在 Jetson 上既慢又无意义"
elif [ "$HAS_BROWSER" = yes ]; then
  if [ "$GPU_NV" = yes ] && [ "$MEM_GB" -ge 16 ]; then
    echo "    1) 仿真主机（PX4+Gazebo）  2) 前端显示  3) Runtime（若 python>=3.10）"
  else
    echo "    1) 前端显示  2) Runtime（若 python>=3.10）  3) 加独显后可升级为仿真主机"
  fi
elif [ "$GPU_NV" = yes ] && [ "$MEM_GB" -ge 16 ]; then
  echo "    1) 仿真主机（PX4+Gazebo，无头也能跑）  2) Runtime"
  echo "    ! 没有浏览器，显示不了控制台；要么装浏览器，要么把显示交给另一台"
else
  echo "    1) 存储 / 中转  2) 加浏览器后可当前端显示"
  echo "    x 跑不了 Runtime（python 太旧或未装）、跑不了仿真（无独显）、显示不了（无浏览器）"
fi

hr "报告结束"
echo "请把整份输出带回来。最要紧的是第 11 节（评级）与第 2 节（Python）。"
