#!/usr/bin/env python3
"""环境自检：**迁移到新机器后跑这一条**，它会告诉你还差什么。

为什么要有它
------------
迁移文档里的清单靠人去核对，容易漏。这个脚本把「这台机器能不能跑四模块」
变成一条命令，逐项检查并给出**可执行的下一步**。

设计取舍
--------
· **只读**。不启动、不停止任何东西，不改任何文件。可以随时安全运行。
· **不猜**。每一项都实测；测不到就报 `unknown`，**不报通过**。
· **区分"必需"与"可选"**。缺 GPU 只影响实时因子，缺 pymavlink 则完全跑不了。

用法
----
    python3 scripts/check_environment.py            # 全部检查
    python3 scripts/check_environment.py --quiet    # 只报问题

退出码：0 = 必需项全过；1 = 有必需项失败；2 = 本脚本自身无法运行（非 Linux/WSL）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ⚠️ Windows 控制台默认是 GBK，打印 ✅/❌ 会抛 UnicodeEncodeError **直接打挂脚本**。
# 本脚本主要给 WSL/Linux 用，但在 Windows 上运行（比如从 PowerShell 调）也不该崩。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

# ---------------------------------------------------------------- 输出助手

_TTY = sys.stdout.isatty()


def _c(code: str) -> str:
    return code if _TTY else ""


OK, BAD, WARN, DIM, END = _c("\033[32m"), _c("\033[31m"), _c("\033[33m"), _c("\033[2m"), _c("\033[0m")

#: 结果分三级。`unknown` 既不等于通过也不等于失败 —— 迁移文档里反复强调
#: "不能把缺失当否定"，对自检同样成立。
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"


class Report:
    def __init__(self, quiet: bool = False) -> None:
        self.rows: list[tuple[str, str, str, str, bool]] = []
        self.quiet = quiet

    def add(self, name: str, status: str, detail: str, hint: str = "", required: bool = True) -> None:
        self.rows.append((name, status, detail, hint, required))

    def show(self) -> None:
        print()
        print("=" * 78)
        print("环境自检结果")
        print("=" * 78)
        width = max(len(r[0]) for r in self.rows) if self.rows else 10
        for name, status, detail, hint, required in self.rows:
            if self.quiet and status == PASS:
                continue
            mark = {"pass": f"{OK}✅{END}", "fail": f"{BAD}❌{END}", "unknown": f"{WARN}❓{END}"}[status]
            tag = "" if required else f"{DIM}(可选){END}"
            print(f"  {mark} {name:<{width}}  {detail} {tag}")
            if hint and status != PASS:
                for line in hint.splitlines():
                    print(f"      {DIM}→ {line}{END}")
        failed = [r for r in self.rows if r[1] == FAIL and r[4]]
        unknown = [r for r in self.rows if r[1] == UNKNOWN and r[4]]
        print()
        if failed:
            print(f"  {BAD}必需项失败 {len(failed)} 个{END} —— 见上面的 → 提示")
        elif unknown:
            print(f"  {WARN}必需项有 {len(unknown)} 个无法判定{END} —— 逐个人工确认，不要当通过")
        else:
            print(f"  {OK}必需项全部通过{END}")
        print()


# ---------------------------------------------------------------- 单项检查


def _run(command: list[str], timeout: float = 20.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, f"{type(exc).__name__}:{exc}"


def check_platform(report: Report) -> None:
    if sys.platform.startswith("linux"):
        report.add("运行平台", PASS, f"linux ({os.uname().machine})")
    else:
        # 仿真 harness 明确拒绝非 Linux/WSL。
        report.add(
            "运行平台", FAIL, sys.platform,
            "仿真只能在 Linux/WSL 里跑。用 `wsl.exe -e bash` 从 WSL 侧运行本脚本。",
        )


def check_repo(report: Report) -> None:
    repo = Path(__file__).resolve().parents[1]
    marker = repo / "simulation/px4_gazebo/harness.py"
    if marker.is_file():
        report.add("仓库结构", PASS, str(repo))
    else:
        report.add("仓库结构", FAIL, f"{repo} 里没有 simulation/px4_gazebo/harness.py",
                   "从仓库根运行 scripts/check_environment.py")
    # 路径约定：harness 的 REPO_ROOT 是它所在目录的上两级，状态与标定都写在那里。
    runtime_dir = repo / ".runtime/px4_gazebo"
    report.add(
        "运行产物目录", PASS if runtime_dir.is_dir() else UNKNOWN,
        str(runtime_dir) if runtime_dir.is_dir() else "不存在（还没跑过仿真，正常）",
    )


def check_px4(report: Report) -> None:
    candidates = [
        Path.home() / "PX4-Autopilot",
        Path("/opt/PX4-Autopilot"),
        Path(os.environ.get("PX4_DIR", "/nonexistent")),
    ]
    px4_dir = next((p for p in candidates if (p / "build/px4_sitl_default/bin/px4").is_file()), None)
    if px4_dir is None:
        report.add(
            "PX4 二进制", FAIL, "没找到 build/px4_sitl_default/bin/px4",
            "编译 PX4：\n"
            "  git clone https://github.com/PX4/PX4-Autopilot ~/PX4-Autopilot\n"
            "  cd ~/PX4-Autopilot && git submodule update --init --recursive\n"
            "  make px4_sitl_default\n"
            "或设 PX4_DIR 指向已编译的 PX4-Autopilot。",
        )
        return
    code, out = _run([str(px4_dir / "build/px4_sitl_default/bin/px4"), "--help"], timeout=20)
    # ⚠️ `px4 --version` 不是合法 flag（实测输出 "unrecognized flag"）。
    # 所以这里不拿某个 flag 的退出码当"二进制可用"的判据 —— 那会误报失败。
    # 二进制**存在且可执行**才是本项要回答的，`--help` 的输出不作为判据。
    usable = (px4_dir / "build/px4_sitl_default/bin/px4").stat().st_mode & 0o111 != 0
    report.add("PX4 二进制", PASS if usable else FAIL,
               f"{px4_dir}（存在且可执行）" if usable else f"{px4_dir} 不可执行",
               None if usable else f"chmod +x {px4_dir}/build/px4_sitl_default/bin/px4")
    code, out = _run(["git", "-C", str(px4_dir), "rev-parse", "HEAD"])
    if code == 0:
        report.add("PX4 提交", PASS, out.strip()[:12])


def check_gazebo(report: Report) -> None:
    exe = shutil.which("gz")
    if exe is None:
        report.add(
            "Gazebo (gz)", FAIL, "PATH 里没有 gz",
            "装 Gazebo Harmonic 并加入 PATH。PX4 的 gz_x500 需要它。",
        )
        return
    code, out = _run(["gz", "sim", "--versions"], timeout=25)
    report.add("Gazebo (gz)", PASS if code == 0 else UNKNOWN, out.strip().splitlines()[0][:60] if out.strip() else "(无版本输出)")


def check_python(report: Report) -> None:
    report.add("Python", PASS if sys.version_info >= (3, 10) else FAIL,
               f"{sys.version.split()[0]}",
               None if sys.version_info >= (3, 10) else "需要 3.10 或更高")
    try:
        import pymavlink  # noqa: F401
        report.add("pymavlink", PASS, getattr(pymavlink, "__version__", "?"))
    except ImportError:
        report.add("pymavlink", FAIL, "未安装",
                   "pip install pymavlink   （或 apt install python3-pymavlink）")
    try:
        import pytest  # noqa: F401
        report.add("pytest", PASS, getattr(pytest, "__version__", "?"), required=False)
    except ImportError:
        # ⚠️ 用 `sys.executable -m pytest` 判断"这个解释器能不能跑测试"，
        # 而不是 `shutil.which("pytest")` —— 后者会命中另一个解释器安装的
        # 可执行文件，给出**虚假的通过**（实测：WSL 的 python3 没装 pytest，
        # 但 `which pytest` 因为 Windows 侧装了而能找到）。
        # pytest 是可选：开发/回归需要，运行四模块不需要。
        report.add("pytest", UNKNOWN, f"当前解释器没装（{sys.executable}）",
                   "要跑测试才需要：python3 -m pip install pytest\n"
                   "只跑仿真/Runtime/前端**不需要**它。",
                   required=False)


def check_gpu(report: Report) -> None:
    """GPU 只影响实时因子，不影响功能 —— 所以是**可选**项。

    但相机版仿真对它有强依赖：实测不加适配器变量时 RTF 从 0.839 掉到 0.175。
    """
    code, out = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                      "--format=csv,noheader"], timeout=20)
    if code != 0:
        report.add("NVIDIA GPU", UNKNOWN, "nvidia-smi 不可用",
                   "无相机仿真不依赖 GPU。相机版需要 GPU，否则实时因子会很低。",
                   required=False)
        return
    report.add("NVIDIA GPU", PASS, out.strip()[:80], required=False)
    adapter = os.environ.get("MESA_D3D12_DEFAULT_ADAPTER_NAME")
    report.add(
        "GPU 适配器变量", PASS if adapter else WARN, adapter or "未设置",
        "相机版仿真必须设：MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA\n"
        "不设的话 WSL 会挑集显，实测实时因子 0.839 → 0.175。",
        required=False,
    )


def check_ports(report: Report) -> None:
    """14540-14542 是 Runtime 的监听口，必须空闲才能起 Runtime。

    ⚠️ 读 `/proc/net/udp` **需要 root**（普通用户得到空内容，不是错误）。
    所以这里必须区分"读到且端口空闲"与"读不到"：
    把读不到当"空闲"会给出一个**虚假的通过** —— 而这正是本项目反复踩的那类错。
    """
    try:
        text = Path("/proc/net/udp").read_text(encoding="utf-8")
    except OSError as exc:
        report.add("MAVLink 端口", UNKNOWN, f"读不到 /proc/net/udp（{exc.__class__.__name__}）",
                   "普通用户读不到它是正常的。改用需要 sudo 的等价检查：\n"
                   "  sudo ss -lunp | grep -E '1454[0-2]'\n"
                   "或直接问 Runtime：curl -s http://127.0.0.1:8765/api/health",
                   required=False)
        return
    busy = set()
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) > 1:
            try:
                busy.add(int(fields[1].split(":")[1], 16))
            except (IndexError, ValueError):
                continue
    if not busy:
        # 读到了内容却一个端口都没有 —— 几乎不可能，说明解析假设不成立。
        report.add("MAVLink 端口", UNKNOWN, "解析 /proc/net/udp 得到空集合",
                   "格式假设可能已变。用 sudo ss -lunp 人工确认。", required=False)
        return
    occupied = [p for p in (14540, 14541, 14542) if p in busy]
    if occupied:
        report.add("MAVLink 端口", WARN, f"{occupied} 被占用",
                   "若仿真/Runtime 已在跑，这是正常的。\n"
                   "若要重新启动，先停：bash simulation/px4_gazebo/scripts/stop_three_uav.sh",
                   required=False)
    else:
        report.add("MAVLink 端口", PASS, "14540-14542 空闲", required=False)


def check_manifests(report: Report) -> None:
    """两份 manifest 必须都在，且模型名真的不同。

    混淆它们是本项目最常见的坑（起默认版却以为在跑相机版）。
    """
    repo = Path(__file__).resolve().parents[1]
    config = repo / "simulation/px4_gazebo/config"
    pair = {
        "默认（无相机）": config / "three_uav_sitl.json",
        "相机版": config / "three_uav_mono_cam_sitl.json",
    }
    missing = [name for name, path in pair.items() if not path.is_file()]
    if missing:
        report.add("仿真 manifest", FAIL, f"缺 {missing}", "仓库不完整，重新 clone")
        return
    try:
        default = json.loads(pair["默认（无相机）"].read_text(encoding="utf-8"))
        camera = json.loads(pair["相机版"].read_text(encoding="utf-8"))
        default_models = [v["gazebo_model_name"] for v in default["vehicles"]]
        camera_models = [v["gazebo_model_name"] for v in camera["vehicles"]]
    except (OSError, ValueError, KeyError) as exc:
        report.add("仿真 manifest", FAIL, f"解析失败: {exc}")
        return
    if default_models == camera_models:
        report.add("仿真 manifest", FAIL, "两份 manifest 的模型名相同",
                   "那说明两份配置被改混了。相机版必须是 x500_mono_cam_*")
        return
    report.add("仿真 manifest", PASS, f"默认 {default_models[0]} / 相机 {camera_models[0]}")


def check_scene(report: Report) -> None:
    repo = Path(__file__).resolve().parents[1]
    world = repo / "scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf"
    report.add("场景文件", PASS if world.is_file() else FAIL,
               str(world.relative_to(repo)) if world.is_file() else "缺失",
               None if world.is_file() else "仓库不完整")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="只显示非通过项")
    args = parser.parse_args(argv)

    report = Report(quiet=args.quiet)
    check_platform(report)
    check_repo(report)
    check_python(report)
    check_px4(report)
    check_gazebo(report)
    check_manifests(report)
    check_scene(report)
    check_gpu(report)
    check_ports(report)
    report.show()

    if any(r[1] == FAIL and r[4] for r in report.rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
