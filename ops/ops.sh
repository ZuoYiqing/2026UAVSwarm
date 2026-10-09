#!/usr/bin/env bash
# 2026UAVSwarm 运维工具
#
# 用法:
#   bash ops.sh status            # 只读体检（随时可跑）
#   bash ops.sh start             # 按顺序启动仿真 + Runtime（后台常驻）
#   bash ops.sh stop              # 按正确顺序停止（先 Runtime 后仿真）
#   bash ops.sh restart           # stop + start
#   bash ops.sh calib             # 发布一次标定
#   bash ops.sh calib-loop        # 循环发布标定（前台，Ctrl+C 停止）
#   bash ops.sh logs [sim|rt]     # 查看日志尾部
#
# 停止顺序的设计原因:
#   Runtime 独占 MAVLink 端口 14540-14542。必须先把 Runtime 停掉释放端口，
#   再停仿真；否则会残留占用，下次启动 preflight 直接失败。
#
# 标定 5 秒过期的原因:
#   标定的 valid_for_ms 约 5000ms。过期后 Runtime 置 calibration_status=stale，
#   前端拒绝显示飞机（这是设计，防止用过期坐标把飞机画在错误位置）。
#   想持续看到飞机必须循环发布 -> 用 calib-loop。

set -u

# REPO 可用环境变量覆盖。为什么需要：仿真侧的 harness 会把状态与标定证据写在
# **它自己所在的那个仓库** 的 .runtime/ 下（harness.py: REPO_ROOT = 其所在目录的上两级），
# 而 Runtime 只认 $REPO/.runtime/。若仿真在某个 worktree 里跑、Runtime 从主仓库起，
# 就会读到**过期的标定证据** —— 表现为"前端能连上飞机，但标定 stale、
# 三维视图不显示、goto 被拒"，即"看起来正常、实际不可用"。
REPO=${UAV_REPO:-/mnt/d/2026UAVSwarm}
OPS=/mnt/d/2026UAVSwarm-worktrees/_ops
LOG="$OPS/logs"
API=http://127.0.0.1:8765/api
SIM_LOG="$LOG/sim.log"
RT_LOG="$LOG/rt.log"
RT_PID_FILE="$LOG/rt.pid"

# 仿真 manifest 可用环境变量覆盖。默认是**无相机**的 x500 配置。
#
# ⚠️ 这个默认值是刻意保留的（它不是"漏了相机"）：不指定时行为与以前完全一致。
# 但必须**显式显示**当前用的是哪一份 —— 否则"跑的是无相机配置"这件事
# 在界面上看不出来：端口对、health ready、飞机能飞，**只有相机动作会失败**。
SIM_CONFIG=${UAV_SIM_CONFIG:-simulation/px4_gazebo/config/three_uav_sitl.json}
#: 仿真启动脚本的路径（相对 $REPO）。单独抽出来是因为 runbook 里还有别的入口，
#: 而这里必须与 stop 用的那个保持同一个来源。
SIM_CONFIG_START=simulation/px4_gazebo/scripts/start_three_uav.sh
SIM_STOP_SCRIPT=simulation/px4_gazebo/scripts/stop_three_uav.sh

# 相机版需要显卡适配器变量，否则 WSL 会挑到集显、RTF 掉到 0.1 附近。
# 实测（仿真侧验收报告）：0.175 → 0.839。这里只在用户没设时给默认值，
# 不覆盖用户的选择。
: "${UAV_GPU_ADAPTER:=NVIDIA}"

mkdir -p "$LOG"

c_ok()   { printf '\033[32m%s\033[0m\n' "$1"; }
c_err()  { printf '\033[31m%s\033[0m\n' "$1"; }
c_warn() { printf '\033[33m%s\033[0m\n' "$1"; }
c_dim()  { printf '\033[2m%s\033[0m\n' "$1"; }

# ---------- 配置自检 ----------
# 两个流程错位都会产生"看起来正常、实际不可用"的状态，所以这里主动报出来。
sim_config_is_camera() { case "$SIM_CONFIG" in *mono_cam*) return 0 ;; *) return 1 ;; esac; }

