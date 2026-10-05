"""超时分类的判据测试。

要解决的问题（实测，不是设想）
------------------------------
原先所有"等不到完成条件"的超时都报同一个原因码，而它把三种**完全不同**的
情况混成了一种：

  · 350 m 航线没飞完 → `arrival_timeout`，但飞机在正常飞行、越来越近
  · RTL 后降落超时   → `landing_completion_timeout`，而飞机**已经落地**
  · 坠机后降落超时   → `landing_completion_timeout`，飞机坠了、永远等不到条件

调用方只看 `result: fail` 会得出错误结论：第一种该"再等等"，后两种该"出事了"。

判据为什么不是"数值还在不在变"
------------------------------
最初设想用"高度还在变 / 位置不再变"来区分，**实测证明不可靠**：
"不再变化"无法区分"载具卡住"、"稳稳悬停等条件"、"遥测采样停了"三种情况。
因此改用**观测循环本来就在记录的分量**：

  partial_evidence      —— 至少一个完成条件**可判定**（该分量有新鲜样本）
  insufficient_evidence —— 完成条件**都没有可判定依据**

本文件锁定这些判据。**分类不改变 result**：超时仍报 fail，只是失败更可读。
"""
from __future__ import annotations

import pytest

from uav_runtime.adapters.mavlink_backend_session import classify_incomplete_evidence


# --- 不该被分类的情况 -------------------------------------------------------


def test_completed_evidence_is_not_classified() -> None:
    """已完成的证据不该被归类 —— 调用方只在失败路径上用分类。"""
    assert classify_incomplete_evidence("goto", {"observed": True, "completion_reached": True}) is None
    assert classify_incomplete_evidence("land", {"completion_reached": True}) is None
    assert classify_incomplete_evidence("hold_position", {"held": True}) is None
    assert classify_incomplete_evidence("return_home", {"returning": True}) is None


def test_observed_alone_is_not_treated_as_completion() -> None:
    """`observed` 只是"有没有拿到样本"，**不是**"有没有完成"。

    这条是回归：最初把 `observed` 当完成标志，于是所有"拿到样本但没满足条件"
    的失败都被跳过分类 —— 分类函数在最需要它的场景下静默失效。
    """
    evidence = {
        "observed": True,          # 有样本
        "completion_reached": False,  # 但没完成
        "samples": 200,
        "last_error_m": 50.0,
        "min_error_m": 40.0,
        "target_error_m": 2.0,
    }
    assert classify_incomplete_evidence("goto", evidence) == "partial_evidence"


def test_unknown_action_is_not_classified() -> None:
    """不认识的动作返回 None，而不是硬编一个分类。"""
    assert classify_incomplete_evidence("teleport", {"samples": 5}) is None


def test_non_dict_evidence_is_not_classified() -> None:
    for bad in (None, [], "x", 3):
        assert classify_incomplete_evidence("goto", bad) is None  # type: ignore[arg-type]


# --- 降落：实测中混淆最严重的一处 -------------------------------------------


