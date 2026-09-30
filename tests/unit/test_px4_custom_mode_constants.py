"""校验硬编码的 PX4 主模式常量与 PX4 源码一致。

为什么需要这个测试
------------------
MAVLink 的公共枚举里没有 PX4 的主模式号，所以 Runtime 必须自己带这些常量
（见 mavlink_backend_session.py 里的 PX4_CUSTOM_MAIN_MODE_*）。

这些值在 PX4 源码里是**自动递增的枚举**，不是固定的 1/2/3/6/7 —— 例如 ACRO=5
就夹在 AUTO=4 和 OFFBOARD=6 之间。一旦 PX4 升级时在枚举中间插入新值，
我们硬编码的数字就会**静默错位**：切模式会切到错误的模式，而代码不会报错。

这个测试直接从 PX4 头文件解析枚举真实值并与常量比对，让错位立刻可见。

找不到 PX4 源码时跳过（不是失败）—— CI 或未安装 PX4 的机器上不该因此变红。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from uav_runtime.adapters import mavlink_backend_session as session

# 与 simulation/px4_gazebo/config/three_uav_sitl.json 的 px4_autopilot_dir 一致
_HEADER_RELATIVE = "src/modules/commander/px4_custom_mode.h"


def _px4_header_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_dir = os.environ.get("PX4_AUTOPILOT_DIR")
    if env_dir:
        candidates.append(Path(os.path.expanduser(env_dir)) / _HEADER_RELATIVE)
    # 原生路径：Linux/WSL 下就是 $HOME/PX4-Autopilot；Windows 下通常不存在
    candidates.append(Path.home() / "PX4-Autopilot" / _HEADER_RELATIVE)
    for drive in ("C:", "D:", "E:"):
        candidates.append(Path(f"{drive}/PX4-Autopilot") / _HEADER_RELATIVE)

    # 在 Windows 上跑测试、PX4 装在 WSL 里 —— 这是本项目的常见组合
    # （测试在 Windows 侧执行，仿真在 WSL 里）。
    #
    # 两个坑：
    #   1) \\wsl$ / \\wsl.localhost 的“目录枚举”不可靠（某些环境 iterdir 直接
    #      报 WinError 53），所以直接拼已知发行版名，不做枚举。
    #   2) **必须把 "//wsl.localhost/Ubuntu" 当成一个字符串传给 Path**。
    #      写成 Path("//wsl.localhost") / "Ubuntu" 会被规范化成单个前导反斜杠
    #      \\wsl.localhost\\Ubuntu\\... ，UNC 前缀失效、is_file() 恒为 False。
    for prefix in ("//wsl.localhost", "//wsl$"):
        for distro in ("Ubuntu", "Ubuntu-22.04", "Ubuntu-24.04"):
            root = f"{prefix}/{distro}/home/zyq/PX4-Autopilot"
            candidates.append(Path(root) / _HEADER_RELATIVE)
    return candidates


def _find_header() -> Path | None:
    for candidate in _px4_header_candidates():
        if candidate.is_file():
            return candidate
    return None


def parse_main_mode_enum(source: str) -> dict[str, int]:
    """从 px4_custom_mode.h 源码解析 PX4_CUSTOM_MAIN_MODE_* 的真实数值。

    遵守 C 枚举的自动递增规则：没有显式 ``= N`` 的成员取前一个值 +1。
    """
    # 去掉注释，避免注释里的标识符或数字干扰
    text = re.sub(r"//[^\n]*", "", source)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # 截取主模式枚举块
    match = re.search(
        r"enum\s+PX4_CUSTOM_MAIN_MODE\s*\{(?P<body>.*?)\}",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        # 有些版本不写枚举名，退化为按成员名匹配
        start = text.find("PX4_CUSTOM_MAIN_MODE_MANUAL")
        if start < 0:
            raise AssertionError("px4_custom_mode.h 中找不到主模式枚举")
        body = text[start : text.find("}", start)]
    else:
        body = match.group("body")

    values: dict[str, int] = {}
    current = -1
    for raw_item in body.split(","):
        item = raw_item.strip()
        if not item:
            continue
        name_match = re.match(r"(PX4_CUSTOM_MAIN_MODE_[A-Z_]+)\s*(?:=\s*(-?\d+))?$", item)
        if not name_match:
            continue
        name, explicit = name_match.group(1), name_match.group(2)
        current = int(explicit) if explicit is not None else current + 1
        values[name] = current
    return values


def test_hardcoded_px4_main_mode_constants_match_px4_source() -> None:
    header = _find_header()
    if header is None:
        pytest.skip("未找到 PX4 源码（可在 PX4_AUTOPILOT_DIR 指定），跳过常量一致性校验")

    parsed = parse_main_mode_enum(header.read_text(encoding="utf-8", errors="replace"))
    assert parsed, f"未能从 {header} 解析出任何主模式常量"

    mismatches: list[str] = []
    for name, expected in sorted(parsed.items()):
        actual = getattr(session, name, None)
        if actual is None:
            # 我们没定义的模式（例如新增的）不算错，只在定义了但不一致时报错
            continue
        if actual != expected:
            mismatches.append(f"{name}: 硬编码={actual} 源码={expected}")

    assert not mismatches, (
        "PX4 主模式常量与源码不一致（切模式会切错）：\n  "
        + "\n  ".join(mismatches)
        + f"\n  头文件: {header}"
    )


def test_offboard_and_posctl_are_distinct_and_present() -> None:
    """goto 依赖 OFFBOARD，恢复路径依赖 POSCTL；两者必须存在且不同。"""
    assert session.PX4_CUSTOM_MAIN_MODE_OFFBOARD == 6
    assert session.PX4_CUSTOM_MAIN_MODE_POSCTL == 3
    assert session.PX4_CUSTOM_MAIN_MODE_OFFBOARD != session.PX4_CUSTOM_MAIN_MODE_POSCTL
    assert session.PX4_MAIN_MODE_NAMES[session.PX4_CUSTOM_MAIN_MODE_OFFBOARD] == "OFFBOARD"


def test_main_mode_extraction_matches_px4_packing() -> None:
    """custom_mode 的位布局：main_mode 在 bit 16-23，sub_mode 在 bit 24-31。"""
    pack = lambda main, sub: ((sub & 0xFF) << 24) | ((main & 0xFF) << 16)  # noqa: E731

    assert session.MavlinkBackendSession.px4_main_mode_from_custom_mode(pack(6, 0)) == 6
    assert session.MavlinkBackendSession.px4_main_mode_from_custom_mode(pack(3, 0)) == 3
    # AUTO + MISSION(4)：子模式不能污染主模式
    assert session.MavlinkBackendSession.px4_main_mode_from_custom_mode(pack(4, 4)) == 4
    # 保留位（bit 0-15）同样不能污染
    assert session.MavlinkBackendSession.px4_main_mode_from_custom_mode(pack(6, 0) | 0xFFFF) == 6
    assert session.MavlinkBackendSession.px4_main_mode_from_custom_mode(None) is None