sim_config_exists() { [ -f "$REPO/$SIM_CONFIG" ]; }

manifest_model_names() {
  # 从 manifest 里取每台的 gazebo 模型名，用于显示"这次跑的是什么"。
  python3 - "$REPO/$SIM_CONFIG" <<'PY' 2>/dev/null || true
import json, sys
try:
    m = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit
names = [str(v.get("gazebo_model_name") or "?") for v in m.get("vehicles", [])]
print(", ".join(names) if names else "(manifest 里没有 vehicles)")
PY
}

report_sim_config() {
  echo "  manifest: $SIM_CONFIG"
  if ! sim_config_exists; then
    c_err "    ❌ 文件不存在：$REPO/$SIM_CONFIG"
    return 1
  fi
  if sim_config_is_camera; then
    c_ok "    ✅ 相机版（含 x500_mono_cam）"
  else
    c_warn "    ⚠️  无相机版（x500）—— 相机动作会失败，但端口/health/飞行都正常"
    c_dim "        要用相机版：UAV_SIM_CONFIG=simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json"
  fi
  local models
  models=$(manifest_model_names)
  [ -n "$models" ] && c_dim "    模型: $models"
  return 0
}

# Runtime 读的标定证据在 $REPO/.runtime/ 下。若它比仿真状态旧，说明两者不是同一次运行。
report_runtime_repo_alignment() {
  local state="$REPO/.runtime/px4_gazebo/harness_state.json"
  local calib="$REPO/.runtime/px4_gazebo/calibration/latest.json"
  local wt_state
  wt_state=$(ls -1 /mnt/d/2026UAVSwarm-worktrees/*/.runtime/px4_gazebo/harness_state.json 2>/dev/null | head -1)
  if [ ! -f "$state" ] && [ -n "$wt_state" ]; then
    c_err "    ❌ 本仓库没有 harness state，但 worktree 里有："
    c_dim "        $wt_state"
    c_warn "       仿真是在 worktree 里跑的，而 Runtime 只认 $REPO/.runtime/"
    c_warn "       → 标定会读到过期证据。要么从本仓库起仿真，"
    c_warn "         要么设 UAV_REPO=<那个 worktree> 让 ops.sh 跟着走。"
    return 1
  fi
  if [ -f "$state" ] && [ -f "$calib" ]; then
    if [ "$state" -nt "$calib" ]; then
      c_warn "    ⚠️  标定证据比仿真状态旧（不是同一次运行留下的）"
    fi
  fi
  return 0
}

# ---------- 只读检查 ----------
# 注意两处坑：
#   1. 用 'bin/px4' 精确匹配 —— 'px4' 会误匹配 sample_calibration.py 和它临时
#      拉起的 px4-listener（名字里含 px4），导致计数虚高。
#   2. 必须写 `2>/dev/null; }` 而不是 `2>/dev/null || echo 0` —— pgrep 找不到
#      匹配时既无 stdout 输出、又返回非零，`|| echo 0` 会让函数返回 "0\n0"
#      两行，后面 [ "$p" -ge 3 ] 就会报 integer expression expected。
px4_count()  { pgrep -cf 'bin/px4' 2>/dev/null; }
gz_count()   { pgrep -cf 'gz sim' 2>/dev/null; }
rt_count()   { pgrep -cf 'uav_runtime.http.server' 2>/dev/null; }
api_up()     { curl -sf --max-time 3 "$API/health" >/dev/null 2>&1; }
state_file() { [ -f "$REPO/.runtime/px4_gazebo/harness_state.json" ]; }

cmd_status() {
  echo "=== 2026UAVSwarm 状态 ==="
  cd "$REPO" 2>/dev/null || { c_err "找不到 $REPO"; return 1; }
  echo "工作区: $REPO"
  echo "HEAD:   $(git log -1 --oneline 2>/dev/null)"
  echo

  local p g r
  p=$(px4_count); p=${p:-0}
  g=$(gz_count);  g=${g:-0}
  r=$(rt_count);  r=${r:-0}

  echo "--- 配置（下面两个错位都会产生「看起来正常、实际不可用」的状态）---"
  echo "  REPO:     $REPO"
  report_sim_config
  report_runtime_repo_alignment
  echo

  echo "--- 进程 ---"
  [ "$p" -ge 3 ] && c_ok  "  PX4:     $p (需 3)" || c_err "  PX4:     $p (需 3)"
  [ "$g" -ge 1 ] && c_ok  "  Gazebo:  $g (需 1)" || c_err "  Gazebo:  $g (需 1)"
  [ "$r" -ge 1 ] && c_ok  "  Runtime: $r (需 1)" || c_err "  Runtime: $r (需 1)"
  echo

  echo "--- Runtime API ---"
  if api_up; then
    c_ok "  8765: 响应正常"
    python3 - <<'PY' 2>/dev/null
import json, urllib.request
try:
    d = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/vehicle-snapshot", timeout=8))
    for v in d.get("vehicles", []):
        s = v.get("spatial") or {}
        st = s.get("calibration_status")
        mark = "OK " if s.get("public_position_usable") else "-- "
        print("    %s%-7s status=%-11s age=%sms" % (
            mark, v.get("id"), st, s.get("calibration_age_ms")))
    if not d.get("vehicles"):
        print("    (无载具)")
except Exception as e:
    print("    vehicle-snapshot 读取失败:", e)
PY
  else
    c_err "  8765: 无响应（Runtime 未启动）"
  fi
  echo

  echo "--- 标定 ---"
  if [ -f "$REPO/.runtime/px4_gazebo/calibration/latest.json" ]; then
    c_dim "  latest.json 存在（注意：标定 5 秒过期，文件存在 ≠ 当前有效）"
  else
    c_warn "  尚无标定文件"
  fi
  echo

  echo "--- 端口 ---"
  ss -lunp 2>/dev/null | grep -qE '1454[0-2]' \
    && c_ok "  UDP 14540-14542: 已被占用（Runtime 持有，正常）" \
    || c_warn "  UDP 14540-14542: 空闲（Runtime 未接管）"
  ss -ltnp 2>/dev/null | grep -q 8765 \
    && c_ok "  TCP 8765: 监听中" \
    || c_err "  TCP 8765: 未监听"

  echo
  echo "--- 前端（在 Windows 浏览器里确认）---"
  # 注意：WSL -> Windows 的 localhost 转发通常不通，所以在 WSL 里 curl 5178/5179
  # 失败不代表前端没起。这里只做提示性检查，不计入整体结论。
  win_ok=0
  for port in 5178 5179; do
    if curl -sf --max-time 2 "http://127.0.0.1:$port/" >/dev/null 2>&1; then
      c_ok "  $port: WSL 可访问"
      win_ok=$((win_ok+1))
    fi
  done
  if [ "$win_ok" -eq 0 ]; then
    c_dim "  WSL 侧无法探测（正常现象）。请在 Windows 浏览器打开:"
    c_dim "    http://localhost:5178/  → 三维集群态势 → simple_recon · 后端任务坐标"
  fi
  return 0
}

# ---------- 启动 ----------
cmd_start() {
  cd "$REPO" || { c_err "找不到 $REPO"; return 1; }

  echo "=== 启动仿真层 ==="
  local p g
  p=$(px4_count); p=${p:-0}
  g=$(gz_count);  g=${g:-0}
  if [ "$p" -ge 3 ] && state_file; then
    c_dim "  仿真已在运行，跳过"
  else
    if [ "$p" -gt 0 ] || [ "$g" -gt 0 ]; then
      c_warn "  检测到残留进程，先清理"
      bash "$SIM_STOP_SCRIPT" >/dev/null 2>&1 || true
      sleep 2
    fi
    echo "  启动 PX4 + Gazebo（日志: $SIM_LOG）..."
    echo "  配置:"; report_sim_config || return 1
    # 相机版必须显式指定适配器，否则 WSL 会挑到集显、RTF 掉到 0.1 附近
    # （实测 0.175 vs 0.839）。只对相机版设，避免影响无相机场景。
    if sim_config_is_camera && [ -n "${UAV_GPU_ADAPTER:-}" ]; then
      c_dim "    MESA_D3D12_DEFAULT_ADAPTER_NAME=$UAV_GPU_ADAPTER"
      nohup env "MESA_D3D12_DEFAULT_ADAPTER_NAME=$UAV_GPU_ADAPTER" \
        bash "$SIM_CONFIG_START" --headless --config "$SIM_CONFIG" \
        >"$SIM_LOG" 2>&1 &
    else
      nohup bash "$SIM_CONFIG_START" --headless --config "$SIM_CONFIG" \
        >"$SIM_LOG" 2>&1 &
    fi
    # 等待 harness 写出状态文件
    for i in $(seq 1 60); do
      p=$(px4_count); p=${p:-0}
      if [ "$p" -ge 3 ] && state_file; then break; fi
      sleep 1
    done
    p=$(px4_count); p=${p:-0}
    if [ "$p" -ge 3 ]; then
      c_ok "  仿真就绪（PX4=$p）"
    else
      c_err "  仿真启动超时，检查 $SIM_LOG"
      return 1
    fi
  fi
  echo

  echo "=== 启动 Runtime ==="
  if api_up; then
    c_dim "  Runtime 已在运行，跳过"
  else
    # 关键：等 PX4 的 Onboard MAVLink 实例真正开始外发。
    # 只等进程出现是不够的 —— Runtime 的 collector 连接时有 heartbeat_timeout，
    # 而 start_vehicle 失败后不会自动重试。若起得太早（UAV-03 的 MAVLink 尚未
    # 就绪），该节点会永久停在 offline，直到 Runtime 重启。
    echo "  等待 PX4 MAVLink 实例就绪..."
    local n
    for i in $(seq 1 20); do
      n=$(grep -c 'mode: Onboard' "$REPO"/.runtime/px4_gazebo/UAV-0*/stdout.log 2>/dev/null \
          | awk -F: '{s+=$2} END {print s+0}')
      [ "${n:-0}" -ge 3 ] && break
      sleep 1
    done
    echo "    Onboard MAVLink 记录: ${n:-0} 行，再等 3 秒"
    sleep 3

    echo "  启动 HTTP bridge（日志: $RT_LOG）..."
    # -u 关闭 stdout 缓冲，否则重定向到文件后 "listening on ..." 不会落盘
    PYTHONPATH="$REPO/src" nohup python3 -u -m uav_runtime.http.server \
      >"$RT_LOG" 2>&1 &
    echo $! > "$RT_PID_FILE"
    for i in $(seq 1 30); do
      if api_up; then break; fi
      sleep 1
    done
    if api_up; then
      c_ok "  Runtime 就绪（pid $(cat "$RT_PID_FILE" 2>/dev/null)）"
    else
      c_err "  Runtime 启动超时，检查 $RT_LOG"
      return 1
    fi

    # 校验三个 collector 是否全部绑上（失败节点不会自愈，必须重启 Runtime）
    sleep 2
    local conn
    conn=$(python3 - <<'PY'
import json, urllib.request
try:
    d = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/vehicles", timeout=8))
    print(sum(1 for v in d.get("vehicles", []) if v.get("connected")))
except Exception:
    print(-1)
PY
)
    conn=${conn:-0}
    if [ "$conn" -eq 3 ]; then
      c_ok "  三个 collector 全部连接（3/3）"
    else
      c_warn "  仅 $conn/3 连接 —— 存在心跳超时节点，自动重启 Runtime 重试"
      local rpids
      rpids=$(pgrep -f 'uav_runtime.http.server' 2>/dev/null || true)
      for pid in $rpids; do kill "$pid" 2>/dev/null || true; done
      sleep 4
      PYTHONPATH="$REPO/src" nohup python3 -u -m uav_runtime.http.server \
        >"$RT_LOG" 2>&1 &
      echo $! > "$RT_PID_FILE"
      for i in $(seq 1 30); do
        if api_up; then break; fi
        sleep 1
      done
      sleep 3
      conn=$(python3 - <<'PY'
import json, urllib.request
try:
    d = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/vehicles", timeout=8))
    print(sum(1 for v in d.get("vehicles", []) if v.get("connected")))
except Exception:
    print(-1)
PY
)
      conn=${conn:-0}
      [ "$conn" -eq 3 ] \
        && c_ok "  重试后三台全部连接（3/3）" \
        || c_err "  重试后仍只有 $conn/3，请查看: bash ops.sh status"
    fi
  fi
  echo

  echo "=== 下一步 ==="
  c_warn "  标定尚未发布 —— 三维视图不会显示载具"
  echo "  发布一次（有效期 60 秒，日常够用）:"
  echo "    bash $OPS/ops.sh calib-once"
  echo "  长时间演示则用循环刷新:"
  echo "    bash $OPS/ops.sh calib-loop"
  echo
  echo "  Windows 侧前端（如果没起）:"
  echo "    5178:  cd D:\\2026UAVSwarm && python -m http.server 5178 --directory frontend\\swarm-console"
  echo "    5179:  cd D:\\2026UAVSwarm\\frontend\\swarm-console\\simulation-3d && npm run dev"
}