def test_land_grounded_but_armed_is_partial() -> None:
    """落地了但没 disarm → partial。

    这正是我实际遇到的那次：飞机已经在地面（landed_state=on_ground），
    但该次失败报的是笼统的 landing_completion_timeout，
    调用方无法从原因码看出"它其实已经落地了"。
    """
    evidence = {
        "telemetry_state": "fresh",
        "landed_state": 1,
        "landed_state_name": "on_ground",
        "armed": True,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("land", evidence) == "partial_evidence"


def test_land_disarmed_but_not_reported_on_ground_is_partial() -> None:
    """另一半成立也算 partial：已 disarm 但飞控没报 on_ground。"""
    evidence = {
        "telemetry_state": "fresh",
        "landed_state": 4,
        "landed_state_name": "not_on_ground",
        "armed": False,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("land", evidence) == "partial_evidence"


def test_land_crash_state_gets_its_own_stronger_classification() -> None:
    """坠机卡死：飞控明确报 not_on_ground 且仍 armed。

    这一条是本次最重要的回归，而且**改过一次**：

    第一版把它归为 `partial_evidence`，与"落地了但没 disarm"同码 —— 于是两者
    拿到同一句"**这不代表降落失败**，请据遥测确认"。对一次坠机说这句话是误导。

    现在它有自己的分类 `not_on_ground_after_land`：说明"再等下去也不会完成，
    建议人工确认"。判据也收紧了 —— 读数的**存在**不等于条件的**成立**；
    第一版用 `landed_state is not None` 就算"看到一个条件成立"，那太宽。
    """
    evidence = {
        "telemetry_state": "incomplete",
        "landed_state": 4,
        "landed_state_name": "not_on_ground",
        "armed": True,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("land", evidence) == "not_on_ground_after_land"


def test_land_crash_classification_is_not_the_reassuring_one() -> None:
    """坠机与"落地未 disarm"必须分属不同分类。

    这是本文件的**核心断言**：两者原先同码同文案，而它们对操作者的含义相反 ——
    一个说"可能已经落地了，去看遥测"，另一个说"它没在地面，建议人工介入"。
    """
    grounded_but_armed = {
        "telemetry_state": "incomplete",
        "landed_state": 1,
        "landed_state_name": "on_ground",
        "armed": True,
        "completion_reached": False,
    }
    crashed = {
        "telemetry_state": "incomplete",
        "landed_state": 4,
        "landed_state_name": "not_on_ground",
        "armed": True,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("land", grounded_but_armed) == "partial_evidence"
    assert classify_incomplete_evidence("land", crashed) == "not_on_ground_after_land"
    assert classify_incomplete_evidence("land", grounded_but_armed) != classify_incomplete_evidence(
        "land", crashed
    )


def test_land_without_any_telemetry_is_insufficient() -> None:
    """完全没有遥测 → insufficient：连"卡在哪"都无从判断。"""
    evidence = {
        "telemetry_state": "unknown",
        "landed_state": None,
        "armed": None,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("land", evidence) == "insufficient_evidence"


def test_land_with_stale_telemetry_but_a_real_reading_is_still_partial() -> None:
    """样本陈旧、但读数本身有效 → 仍算 partial。

    修正说明：我最初把 `stale` 一律当成"没有依据"，写了一条"stale 必须报
    insufficient"的断言。**那条断言是错的**：`landed_state=on_ground` 即使来自
    陈旧样本，也真实说明了"**某个时刻**载具曾在地面"—— 那是有效信息，
    不该被"陈旧"两个字抹掉。

    `stale` 真正该影响的，是**没有任何有效读数**的情况（见下一条）。
    """
    evidence = {
        "telemetry_state": "stale",
        "landed_state": 1,
        "armed": True,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("land", evidence) == "partial_evidence"


def test_land_with_stale_telemetry_and_no_reading_is_insufficient() -> None:
    """陈旧且没有有效读数 → insufficient：无从判断卡在哪。"""
    evidence = {
        "telemetry_state": "stale",
        "landed_state": None,
        "armed": None,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("land", evidence) == "insufficient_evidence"


# --- 起飞 -------------------------------------------------------------------


def test_takeoff_with_altitude_in_tolerance_is_partial() -> None:
    """高度已进容差、只差"稳定保持"的时长 → partial。"""
    evidence = {
        "observed": True,
        "sample_count": 40,
        "target_altitude_m": 20.0,
        "tolerance_m": 0.3,
        "last_altitude_m": 19.95,
        "max_altitude_m": 20.1,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("takeoff", evidence) == "partial_evidence"


def test_takeoff_climbing_toward_target_is_partial() -> None:
    """爬升中、还没到目标高度 → partial（高度读数可判定）。"""
    evidence = {
        "observed": True,
        "sample_count": 12,
        "target_altitude_m": 20.0,
        "tolerance_m": 0.3,
        "last_altitude_m": 6.0,
        "max_altitude_m": 6.2,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("takeoff", evidence) == "partial_evidence"


def test_takeoff_without_any_altitude_sample_is_insufficient() -> None:
    """一个高度样本都没有 → insufficient。"""
    evidence = {
        "observed": False,
        "sample_count": 0,
        "target_altitude_m": 20.0,
        "tolerance_m": 0.3,
        "last_altitude_m": None,
        "max_altitude_m": None,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("takeoff", evidence) == "insufficient_evidence"


# --- goto -------------------------------------------------------------------


def test_goto_that_got_close_is_partial() -> None:
    """接近过目标（最近距离在两倍容差内）→ partial：可能只是时间不够。"""
    evidence = {
        "observed": False,
        "samples": 283,
        "last_error_m": 26.0,
        "min_error_m": 1.6,
        "target_error_m": 1.0,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("goto", evidence) == "partial_evidence"


def test_goto_that_never_approached_is_partial_when_samples_exist() -> None:
    """有位置样本但从未接近 → 仍算 partial。

    这里刻意**不**断言成"blocked/不可能完成"：有位置样本只说明"这一项可判定"，
    并不足以断定它永远到不了（可能只是飞得慢，或起点远）。
    声称"不可能完成"需要比"距离还很大"更强的证据。
    """
    evidence = {
        "observed": False,
        "samples": 200,
        "last_error_m": 117.6,
        "min_error_m": 98.0,
        "target_error_m": 2.0,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("goto", evidence) == "partial_evidence"


def test_goto_without_any_position_sample_is_insufficient() -> None:
    """一个位置样本都没有 → insufficient。"""
    evidence = {
        "observed": False,
        "samples": 0,
        "last_error_m": None,
        "min_error_m": None,
        "target_error_m": 2.0,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("goto", evidence) == "insufficient_evidence"


# --- hold_position / return_home -------------------------------------------


def test_hold_within_tolerance_is_partial() -> None:
    """漂移在容差内、只差持续时间 → partial。"""
    evidence = {
        "held": False,
        "samples": 41,
        "max_drift_m": 0.03,
        "tolerance_m": 2.0,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("hold_position", evidence) == "partial_evidence"


def test_hold_accepts_alias() -> None:
    """注册表拼写与算法拼写都要能分类。"""
    evidence = {"samples": 10, "max_drift_m": 5.0, "tolerance_m": 2.0}
    assert classify_incomplete_evidence("hold", evidence) == "partial_evidence"


def test_hold_without_drift_sample_is_insufficient() -> None:
    evidence = {"held": False, "samples": 0, "max_drift_m": None, "tolerance_m": 2.0}
    assert classify_incomplete_evidence("hold_position", evidence) == "insufficient_evidence"


def test_return_home_with_distance_readings_is_partial() -> None:
    """距离有读数 → partial（可判定它没收敛够）。

    字段名用契约里对外暴露的 final_distance_m / initial_distance_m，
    不另造名字 —— 同一份证据有两个名字，迟早会有一处读错。
    """
    evidence = {
        "returning": False,
        "samples": 30,
        "initial_distance_m": 60.7,
        "final_distance_m": 58.0,
        "distance_reduction_m": 2.7,
        "min_progress_m": 5.0,
        "completion_reached": False,
    }
    assert classify_incomplete_evidence("return_home", evidence) == "partial_evidence"


def test_return_home_mode_not_confirmed_is_insufficient() -> None:
    """连 RTL 模式都没进 → 没有任何距离证据 → insufficient。

    注意这条走的是 `return_home_mode_not_confirmed` 那条提前返回，
    它不带 telemetry_state —— 分类必须能处理这种字段不全的证据。
    """
    evidence = {
        "returning": False,
        "reason": "mode_not_confirmed",
        "initial_distance_m": None,
        "final_distance_m": None,
        "distance_reduction_m": None,
        "samples": 0,
        "failure_reason": "return_home_mode_not_confirmed",
    }
    assert classify_incomplete_evidence("return_home", evidence) == "insufficient_evidence"


def test_return_home_without_distance_readings_is_insufficient() -> None:
    evidence = {
        "returning": False,
        "samples": 0,
        "initial_distance_m": None,
        "final_distance_m": None,
        "min_progress_m": 5.0,
    }
    assert classify_incomplete_evidence("return_home", evidence) == "insufficient_evidence"


# --- 分类绝不改变事实 -------------------------------------------------------


@pytest.mark.parametrize("action", ["land", "takeoff", "goto", "hold_position", "return_home"])
@pytest.mark.parametrize(
    "evidence",
    [
        {},
        {"telemetry_state": "unknown"},
        {"samples": 0, "sample_count": 0},
        {"observed": False, "completion_reached": False},
    ],
)
def test_classifier_never_claims_completion(action: str, evidence: dict) -> None:
    """无论证据多残缺，分类都不能返回任何"完成"含义的值。

    这是本函数的安全边界：它只在失败路径上被调用，返回的必然是"未完成"的
    某个分类、或 None。**绝不能出现 pass/succeeded 之类的值** ——
    否则一个判据辅助函数会变成绕过完成检查的后门。
    """
    result = classify_incomplete_evidence(action, evidence)
    allowed = (
        None,
        "partial_evidence",
        "insufficient_evidence",
        "not_on_ground_after_land",
    )
    assert result in allowed, result
    assert result not in ("succeeded", "pass", "completed", "observed")
