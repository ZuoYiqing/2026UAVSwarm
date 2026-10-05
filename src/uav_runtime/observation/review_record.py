"""L2 观察复核记录：格式、校验、构建与读写。

为什么需要这个模块
------------------
采集到图像（L1，`CAPTURE`）与判定"是否观察到目标"（L2）是两件事。
三方已对齐：**`CAPTURE` 的 `pass` 只表示真实图像采集及关联证据满足要求，
不能把 `OBSERVE`、巡检步骤或原任务标记为已完成。**

本阶段 L2 只接受**人工复核**。这个模块把那组字段固化成可校验的记录，
并用三条规则挡住最容易出的问题：

  1. **不得编造数值置信度**（`confidence` 必须为 `null`）
  2. **`reviewer` 必须是 `human:` 前缀**（不接受检测器/自动结果）
  3. **`not_observed` 必须给出依据**（区域或说明）

为什么用校验器而不是"写文档让大家照着填"
----------------------------------------
文档拦不住"给人工判断补一个 0.95"，也拦不住"没看到"被写成"不存在"。
校验器能。而且违规是**一次报全**的，便于调用方一轮改完。

⚠️ 本模块**不能**证明记录来自真实采集
------------------------------------
它只能保证**格式与哈希自洽**（`image.ref` 与 `image.sha256` 一致）。
现在没有 L1 端点，`capture_id` 与哈希都靠人工录入 ——
**防得住"编造置信度"，防不住"整条记录都是编的"**。
等 `CAPTURE` 端点接通、`capture_id` 由 Runtime 签发后，这一点才会成立。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: 记录格式版本。格式变化时递增，便于识别旧记录。
REVIEW_VERSION = "0.1"

#: 允许的结论取值。
#:
#: * ``observed``       —— 按判据在这份图像中看到了目标
#: * ``not_observed``   —— 按判据在这份图像中**没**看到（**不证明目标不存在**）
#: * ``undetermined``   —— 判不了（模糊、遮挡、区域外…）
VALID_OUTCOMES = ("observed", "not_observed", "undetermined")

#: `confidence` 必须为 `null` 时使用的违规码。
CONFIDENCE_MUST_BE_NULL = "confidence_must_be_null"

#: `linked_task_completion` 的唯一合法取值。
#:
#: 固定值，不是枚举里的一个选项 —— 记录**无从表达**"任务已完成"。
#: 三方共识要求 CAPTURE 成功不能自动完成 OBSERVE 或原任务；
#: 要表达任务完成需要另一个显式动作（尚未设计）。
LINKED_TASK_COMPLETION_NOT_ASSERTED = "not_asserted"

#: 人工复核者的前缀。本阶段只接受人工结论。
HUMAN_REVIEWER_PREFIX = "human:"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_FIELDS = (
    "review_version",
    "review_id",
    "created_at",
    "task_id",
    "target_id",
    "capture_id",
    "image",
    "criterion_version",
    "reviewer",
    "reviewed_at",
    "outcome",
    "confidence",
    "linked_task_completion",
)

_IMAGE_REQUIRED_FIELDS = (
    "ref",
    "sha256",
    "width",
    "height",
    "encoding",
    "captured_at",
    "vehicle_id",
    "camera_id",
)

#: 必须是**非空字符串**的标识类字段。
#:
#: 存在性与非空是两件事：`{"capture_id": ""}` 通过了"键存在"检查，
#: 却让记录无法关联到任何采集。
_IDENTITY_FIELDS = (
    "review_id",
    "task_id",
    "target_id",
    "capture_id",
    "criterion_version",
    "reviewed_at",
)


class ReviewValidationError(ValueError):
    """复核记录不合法。

    ``violations`` 里是**全部**违规项，不是第一个 —— 便于调用方一轮改完。
    """

    def __init__(self, message: str, violations: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.violations = list(violations or [])

    def to_dict(self) -> dict[str, Any]:
        return {"error": "review_invalid", "message": str(self), "violations": self.violations}


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_review(record: Any) -> dict[str, Any]:
    """校验一条复核记录。

    Args:
        record: 待校验的记录（应为 dict）。

    Returns:
        归一化后的记录（浅拷贝 + 规范化），可直接落盘。

    Raises:
        ReviewValidationError: 含**全部**违规项。
    """
    violations: list[dict[str, Any]] = []

    if not isinstance(record, dict):
        raise ReviewValidationError(
            f"复核记录必须是对象，实际是 {type(record).__name__}",
            [{"code": "not_an_object", "actual_type": type(record).__name__}],
        )

    # --- 必填字段 ---------------------------------------------------------
    #
    # ⚠️ 只查"键在不在"是不够的：**空字符串**能通过存在性检查，而一个
    # `capture_id: ""` 的记录没有任何东西能把它关联到某次采集 —— 恰好废掉
    # 这个字段的全部意义。因此标识类字段必须是**非空字符串**。
    # （这个洞是先在前端实现里发现的：`capture_id` 传空串时校验器放行。）
    for field in _REQUIRED_FIELDS:
        if field not in record:
            violations.append({"code": "missing_field", "field": field})
    for field in _IDENTITY_FIELDS:
        if field in record and not _is_non_empty_string(record[field]):
            violations.append({
                "code": "empty_identity_field", "field": field, "value": record[field],
                "hint": (
                    "标识类字段必须是非空字符串。空值会让这条记录无法关联到"
                    "任何任务、目标或采集。"
                ),
            })

    # --- 规则一：不得编造数值置信度 ---------------------------------------
    #
    # 注意这里检查的是"键存在且值为 null"，不是"值假"。`confidence: 0` 也要拒 ——
    # 它同样是把一个主观印象伪装成一个测量值。
    #
    # `confidence` **缺失**也按同一条规则报（而不是笼统的 missing_field）：
    # 省略会让"忘了填"与"确实没有"看起来一样，而这条恰恰是要区分这件事的。
    if "confidence" not in record or record["confidence"] is not None:
        violations.append({
            "code": CONFIDENCE_MUST_BE_NULL,
            "field": "confidence",
            "value": record.get("confidence"),
            "hint": (
                "人工结论不伪造数值置信度。必须显式填 null，并把判断依据写进 region 或 note。"
                "给一个 0–1 的数字会被下游当成模型输出概率，而它实际是主观印象。"
            ),
        })

    # --- 规则二：reviewer 必须是人工 --------------------------------------
    #
    # ⚠️ `None` 必须被拒，不能"值为空就跳过检查" —— 那样一条 reviewer=None 的
    # 记录会绕过规则二。最初写成 `if reviewer is not None:` 就有这个洞。
    reviewer = record.get("reviewer")
    if reviewer is None or not isinstance(reviewer, str):
        violations.append({
            "code": "reviewer_not_human", "field": "reviewer", "value": reviewer,
            "hint": f"reviewer 必须是非空字符串且以 {HUMAN_REVIEWER_PREFIX!r} 开头。",
        })
    elif not reviewer.startswith(HUMAN_REVIEWER_PREFIX):
        violations.append({
            "code": "reviewer_not_human", "field": "reviewer", "value": reviewer,
            "hint": (
                f"本阶段 L2 只接受人工复核，reviewer 必须以 {HUMAN_REVIEWER_PREFIX!r} 开头。"
                "仿真真值只能用于离线标注与评价，不得写入运行时检测或冒充检测结果。"
            ),
        })
    elif not reviewer[len(HUMAN_REVIEWER_PREFIX):].strip():
        violations.append({
            "code": "reviewer_not_human", "field": "reviewer", "value": reviewer,
            "hint": f"{HUMAN_REVIEWER_PREFIX!r} 后必须有实际标识，否则无法追溯是谁复核的。",
        })

    # --- 结论取值 ---------------------------------------------------------
    outcome = record.get("outcome")
    if outcome is not None and outcome not in VALID_OUTCOMES:
        violations.append({
            "code": "invalid_outcome", "field": "outcome", "value": outcome,
            "allowed": list(VALID_OUTCOMES),
        })

    # --- 规则三：否定/未判定必须给出依据 ----------------------------------
    #
    # `not_observed` 只表示"在这份图像中未按判据看到"，**不证明目标不存在**。
    # 没有依据的否定与"检测器没报"在数据上无法区分 —— 而后者不能作为结论。
    has_region = isinstance(record.get("region"), dict) and bool(record.get("region"))
    has_note = _is_non_empty_string(record.get("note"))
    if outcome in ("not_observed", "undetermined") and not (has_region or has_note):
        violations.append({
            "code": "missing_negative_evidence",
            "field": "note",
            "outcome": outcome,
            "hint": (
                f"outcome={outcome!r} 必须给出 region 或 note。"
                "not_observed 只表示「在这份图像中未按判据看到」，不证明目标不存在；"
                "没有依据的否定与「检测器没报」无法区分。"
            ),
        })

    # --- 图像引用 ---------------------------------------------------------
    image = record.get("image")
    if image is not None:
        if not isinstance(image, dict):
            violations.append({"code": "invalid_image", "field": "image", "value": image})
        else:
            for field in _IMAGE_REQUIRED_FIELDS:
                if field not in image:
                    violations.append({"code": "missing_field", "field": f"image.{field}"})
            sha = image.get("sha256")
            if sha is not None and not (isinstance(sha, str) and _SHA256_RE.match(sha)):
                violations.append({
                    "code": "malformed_sha256", "field": "image.sha256", "value": sha,
                    "hint": "必须是 64 位小写十六进制。",
                })
            ref = image.get("ref")
            if isinstance(ref, str) and isinstance(sha, str):
                expected = f"sha256:{sha}"
                if ref != expected:
                    violations.append({
                        "code": "image_ref_hash_mismatch",
                        "field": "image.ref",
                        "value": ref,
                        "expected": expected,
                        "hint": (
                            "ref 必须与 sha256 自洽。引用不可变，否则同一条记录会指向不同图像。"
                        ),
                    })

    # --- 结构性约束：无从表达"任务已完成" ---------------------------------
    linked = record.get("linked_task_completion")
    if linked is not None and linked != LINKED_TASK_COMPLETION_NOT_ASSERTED:
        violations.append({
            "code": "task_completion_not_representable",
            "field": "linked_task_completion",
            "value": linked,
            "allowed": [LINKED_TASK_COMPLETION_NOT_ASSERTED],
            "hint": (
                "复核记录无从表达「任务已完成」。CAPTURE 成功不能自动完成 OBSERVE、"
                "巡检步骤或原任务；要表达任务完成需要另一个显式动作（尚未设计），"
                "它必须同时引用 capture_id 与 review_id 并有自己的授权路径。"
            ),
        })

    if violations:
        raise ReviewValidationError(
            f"复核记录有 {len(violations)} 处不合法，已拒绝（不部分采纳）。", violations
        )

    normalized = dict(record)
    normalized["review_version"] = str(normalized.get("review_version") or REVIEW_VERSION)
    normalized["confidence"] = None
    normalized["linked_task_completion"] = LINKED_TASK_COMPLETION_NOT_ASSERTED
    normalized["outcome"] = str(normalized["outcome"])
    return normalized


def record_sha256(record: dict[str, Any]) -> str:
    """记录内容的 SHA-256（键排序、紧凑分隔符），用于内容寻址。

    用规范化 JSON 而不是原始文本：同一份记录因缩进或键序不同而得到不同哈希，
    会让"内容没变"这件事无法判断。
    """
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_review(
    *,
    task_id: str,
    target_id: str,
    capture_id: str,
    image: dict[str, Any],
    criterion_version: str,
    reviewer: str,
    reviewed_at: str,
    outcome: str,
    region: dict[str, Any] | None = None,
    note: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """构造一条复核记录并校验。

    ``review_id`` 由记录内容派生，因此**同一输入得到同一 id** ——
    记录本身要被哈希引用，不能每次构建都不同（否则无法判断是不是同一条）。

    ⚠️ 构建入口也做校验，不能只在校验时拦：否则可以经 build 造出一条
    `reviewer="detector:..."` 的记录，再想办法绕过校验落盘。

    Raises:
        ReviewValidationError: 含全部违规项。
    """
    record: dict[str, Any] = {
        "review_version": REVIEW_VERSION,
        "created_at": created_at or _utc_now_iso(),
        "task_id": task_id,
        "target_id": target_id,
        "capture_id": capture_id,
        "image": dict(image),
        "criterion_version": criterion_version,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "outcome": outcome,
        # 本阶段人工结论一律不编造数值置信度。
        "confidence": None,
        "linked_task_completion": LINKED_TASK_COMPLETION_NOT_ASSERTED,
    }
    if region is not None:
        record["region"] = dict(region)
    if note is not None:
        record["note"] = note

    # review_id 由内容派生。先去掉 review_id 占位再算，避免自引用。
    record["review_id"] = "rev-" + _derive_id(record)
    return validate_review(record)


def _derive_id(record: dict[str, Any]) -> str:
    """由记录内容派生稳定的 16 位十六进制标识。"""
    payload = {k: v for k, v in record.items() if k != "review_id"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def write_review(record: dict[str, Any], directory: str | Path) -> Path:
    """把校验过的记录写入目录，文件名带内容哈希前缀。

    文件名带哈希是为了**发现被改动过的记录**：文件内容变了、名字里的哈希没变，
    一眼就能看出不一致。

    Returns:
        写入的文件路径。
    """
    validated = validate_review(record)
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = record_sha256(validated)
    path = target_dir / f"{validated['review_id']}-{digest[:16]}.json"
    path.write_text(
        json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_review(path: str | Path) -> dict[str, Any]:
    """读取一份记录文件（不校验；校验请调用 :func:`validate_review`）。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))