# ---------- 停止 ----------
cmd_stop() {
  cd "$REPO" || { c_err "找不到 $REPO"; return 1; }

  echo "=== 停止 Runtime（必须先停，它独占 MAVLink 端口）==="
  local pids rc
  pids=$(pgrep -f 'uav_runtime.http.server' 2>/dev/null || true)
  if [ -n "$pids" ]; then
    # 按 pgrep 结果精确 kill，不用 pkill -f 通配
    for pid in $pids; do kill "$pid" 2>/dev/null || true; done
    for i in $(seq 1 10); do
      rc=$(rt_count); rc=${rc:-0}
      [ "$rc" -eq 0 ] && break
      sleep 1
    done
    rc=$(rt_count); rc=${rc:-0}
    if [ "$rc" -eq 0 ]; then
      c_ok "  Runtime 已停止"
    else
      c_warn "  Runtime 未退出，发送 SIGKILL"
      for pid in $pids; do kill -9 "$pid" 2>/dev/null || true; done
      sleep 1
    fi
  else
    c_dim "  Runtime 未运行"
  fi
  rm -f "$RT_PID_FILE"
  echo

  echo "=== 停止仿真 ==="
  local sp sg
  sp=$(px4_count); sp=${sp:-0}
  sg=$(gz_count);  sg=${sg:-0}
  if [ "$sp" -gt 0 ] || [ "$sg" -gt 0 ] || state_file; then
    bash "$SIM_STOP_SCRIPT" 2>&1 | \
      python3 -c "
import json,sys
raw=sys.stdin.read()
try:
    d=json.loads(raw)
    print('  status:', d.get('status'), '| clean:', (d.get('cleanup') or {}).get('clean'))
except Exception:
    print(raw[:400])
"
  else
    c_dim "  仿真未运行"
  fi
  echo

  echo "=== 残留检查 ==="
  local leftover
  leftover=$(pgrep -f 'uav_runtime.http.server|px4|gz sim' 2>/dev/null | wc -l)
  [ "$leftover" -eq 0 ] && c_ok "  无残留进程" || c_warn "  仍有 $leftover 个相关进程"
  ss -lunp 2>/dev/null | grep -qE '1454[0-2]' \
    && c_warn "  端口 14540-14542 仍被占用" || c_ok "  端口已释放"
}

