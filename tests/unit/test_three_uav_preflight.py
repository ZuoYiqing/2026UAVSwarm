"""`harness preflight` 的测试。

为什么需要这个子命令
--------------------
两个流程错位都会产生**"看起来正常、实际不可用"**的状态 —— 这正是本项目一直在防的
那类失败。它们原先只在我方未受版本控制的 `_ops/ops.sh` 里检查，**别人拉不到**。
做成被跟踪的子命令后，仿真侧、Runtime 侧、任何人都能用同一份判据。

两个错位
--------
① **配置里没有相机。** `ops.sh start` 原先写死不带 `--config`，起的是默认 `x500`。
   那个状态**表面完全正常**：端口对、health ready、飞机能飞 —— **只有相机动作会失败**。

② **仿真跑在别的仓库，而 Runtime 只认本仓库。** `harness.py` 的 `REPO_ROOT` 是它
   自己所在目录的上两级，所以 harness state 与标定证据写在**跑仿真的那个仓库**的
   `.runtime/` 下。Runtime 读不到 → 标定 stale → 三维视图不显示、`goto` 被拒。

判据要能区分"事实"与"猜测"
--------------------------
本文件断言的是**可验证的结果形状**：哪个字段、什么严重级别、退出码是多少。
不依赖本机是否真的在跑仿真。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HARNESS_DIR = Path("simulation/px4_gazebo").resolve()
sys.path.insert(0, str(HARNESS_DIR))

import harness  # noqa: E402


CAMERA_MANIFEST = HARNESS_DIR / "config" / "three_uav_mono_cam_sitl.json"
DEFAULT_MANIFEST = HARNESS_DIR / "config" / "three_uav_sitl.json"


# --- 相机能力判定 -----------------------------------------------------------


def test_default_manifest_is_reported_as_having_no_camera() -> None:
    """默认 manifest 必须被判为"无相机"。

    这是本命令存在的首要理由：那个状态看起来完全正常，只有相机动作会失败。
    """
    manifest = harness.load_manifest(DEFAULT_MANIFEST)
    assert harness.manifest_has_camera(manifest) is False


def test_camera_manifest_is_reported_as_having_a_camera() -> None:
    manifest = harness.load_manifest(CAMERA_MANIFEST)
    assert harness.manifest_has_camera(manifest) is True


def test_camera_detection_reads_the_manifest_not_the_filename() -> None:
    """判据必须读 manifest 内容，而不是猜文件名。

    理由：文件名可以随便起。若按名字里有没有 "mono_cam" 判断，一个改名后的
    无相机 manifest 会被误判成有相机 —— 而误判的方向恰好是"以为有相机"，
    也就是把问题藏起来。
    """
    manifest = harness.load_manifest(DEFAULT_MANIFEST)
    # 把默认 manifest 复制一份，模型名换成相机版 —— 内容变了，名字没变
    patched = json.loads(json.dumps(manifest))
    for vehicle in patched["vehicles"]:
        vehicle["gazebo_model_name"] = "x500_mono_cam_0"
    assert harness.manifest_has_camera(patched) is True, "应据内容判定"

    # 反向：相机 manifest 的模型名换回 x500，应判为无相机
    camera = json.loads(json.dumps(harness.load_manifest(CAMERA_MANIFEST)))
    for vehicle in camera["vehicles"]:
        vehicle["gazebo_model_name"] = "x500_0"
    assert harness.manifest_has_camera(camera) is False


# --- preflight 报告 ---------------------------------------------------------


def _codes(report: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in report["findings"]}


def test_preflight_reports_no_camera_as_a_warning_not_an_error() -> None:
    """无相机是**警告**不是错误：无相机仿真本身是合法用途。

    若报成错误，`ops.sh start` 就会被拒，那会破坏现有的无相机工作流。
    但它必须被**说出来** —— 那才是重点。
    """
    report = harness.preflight_manifest(
        harness.load_manifest(DEFAULT_MANIFEST), repo_root=HARNESS_DIR.parent.parent
    )
    findings = {f["code"]: f for f in report["findings"]}
    assert "manifest_has_no_camera" in findings
    assert findings["manifest_has_no_camera"]["severity"] == "warning"
    assert report["ok"] is True, "无相机不该让 preflight 失败"


def test_preflight_accepts_camera_manifest() -> None:
    report = harness.preflight_manifest(
        harness.load_manifest(CAMERA_MANIFEST), repo_root=HARNESS_DIR.parent.parent
    )
    assert "manifest_has_no_camera" not in _codes(report)
    assert report["ok"] is True


def test_preflight_reports_camera_manifest_positive_fact() -> None:
    """有相机时要给出**肯定**的结论，而不是"没报错"。

    操作者需要看到"这次跑的确实是相机版"，而不是靠"没有警告"去推断 ——
    后者在警告被静音或漏看时会误导。
    """
    report = harness.preflight_manifest(
        harness.load_manifest(CAMERA_MANIFEST), repo_root=HARNESS_DIR.parent.parent
    )
    assert report["camera"]["present"] is True
    assert report["camera"]["models"], "应列出相机模型的名称"


def test_preflight_reports_which_manifest_it_checked() -> None:
    """必须回报检查的是哪一份 —— 否则"检查通过了"没有意义。"""
    report = harness.preflight_manifest(
        harness.load_manifest(CAMERA_MANIFEST),
        repo_root=HARNESS_DIR.parent.parent,
        manifest_path=CAMERA_MANIFEST,
    )
    assert report["manifest"]["path"].endswith("three_uav_mono_cam_sitl.json")
    assert str(report["manifest"]["path"]).endswith(
        CAMERA_MANIFEST.name
    ), "必须能看出查的是哪一份"


def test_preflight_flags_state_in_another_worktree(tmp_path: Path) -> None:
    """仿真跑在别的仓库时，必须报出来。

    这是第二个错位：Runtime 只认本仓库的 `.runtime/`，而仿真把状态写在了别处。
    """
    fake_repo = tmp_path / "main"
    fake_repo.mkdir()
    worktrees = tmp_path / "worktrees"
    other = worktrees / "some-worktree" / ".runtime" / "px4_gazebo"
    other.mkdir(parents=True)
    (other / "harness_state.json").write_text("{}", encoding="utf-8")

    report = harness.preflight_manifest(
        harness.load_manifest(CAMERA_MANIFEST),
        repo_root=fake_repo,
        worktrees_root=worktrees,
    )
    findings = {f["code"]: f for f in report["findings"]}
    assert "state_in_other_worktree" in findings
    assert findings["state_in_other_worktree"]["severity"] == "error"
    assert report["ok"] is False, "这个错位会让标定读到过期证据，必须失败"
    assert "some-worktree" in str(findings["state_in_other_worktree"]["detail"])


def test_preflight_does_not_flag_when_state_is_local(tmp_path: Path) -> None:
    """本仓库有状态、别处没有 → 不该报错。"""
    fake_repo = tmp_path / "main"
    (fake_repo / ".runtime" / "px4_gazebo").mkdir(parents=True)
    (fake_repo / ".runtime" / "px4_gazebo" / "harness_state.json").write_text(
        "{}", encoding="utf-8"
    )
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()

    report = harness.preflight_manifest(
        harness.load_manifest(CAMERA_MANIFEST),
        repo_root=fake_repo,
        worktrees_root=worktrees,
    )
    assert "state_in_other_worktree" not in _codes(report)
    assert report["ok"] is True


def test_preflight_still_reports_other_worktree_when_local_state_exists(
    tmp_path: Path,
) -> None:
    """本仓库与别的仓库**都有**状态时，也要报出来。

    这种情况更危险：本仓库那份可能是**旧的**，而 Runtime 会读它。
    """
    fake_repo = tmp_path / "main"
    (fake_repo / ".runtime" / "px4_gazebo").mkdir(parents=True)
    (fake_repo / ".runtime" / "px4_gazebo" / "harness_state.json").write_text(
        "{}", encoding="utf-8"
    )
    worktrees = tmp_path / "worktrees"
    other = worktrees / "wt-a" / ".runtime" / "px4_gazebo"
    other.mkdir(parents=True)
    (other / "harness_state.json").write_text("{}", encoding="utf-8")

    report = harness.preflight_manifest(
        harness.load_manifest(CAMERA_MANIFEST),
        repo_root=fake_repo,
        worktrees_root=worktrees,
    )
    findings = {f["code"]: f for f in report["findings"]}
    assert "state_in_other_worktree" in findings
    assert findings["state_in_other_worktree"]["severity"] == "error"


def test_preflight_is_json_serializable() -> None:
    """报告必须是可直接 json.dumps 的 —— 它要被 ops.sh 与其它脚本消费。"""
    report = harness.preflight_manifest(
        harness.load_manifest(CAMERA_MANIFEST), repo_root=HARNESS_DIR.parent.parent
    )
    text = json.dumps(report, ensure_ascii=False)
    assert "findings" in text
    assert json.loads(text)["ok"] in (True, False)


# --- 与 CLI 的接线 ----------------------------------------------------------


def test_preflight_subcommand_exists_and_exits_nonzero_on_error(tmp_path: Path) -> None:
    """CLI 必须存在，且**在错位时报非零退出码**。

    退出码是 `ops.sh` 唯一能可靠消费的信号 —— 若错位时仍返回 0，
    它就只能靠解析文字判断，那迟早会失效。
    """
    fake_repo = tmp_path / "main"
    fake_repo.mkdir()
    worktrees = tmp_path / "worktrees"
    other = worktrees / "wt" / ".runtime" / "px4_gazebo"
    other.mkdir(parents=True)
    (other / "harness_state.json").write_text("{}", encoding="utf-8")

    exit_code = harness.main(
        [
            "preflight",
            "--config",
            str(CAMERA_MANIFEST),
            "--repo-root",
            str(fake_repo),
            "--worktrees-root",
            str(worktrees),
        ]
    )
    assert exit_code != 0


def test_preflight_subcommand_exits_zero_when_clean(tmp_path: Path) -> None:
    fake_repo = tmp_path / "main"
    (fake_repo / ".runtime" / "px4_gazebo").mkdir(parents=True)
    (fake_repo / ".runtime" / "px4_gazebo" / "harness_state.json").write_text(
        "{}", encoding="utf-8"
    )
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()

    exit_code = harness.main(
        [
            "preflight",
            "--config",
            str(CAMERA_MANIFEST),
            "--repo-root",
            str(fake_repo),
            "--worktrees-root",
            str(worktrees),
        ]
    )
    assert exit_code == 0
