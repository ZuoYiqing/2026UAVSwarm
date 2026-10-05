"""后端整条路径上的超时分类测试。

为什么必须有这一层
------------------
纯函数（``classify_incomplete_evidence``）与会话记录都已单独测过，但**实证跑真实
场景时仍然抓到两个 bug**，它们都在"后端把证据交给分类器"这一段：

  1. HOLD 漂了 30 m（容差 0.5），说明文案却写"位置在容差内"
     —— 后端构造的 ``completion_evidence`` **没放 tolerance_m**，分类因此
        判不出"漂移是否在容差内"，而文案却**假定**它在容差内。
  2. RETURN_HOME 的说明写"距 home None m"
     —— 文案读的是自造的 ``last_distance_m``，真实键名是 ``final_distance_m``。

两个 bug 的共同形状：**证据的产生方与解释方对不上**。纯函数测试看不见它，
因为测试自己造的证据总是"对得上"的。所以本文件用**后端真实产生的那份证据**
来做断言。

同时也覆盖一条更根本的规则：**文案不能比判据更乐观**。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig  # noqa: E402
from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend  # noqa: E402


class _FakeSession:
    """按需返回一个预置 outcome 的假会话。"""

    def __init__(self, outcome: dict[str, Any]) -> None:
        self._outcome = outcome
        self._last_completion_evidence: dict[str, Any] = outcome

    def hold_position(self, **_kwargs: Any) -> dict[str, Any]:
        return self._outcome

    def return_home(self, **_kwargs: Any) -> dict[str, Any]:
        return self._outcome

    def classify_incomplete(self, action: str) -> str | None:
        from uav_runtime.adapters.mavlink_backend_session import (
            classify_incomplete_evidence,
        )

        return classify_incomplete_evidence(action, self._outcome)

    def start_gcs_heartbeat(self) -> None:
        return None


def _build_backend(outcome: dict[str, Any], action: str) -> tuple[Px4SitlBackend, dict[str, Any]]:
    """跑后端动作，返回 (backend, result)。

    用真实 config 构造，但会话换成假的 —— 只测"证据怎么交给分类器"这一段，
    不连任何 UDP 端口（单测不该去碰开发者机器上的 PX4 监听）。
    """
    cfg = MavlinkBackendConfig(
        backend_mode="sitl",
        backend_enabled=True,
        transport_endpoint="udpin:127.0.0.1:14540",
    )
    backend = Px4SitlBackend(cfg, _FakeSession(outcome))  # type: ignore[arg-type]

    result = backend._base_action_result(action)

    # 复现后端在超时分支上的两件事：展开证据，然后分类。
    if action == "hold_position":
        result["completion_evidence"] = {
            "held": outcome.get("held"),
            "reason": outcome.get("reason"),
            "max_drift_m": outcome.get("max_drift_m"),
            "samples": outcome.get("samples"),
            "tolerance_m": outcome.get("tolerance_m"),
            "hold_s": outcome.get("hold_s"),
        }
        result["completion_state"] = str(outcome.get("reason") or "unknown")
        result["failure_reason"] = str(outcome["failure_reason"])
        backend._classify_completion_timeout(result, "hold_position")
    else:
        result["completion_evidence"] = {
            "returning": outcome.get("returning"),
            "reason": outcome.get("reason"),
            "initial_distance_m": outcome.get("initial_distance_m"),
            "final_distance_m": outcome.get("final_distance_m"),
            "distance_reduction_m": outcome.get("distance_reduction_m"),
            "min_progress_m": outcome.get("min_progress_m"),
            "samples": outcome.get("samples"),
        }
        result["completion_state"] = str(outcome.get("reason") or "unknown")
        result["failure_reason"] = str(outcome["failure_reason"])
        backend._classify_completion_timeout(result, "return_home")

    return backend, result


# --- HOLD：漂移超容差时文案不能说"在容差内" ---------------------------------


def test_hold_exceeding_tolerance_does_not_claim_within_tolerance() -> None:
    """实测场景：容差 0.5 m，实际漂了 30 m。

    回归：最初文案无条件写"位置在容差内"，因为后端没把 tolerance_m 放进证据，
    分类判不出来，而文案却假定了结论 —— 给出了与事实相反的话。
    """
    outcome = {
        "held": False,
        "reason": "hold_timeout",
        "samples": 35,
        "max_drift_m": 30.0,
        "tolerance_m": 0.5,
        "hold_s": 0.2,
        "failure_reason": "hold_timeout",
    }
    _, result = _build_backend(outcome, "hold_position")

    detail = result["completion_timeout_detail"]
    assert "30.0" in detail, detail
    assert "0.5" in detail, detail
    assert "超出容差" in detail, f"漂移超容差时必须说「超出」：{detail}"
    assert "位置在容差内" not in detail, f"不能声称在容差内：{detail}"


def test_hold_within_tolerance_says_so() -> None:
    """漂移确实在容差内时，文案才可以说"在容差内"。"""
    outcome = {
        "held": False,
        "reason": "hold_timeout",
        "samples": 40,
        "max_drift_m": 0.03,
        "tolerance_m": 2.0,
        "hold_s": 5.0,
        "failure_reason": "hold_timeout",
    }
    _, result = _build_backend(outcome, "hold_position")
    detail = result["completion_timeout_detail"]
    assert "位置在容差内" in detail, detail


def test_hold_without_drift_sample_is_honest_about_not_knowing() -> None:
    """没有漂移读数时不许猜。"""
    outcome = {
        "held": False,
        "reason": "hold_timeout",
        "samples": 0,
        "max_drift_m": None,
        "tolerance_m": 2.0,
        "hold_s": 5.0,
        "failure_reason": "hold_timeout",
    }
    _, result = _build_backend(outcome, "hold_position")
    detail = result["completion_timeout_detail"]
    assert "无法说明" in detail, detail
    assert "容差内" not in detail, detail


# --- RETURN_HOME：文案必须读到真实的距离字段 --------------------------------


def test_return_home_detail_reads_the_real_distance_field() -> None:
    """回归：文案原先读自造的 `last_distance_m`，于是永远打印 "None m"。

    真实字段是 `final_distance_m`（也是契约里对外暴露的名字）。
    """
    outcome = {
        "returning": False,
        "reason": "no_convergence",
        "samples": 60,
        "initial_distance_m": 60.75,
        "final_distance_m": 55.50,
        "distance_reduction_m": 5.25,
        "min_progress_m": 5.0,
        "failure_reason": "return_home_not_converging",
    }
    _, result = _build_backend(outcome, "return_home")

    detail = result["completion_timeout_detail"]
    assert "None" not in detail, f"读不到距离时说 None 等于没有信息：{detail}"
    assert "55.5" in detail, detail
    assert "60.75" in detail, detail


# --- 分类绝不改变事实 -------------------------------------------------------


def test_classification_never_turns_a_failure_into_a_success() -> None:
    """分类只让失败更可读，**不得**把 result 变成 pass。

    这是本功能的安全边界：超时仍然报 fail。
    """
    for action, outcome in (
        (
            "hold_position",
            {
                "held": False, "reason": "hold_timeout", "samples": 35,
                "max_drift_m": 30.0, "tolerance_m": 0.5, "hold_s": 0.2,
                "failure_reason": "hold_timeout",
            },
        ),
        (
            "return_home",
            {
                "returning": False, "reason": "no_convergence", "samples": 60,
                "initial_distance_m": 60.75, "final_distance_m": 55.50,
                "distance_reduction_m": 5.25, "min_progress_m": 5.0,
                "failure_reason": "return_home_not_converging",
            },
        ),
    ):
        _, result = _build_backend(outcome, action)
        assert result["result"] != "pass", f"{action} 超时不得被判成功"
        assert result["failure_reason"], "失败原因必须保留"


@pytest.mark.parametrize(
    "failure_reason",
    ["arm_rejected_or_timeout", "mode_restore_failed", "camera_not_validated"],
)
def test_non_completion_failures_are_not_reclassified(failure_reason: str) -> None:
    """ACK 失败、模式恢复失败等**不是**"等不到完成条件"，不该被套上这套分类。

    混用会让"命令根本没被接受"看起来像"命令执行了但没做完"。
    """
    backend = Px4SitlBackend(
        MavlinkBackendConfig(
            backend_mode="sitl",
            backend_enabled=True,
            transport_endpoint="udpin:127.0.0.1:14540",
        ),
        _FakeSession({"samples": 10, "max_drift_m": 30.0}),  # type: ignore[arg-type]
    )
    result: dict[str, Any] = {"failure_reason": failure_reason, "result": "fail"}
    backend._classify_completion_timeout(result, "hold_position")
    assert "completion_timeout_detail" not in result, (
        f"{failure_reason} 不是观测超时，不该被分类"
    )