# ---------- 标定 ----------
# 标定是"让三维视图能看到载具"的必要条件：PX4 只知道自己在自身 EKF 原点下的
# 位置，共享场景坐标系下的偏移必须由仿真实测并发布给 Runtime。没有标定，
# 三维视图会拒绝显示载具（安全设计）。
#
# 有效期 60 秒，所以：
#   calib-once  → 发布一次，够用一分钟（日常演示足够）
#   calib-loop  → 循环刷新，长时间演示时用（Ctrl+C 停止）
cmd_calib() {
  exec bash "$OPS/calib.sh" once "${1:-2}"
}
cmd_calib_loop() {
  exec bash "$OPS/calib.sh" loop
}
cmd_calib_once() {
  exec bash "$OPS/calib.sh" once "${1:-2}"
}

# 清理 WSLg 留下的孤儿图形窗口。
#
# 现象：Gazebo 带 GUI 运行时，WSL 侧进程被杀掉后，Windows 侧仍会留下一个
# "Gazebo Sim (Ubuntu)" 窗口（由 msrdc.exe 持有）。此时 `ops.sh stop` 会报告
# "仿真未运行" —— WSL 侧确实干净了 —— 但屏幕上那个窗口还在，看起来像卡死。
#
# 只关闭**窗口标题匹配 Gazebo** 的进程，不动其它 WSLg 窗口：
# 其它 Linux GUI 程序也共用 msrdc，按进程名误杀会关掉它们的窗口。
cmd_cleanup() {
  echo "=== 清理 WSLg 孤儿图形窗口 ==="
  if ! command -v powershell.exe >/dev/null 2>&1; then
    c_warn "  无法调用 powershell.exe（不在 WSL 里？），请手动关闭窗口"
    return 0
  fi
  powershell.exe -NoProfile -Command '
    $procs = Get-Process | Where-Object { $_.MainWindowTitle -match "Gazebo|gz sim" }
    if (-not $procs) { Write-Output "  没有 Gazebo 窗口"; exit 0 }
    foreach ($p in $procs) {
      Write-Output ("  关闭: {0} (PID {1}) 窗口[{2}]" -f $p.ProcessName, $p.Id, $p.MainWindowTitle)
      Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
  ' 2>/dev/null | sed 's/\r$//'
  echo "  完成（WSL 侧进程不受影响，如需停止仿真请用 stop）"
}

# 尝试通过 WSL interop 启动 Windows 前端。
#
# 实测结论（重要）：
#   从 WSL 启动 Windows 的**交互式窗口**不可靠 —— `cmd.exe /c start ... /k`
#   产生的窗口会持有 stdout 管道，wsl.exe 会一直等待管道 EOF 而挂死。
#   实测结果不稳定：5178 成功过一次，5179（npm run dev）始终没起来。
#   因此本命令默认只做**探测 + 打印命令**，由你在 Windows 侧手动启动。
#   如果确实要用 interop 尝试，加参数 force。
cmd_win_start() {
  echo "=== Windows 前端 ==="

  # 重要：WSL -> Windows 的 localhost 转发通常不通，所以在 WSL 里 curl 5178/5179
  # 失败**不能**说明前端没起。只有探测本身可信时（interop 可用）才据此判断。
  local can_probe=0
  [ -x /mnt/c/Windows/system32/cmd.exe ] && can_probe=1

  local ok=0 unsure=0
  for port in 5178 5179; do
    if curl -sf --max-time 2 "http://localhost:$port/" >/dev/null 2>&1; then
      c_ok "  $port: 已在运行"
      ok=$((ok+1))
    else
      if [ "$can_probe" -eq 1 ]; then
        c_err "  $port: 未响应"
      else
        c_dim "  $port: 无法从 WSL 探测（转发方向限制，不代表未启动）"
        unsure=$((unsure+1))
      fi
    fi
  done
  echo

  if [ "$ok" -ge 2 ]; then
    echo "  两个前端均已就绪"
    echo "  浏览器: http://localhost:5178/  → 三维集群态势 → simple_recon · 后端任务坐标"
    return 0
  fi

  local wroot
  wroot=$(wslpath -w "$REPO" 2>/dev/null)
  [ -z "$wroot" ] && wroot='D:\2026UAVSwarm'

  echo "  请在 Windows 的两个 PowerShell 窗口里分别执行:"
  echo
  echo "  ---- 窗口 1: 主控制台 (5178) ----"
  echo "  cd $wroot"
  echo "  python -m http.server 5178 --directory frontend\\swarm-console"
  echo
  echo "  ---- 窗口 2: 三维视图 (5179) ----"
  echo "  cd $wroot\\frontend\\swarm-console\\simulation-3d"
  echo "  npm run dev"
  echo
  echo "  然后浏览器打开: http://localhost:5178/"
  echo "  场景下拉框选第三项: simple_recon · 后端任务坐标"
  echo
  echo "  提示: 用 PowerShell 验证前端是否在跑 ->  Invoke-WebRequest http://localhost:5178/"
  echo

  if [ "${2:-}" = "force" ]; then
    c_warn "  尝试用 interop 启动（可能挂起，结果不保证）..."
    cmd.exe /c start "" cmd /k \
      "cd /d $wroot && python -m http.server 5178 --directory frontend\\swarm-console" \
      </dev/null >/dev/null 2>&1 &
    c_dim "  已发出 5178 启动请求（后台）"
  fi
  return 0
}

cmd_win_stop() {
  echo "=== 停止 Windows 前端 ==="
  local stopped=0
  for port in 5178 5179; do
    local pid
    pid=$(netstat.exe -ano 2>/dev/null | grep -E "LISTENING" | grep ":$port " | awk '{print $5}' | head -1)
    if [ -n "$pid" ]; then
      taskkill.exe /PID "$pid" /F >/dev/null 2>&1 && { c_ok "  已停止 $port (pid $pid)"; stopped=$((stopped+1)); }
    else
      c_dim "  $port 未在监听"
    fi
  done
  [ "$stopped" -eq 0 ] && c_dim "  没有需要停止的前端进程"
  return 0
}

cmd_logs() {
  case "${1:-rt}" in
    sim) tail -n 40 "$SIM_LOG" 2>/dev/null || echo "无日志" ;;
    rt)  tail -n 40 "$RT_LOG"  2>/dev/null || echo "无日志" ;;
    *)   echo "用法: ops.sh logs [sim|rt]" ;;
  esac
}

