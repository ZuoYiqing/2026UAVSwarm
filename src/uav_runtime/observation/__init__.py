"""观察（OBSERVE）相关的数据结构与工具。

本包现在只有一样东西：L2 观察复核记录。它的存在理由见
``docs/OBSERVE_review_record_spec_v0_1.md`` —— 简单说，采集到图像（L1）与
判定是否观察到目标（L2）是两件事，后者需要独立、可追溯、**不可伪造**的记录。
"""

from uav_runtime.observation.review_record import (  # noqa: F401
    CONFIDENCE_MUST_BE_NULL,
    LINKED_TASK_COMPLETION_NOT_ASSERTED,
    REVIEW_VERSION,
    VALID_OUTCOMES,
    ReviewValidationError,
    build_review,
    read_review,
    record_sha256,
    validate_review,
    write_review,
)

__all__ = [
    "CONFIDENCE_MUST_BE_NULL",
    "LINKED_TASK_COMPLETION_NOT_ASSERTED",
    "REVIEW_VERSION",
    "VALID_OUTCOMES",
    "ReviewValidationError",
    "build_review",
    "read_review",
    "record_sha256",
    "validate_review",
    "write_review",
]
