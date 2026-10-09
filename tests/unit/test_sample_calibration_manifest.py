"""`sample_calibration.py` 的 manifest 选择。

起因（2026-10-09 实测）
----------------------
相机版仿真在跑（世界里的模型是 `x500_mono_cam_0/1/2`），但不带参数直接跑：

    python3 simulation/px4_gazebo/scripts/sample_calibration.py --publish-runtime ...

报：

    ValueError: gazebo_model_pose_missing

原因：`--config` 的默认值是 `DEFAULT_MANIFEST_PATH`，也就是**无相机**那份
`three_uav_sitl.json`（模型 `x500_0/1/2`）。于是它在世界里找不到 `x500_0` 的位姿。

这不是"用户忘了传参数"的问题：**没有任何参数时就应该能用**，
而"现在在跑的是哪一份配置"这件事**是已知的** —— 仿真启动时把它写进了
harness state 的 `manifest_path`。所以默认值应当**从那里读**。

判据
----
本文件断言的是行为，不是实现：
· 显式 `--config` 永远优先（不能被自动探测覆盖）
· 有 harness state 时，默认取它记的那一份
· 没有 state（仿真没跑）时退回 `DEFAULT_MANIFEST_PATH`
· state 损坏时也不能崩 —— 退回默认值，让下游报"仿真未就绪"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "simulation" / "px4_gazebo" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO / "simulation" / "px4_gazebo"))

import sample_calibration  # noqa: E402


CAMERA_MANIFEST = REPO / "simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json"
DEFAULT_MANIFEST = REPO / "simulation/px4_gazebo/config/three_uav_sitl.json"


def _write_state(root: Path, manifest_path: str) -> Path:
    """在 root 下写出一个 harness state，返回 state 文件路径。"""
    state = root / "harness_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"manifest_path": manifest_path, "run_id": "r1"}), encoding="utf-8")
    return state


# --- 核心行为 ---------------------------------------------------------------


def test_default_follows_the_running_manifest(tmp_path: Path) -> None:
    """有 state 时，默认应取 state 里记的那一份。

    这是本次修复的核心：不带参数也要能对上正在跑的仿真。
    """
    state = _write_state(tmp_path, str(CAMERA_MANIFEST))
    resolved = sample_calibration.resolve_manifest_path(None, state_path=state)
    assert resolved == CAMERA_MANIFEST


def test_default_falls_back_when_no_state(tmp_path: Path) -> None:
    """仿真没跑（没有 state）时退回默认 manifest。

    不能崩 —— 那不是"配置错误"，是"还没启动"。
    """
    missing = tmp_path / "harness_state.json"
    resolved = sample_calibration.resolve_manifest_path(None, state_path=missing)
    assert resolved == sample_calibration.DEFAULT_MANIFEST_PATH


def test_explicit_config_always_wins(tmp_path: Path) -> None:
    """显式传的 --config 优先于自动探测。

    否则"我想标定别的配置"这件正当需求就没法表达。
    """
    state = _write_state(tmp_path, str(CAMERA_MANIFEST))
    explicit = DEFAULT_MANIFEST
    resolved = sample_calibration.resolve_manifest_path(explicit, state_path=state)
    assert resolved == explicit


def test_state_without_manifest_path_falls_back(tmp_path: Path) -> None:
    """state 存在但没有 manifest_path 字段 → 退回默认，不报错。"""
    state = tmp_path / "harness_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"run_id": "r1"}), encoding="utf-8")
    resolved = sample_calibration.resolve_manifest_path(None, state_path=state)
    assert resolved == sample_calibration.DEFAULT_MANIFEST_PATH


def test_corrupt_state_does_not_crash(tmp_path: Path) -> None:
    """state 损坏时不能抛异常。

    理由：这个函数的目的只是"挑一份配置"。它失败的模式必须是
    "退回默认值，让下游的仿真就绪检查去报错" —— 而不是在这里抛一个
    与真正问题无关的 JSONDecodeError。
    """
    state = tmp_path / "harness_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{ 这不是 JSON", encoding="utf-8")
    resolved = sample_calibration.resolve_manifest_path(None, state_path=state)
    assert resolved == sample_calibration.DEFAULT_MANIFEST_PATH


def test_same_manifest_reported_by_state_is_used_even_if_it_is_the_default(
    tmp_path: Path,
) -> None:
    """state 记的就是默认那份时，也应当取它（结果相同，但路径来源一致）。"""
    state = _write_state(tmp_path, str(DEFAULT_MANIFEST))
    resolved = sample_calibration.resolve_manifest_path(None, state_path=state)
    assert resolved == DEFAULT_MANIFEST


# --- 与真实仓库的一致性 -----------------------------------------------------


def test_camera_and_default_manifests_actually_differ_in_model_names() -> None:
    """这条测试守住本修复的**前提**：两份 manifest 的模型名确实不同。

    若将来它们变成一样，那"标定找错模型"这个问题就不存在了 ——
    那时应当删掉这组测试，而不是留着一个没有意义的自动探测。
    """
    camera = json.loads(CAMERA_MANIFEST.read_text(encoding="utf-8"))
    default = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    camera_models = [v["gazebo_model_name"] for v in camera["vehicles"]]
    default_models = [v["gazebo_model_name"] for v in default["vehicles"]]
    assert camera_models != default_models
    assert all("mono_cam" in name for name in camera_models)
    assert not any("mono_cam" in name for name in default_models)