case "${1:-status}" in
  status)     cmd_status ;;
  start)      cmd_start ;;
  stop)       cmd_stop ;;
  restart)    cmd_stop && echo && cmd_start ;;
  calib)      cmd_calib "${2:-2}" ;;
  calib-once) cmd_calib_once "${2:-2}" ;;
  calib-loop) cmd_calib_loop ;;
  cleanup)    cmd_cleanup ;;
  win-start)  cmd_win_start ;;
  win-stop)   cmd_win_stop ;;
  logs)       cmd_logs "${2:-rt}" ;;
  *)
    cat <<EOF
2026UAVSwarm 运维工具

  status        只读体检（进程/API/标定/端口）
  start         启动仿真 + Runtime（后台常驻，日志落盘）
  stop          按正确顺序停止（先 Runtime 后仿真）
  restart       stop + start  ⚠️ 会清空标定，之后必须重发

  calib-once    发布一次标定（有效期 60 秒，日常够用）
  calib-loop    循环刷新标定（长时间演示用，Ctrl+C 停止）
  calib [秒]    calib-once 的别名

  cleanup       关闭 WSLg 遗留的 Gazebo 孤儿窗口（stop 之后窗口仍卡在屏幕上时用）

  win-start     探测前端状态并打印 Windows 侧启动命令
  win-stop      停止 Windows 侧前端进程
  logs [sim|rt] 查看日志尾部

典型流程:
  bash ops.sh start          # 1. 起仿真 + Runtime（等待并校验，自动重试）
  bash ops.sh calib-once     # 2. 发布标定（否则三维视图看不到载具）
  # Windows 侧起两个前端（见 win-start 打印的命令）
  # 浏览器 http://localhost:5178/ → 三维集群态势 → simple_recon · 后端任务坐标

长时间演示时把第 2 步换成 calib-loop。

日志目录: $LOG
EOF
    ;;
esac
