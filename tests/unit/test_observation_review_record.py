"""观察复核（L2）记录的校验测试。

本文件锁定的不是"字段齐不齐"，而是**三条防伪造的规则** —— 它们是这套东西存在的理由：

  1. **不得编造数值置信度。** 给一个 0–1 的数字会被下游当成模型输出概率，
     而它实际是某个人的主观印象 —— 那是把判断伪装成测量。
  2. **`reviewer` 必须是 `human:`。** 本阶段只接受人工复核；仿真真值只能用于
     离线标注与评价，不得冒充检测结果。
  3. **`not_observed` 必须给出依据。** 它只表示"在这份图像中未按判据看到"，
     不证明目标不存在。没有依据的 not_observed 与"检测器没报"无法区分。

另外锁定一条结构性约束：**记录里根本没有"任务已完成"这个取值** ——
三方共识要求 CAPTURE 成功不能自动完成 OBSERVE 或原任务，靠的不是"记得别那么做"，
而是让它无从表达。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from uav_runtime.observation.review_record import (
    CONFIDENCE_MUST_BE_NULL,
    LINKED_TASK_COMPLETION_NOT_ASSERTED,
    REVIEW_VERSION,
    ReviewValidationError,
    build_review,
    read_review,
    record_sha256,
    validate_review,
    write_review,
)

#: 一份各字段合法的记录，供各用例改一处来触发特定违规。
VALID = {
    "review_version": REVIEW_VERSION,
    "review_id": "rev-0123456789abcdef",
    "created_at": "2026-10-05T12:00:00Z",
    "task_id": "TASK-1",
    "target_id": "target-001",
    "capture_id": "cap-0123456789abcdef",
    "image": {
        "ref": "sha256:" + "a" * 64,
        "sha256": "a" * 64,
        "width": 1280,
        "height": 960,
        "encoding": "RGB8",
        "captured_at": "2026-10-05T11:59:30Z",
        "vehicle_id": "UAV-01",
        "camera_id": "front_rgb",
    },
    "criterion_version": "l2-criterion-v0.1",
    "reviewer": "human:zyq",
    "reviewed_at": "2026-10-05T12:00:00Z",
    "outcome": "observed",
    "confidence": None,
    "region": {"x": 512, "y": 384, "w": 256, "h": 192},
    "note": "目标位于画面中央偏右。",
    "linked_task_completion": LINKED_TASK_COMPLETION_NOT_ASSERTED,
}


def _mutated(**changes):
    """在合法记录上改一处（顶层字段）。"""
    record = json.loads(json.dumps(VALID))
    record.update(changes)
    return record


def _codes(violations) -> set[str]:
    return {v.get("code") for v in violations}


# --- 合法记录 ---------------------------------------------------------------


def test_valid_record_passes() -> None:
    normalized = validate_review(VALID)
    assert normalized["review_id"] == VALID["review_id"]
    assert normalized["outcome"] == "observed"


def test_valid_not_observed_with_note_passes() -> None:
    record = _mutated(outcome="not_observed")
    assert validate_review(record)["outcome"] == "not_observed"


def test_valid_undetermined_with_note_passes() -> None:
    record = _mutated(outcome="undetermined")
    assert validate_review(record)["outcome"] == "undetermined"


# --- 规则一：不得编造数值置信度 ---------------------------------------------


@pytest.mark.parametrize("confidence", [1.0, 0.0, 0.87, 1, 0])
def test_numeric_confidence_is_rejected(confidence) -> None:
    """任何数值置信度都必须拒绝，包括看起来"保守"的 0.5。

    尤其 `1.0` —— 算法侧点名过「没有检测器时不要填造 confidence: 1.0」。
    """
    with pytest.raises(ReviewValidationError) as excinfo:
        validate_review(_mutated(confidence=confidence))
    assert CONFIDENCE_MUST_BE_NULL in _codes(excinfo.value.violations)


def test_missing_confidence_is_rejected() -> None:
    """`confidence` 必须**显式**为 null，不能省略。

    省略会让"忘了填"与"确实没有"看起来一样。
    """
    record = json.loads(json.dumps(VALID))
    del record["confidence"]
    with pytest.raises(ReviewValidationError) as excinfo:
        validate_review(record)
    assert CONFIDENCE_MUST_BE_NULL in _codes(excinfo.value.violations)


# --- 规则二：reviewer 必须是人工 --------------------------------------------


@pytest.mark.parametrize(
    "reviewer",
    ["detector:yolo-v8", "auto:", "system", "", "   ", "human", "Human:zyq", None, 42],
)
def test_non_human_reviewer_is_rejected(reviewer) -> None:
    """非 `human:` 前缀一律拒绝。

    这里刻意**不**接受 `Human:zyq` 这种大小写变体 —— 前缀是机器读的约定，
    允许变体会让下游的判别逻辑变得不可靠。
    """
    with pytest.raises(ReviewValidationError):
        validate_review(_mutated(reviewer=reviewer))


def test_human_reviewer_with_empty_identity_is_rejected() -> None:
    """`human:` 后面必须有实际标识，否则无法追溯是谁复核的。"""
    with pytest.raises(ReviewValidationError):
        validate_review(_mutated(reviewer="human:"))


# --- 规则三：not_observed 必须给出依据 --------------------------------------


def test_not_observed_without_evidence_is_rejected() -> None:
    """没有区域也没有说明的 not_observed 必须拒绝。

    它只表示"在这份图像中未按判据看到"，不证明目标不存在；
    而"没有依据的否定"与"检测器没报"在数据上无法区分。
    """
    record = _mutated(outcome="not_observed")
    del record["region"]
    del record["note"]
    with pytest.raises(ReviewValidationError) as excinfo:
        validate_review(record)
    assert "missing_negative_evidence" in _codes(excinfo.value.violations)


def test_undetermined_without_evidence_is_also_rejected() -> None:
    """`undetermined` 也要说明为什么判不了 —— 否则它与"没填"无法区分。"""
    record = _mutated(outcome="undetermined")
    del record["region"]
    del record["note"]
    with pytest.raises(ReviewValidationError) as excinfo:
        validate_review(record)
    assert "missing_negative_evidence" in _codes(excinfo.value.violations)


def test_observed_without_evidence_is_allowed() -> None:
    """肯定结论不强制要求区域 —— 但 retained 说明仍建议填写（不强制）。"""
    record = _mutated(outcome="observed")
    del record["region"]
    del record["note"]
    assert validate_review(record)["outcome"] == "observed"


# --- 图像引用必须不可变且自洽 -----------------------------------------------


def test_image_hash_must_match_ref() -> None:
    """`ref` 与 `sha256` 不一致时必须拒绝。"""
    record = json.loads(json.dumps(VALID))
    record["image"]["sha256"] = "b" * 64
    with pytest.raises(ReviewValidationError) as excinfo:
        validate_review(record)
    assert "image_ref_hash_mismatch" in _codes(excinfo.value.violations)


@pytest.mark.parametrize("bad", ["a" * 63, "a" * 65, "A" * 64, "zz" + "a" * 62, ""])
def test_malformed_sha256_is_rejected(bad: str) -> None:
    record = json.loads(json.dumps(VALID))
    record["image"]["sha256"] = bad
    record["image"]["ref"] = "sha256:" + bad
    with pytest.raises(ReviewValidationError):
        validate_review(record)


def test_required_identity_fields_are_required() -> None:
    """任务/目标/采集标识缺一不可 —— 缺了就无法追溯到是哪一次采集。"""
    for field in ("task_id", "target_id", "capture_id", "criterion_version"):
        record = json.loads(json.dumps(VALID))
        del record[field]
        with pytest.raises(ReviewValidationError) as excinfo:
            validate_review(record)
        assert "missing_field" in _codes(excinfo.value.violations), field


@pytest.mark.parametrize("field", ["task_id", "target_id", "capture_id", "criterion_version"])
@pytest.mark.parametrize("empty", ["", "   "])
def test_empty_identity_fields_are_rejected(field: str, empty: str) -> None:
    """**空字符串**必须被拒，不能靠"键存在"就算通过。

    这条是回归：最初必填检查只查 `field in record`，于是 `capture_id: ""`
    一路放行 —— 而一个空的 `capture_id` 没有任何东西能把它关联到某次采集，
    恰好废掉这个字段的全部意义。

    这个洞是先在前端 JS 实现里被测试抓到的，Python 侧当时有同样的洞。
    两端实现共用一个盲区，正是"两份实现要同步"这条约定的价值所在。
    """
    record = _mutated(**{field: empty})
    with pytest.raises(ReviewValidationError) as excinfo:
        validate_review(record)
    assert "empty_identity_field" in _codes(excinfo.value.violations), field


# --- 结构性约束：任务完成状态无从表达 ---------------------------------------


def test_linked_task_completion_must_be_not_asserted() -> None:
    """`linked_task_completion` 只能取 `not_asserted`。

    三方共识要求 CAPTURE 成功不能自动完成 OBSERVE、巡检步骤或原任务。
    这里不靠"记得别那么做"，而是让记录**无从表达**任务完成。
    """
    for bad in ("completed", "asserted", "true", True, 1):
        with pytest.raises(ReviewValidationError):
            validate_review(_mutated(linked_task_completion=bad))


def test_record_cannot_express_task_completion_at_all() -> None:
    """记录里不该存在任何"任务已完成"含义的字段。

    这条是防回退的：将来若有人想加一个 `task_completed: true`，它会变红。
    """
    normalized = validate_review(VALID)
    suspicious = [
        k for k in normalized
        if "complet" in k.lower() and k != "linked_task_completion"
    ]
    assert suspicious == [], f"记录里不该有任务完成字段：{suspicious}"
    assert normalized["linked_task_completion"] == LINKED_TASK_COMPLETION_NOT_ASSERTED


# --- 校验器收集全部违规，不是遇错即停 ---------------------------------------


def test_validator_reports_all_violations_not_just_the_first() -> None:
    """一次报全，避免调用方"改一个跑一次"。"""
    record = _mutated(confidence=0.9, reviewer="detector:x")
    del record["capture_id"]
    with pytest.raises(ReviewValidationError) as excinfo:
        validate_review(record)
    codes = _codes(excinfo.value.violations)
    assert CONFIDENCE_MUST_BE_NULL in codes
    assert "missing_field" in codes
    assert len(excinfo.value.violations) >= 3


# --- 构建、哈希与读写 -------------------------------------------------------


def test_build_review_fills_identifiers_and_is_deterministic() -> None:
    """同一输入应得到同一 `review_id` —— 记录本身要被哈希引用，不能每次不同。

    `created_at` 显式传入：不传的话它取当前时间，两次构建的 `created_at` 不同，
    而 `review_id` 由内容派生 —— 那样这条断言就变成在测时钟，不是测确定性。
    （第一版漏了这一点，测试因此失败；是测试的问题，不是实现的。）
    """
    kwargs = dict(
        task_id="TASK-1", target_id="target-001",
        capture_id="cap-0123456789abcdef",
        image=VALID["image"], criterion_version="l2-criterion-v0.1",
        reviewer="human:zyq", reviewed_at="2026-10-05T12:00:00Z",
        outcome="observed", note="target visible",
        created_at="2026-10-05T12:00:00Z",
    )
    first = build_review(**kwargs)
    second = build_review(**kwargs)
    assert first["review_id"] == second["review_id"]
    assert first["review_id"].startswith("rev-")
    assert first["created_at"] == "2026-10-05T12:00:00Z"


def test_build_review_defaults_created_at_to_now() -> None:
    """不传 `created_at` 时取当前时间（UTC，以 Z 结尾）。"""
    record = build_review(
        task_id="TASK-1", target_id="target-001",
        capture_id="cap-0123456789abcdef",
        image=VALID["image"], criterion_version="l2-criterion-v0.1",
        reviewer="human:zyq", reviewed_at="2026-10-05T12:00:00Z",
        outcome="observed", note="target visible",
    )
    assert record["created_at"].endswith("Z")
    assert record["created_at"][:2] == "20"


def test_build_review_rejects_detector_reviewer() -> None:
    """构建入口也要拦 —— 不能只在校验时拦。"""
    with pytest.raises(ReviewValidationError):
        build_review(
            task_id="TASK-1", target_id="target-001",
            capture_id="cap-0123456789abcdef",
            image=VALID["image"], criterion_version="l2-criterion-v0.1",
            reviewer="detector:yolo", reviewed_at="2026-10-05T12:00:00Z",
            outcome="observed",
        )


def test_record_sha256_changes_when_content_changes() -> None:
    a = validate_review(VALID)
    b = validate_review(_mutated(outcome="not_observed"))
    assert record_sha256(a) != record_sha256(b)
    assert len(record_sha256(a)) == 64


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    record = validate_review(VALID)
    path = write_review(record, tmp_path)
    assert path.exists()
    # 落盘后必须还能原样读回并通过校验 —— 否则记录会随时间变得不可用
    assert validate_review(read_review(path)) == record


def test_write_review_is_content_addressed(tmp_path: Path) -> None:
    """文件名应包含内容哈希，便于发现被改动过的记录。"""
    record = validate_review(VALID)
    path = write_review(record, tmp_path)
    assert record_sha256(record)[:16] in path.name


def test_read_review_rejects_tampered_record(tmp_path: Path) -> None:
    """被改动过的记录必须在校验时被拒，而不是静默通过。"""
    record = validate_review(VALID)
    path = write_review(record, tmp_path)
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["confidence"] = 0.99  # 事后补一个"置信度"
    path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ReviewValidationError):
        validate_review(read_review(path))
