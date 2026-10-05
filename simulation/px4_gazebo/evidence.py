"""Versioned, time-bounded evidence shared by simulation producers."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def timestamp_seconds(value: Any) -> float:
    if not isinstance(value, str):
        raise ValueError("timestamp_required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp_timezone_required")
    return parsed.timestamp()


def freshness(payload: dict[str, Any], *, now: float | None = None) -> tuple[bool, str, float | None]:
    """Check the producer's timestamp, not the time a saved file was read."""
    try:
        if payload.get("contract_version") != "1.0":
            return False, "unsupported_evidence_version", None
        ttl = payload["valid_for_ms"]
        if isinstance(ttl, bool) or not isinstance(ttl, (float, int)) or not math.isfinite(ttl) or not 100 <= ttl <= 60000:
            raise ValueError("invalid_evidence_ttl")
        age = ((datetime.now(timezone.utc).timestamp() if now is None else now)
               - timestamp_seconds(payload["source_timestamp"])) * 1000
        if age < -100:
            return False, "evidence_from_future", age
        if age > ttl:
            return False, "evidence_stale", age
        return True, "ok", max(0.0, age)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False, "invalid_evidence_timestamp_or_ttl", None


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def json_messages(output: str) -> list[dict[str, Any]]:
    """解析 ``gz topic --json-output`` 的输出。

    ⚠️ **不能假设"每行一个 JSON 对象"。**

    实测教训（2026-10-05 三机相机版巡逻验收）：UAV-01 的标定检查抛出
    ``Extra data: line 1 column 14 (char 13)``，导致 ``status: FAIL`` ——
    而三台的 ARM/TAKEOFF/降落**全部正常**。根因就是这里：

        capture_poses() → json_messages(stdout)     ← 没有 try，异常直接抛
        json_messages() → json.loads(line)          ← 按行解析
        → 抛进 patrol._monitor_origin → _calibration_error
        → calibration_valid_at_end = False

    ``gz topic`` 会把**多个对象写进同一行**。三机 + 三路相机比原来的负载大得多
    （RTF 0.948、每路 30fps），更容易撞上。

    用 ``JSONDecoder.raw_decode`` 增量解析：对「每行一个」「一行多个」
    「带前导/尾随空白」三种情况都成立 —— **严格比按行解析更宽容**，
    因此不改变任何当前能工作的场景。

    Raises:
        ValueError: 某个值是合法 JSON 但不是对象（下游按 dict 取字段，
            放任会变成更晚、更难定位的 KeyError）。
        json.JSONDecodeError: 输出被截断，或对象之后跟着非 JSON 内容。
            **不静默丢弃** —— 位姿序列是标定与间距判据的依据，
            少一帧可能让判据算错而不报错。
    """
    decoder = json.JSONDecoder()
    rows: list[dict[str, Any]] = []
    index = 0
    length = len(output)
    while index < length:
        # 跳过对象之间的空白（空格、换行、制表符）
        while index < length and output[index].isspace():
            index += 1
        if index >= length:
            break
        value, index = decoder.raw_decode(output, index)
        if not isinstance(value, dict):
            raise ValueError("gazebo_message_not_object")
        rows.append(value)
    return rows


def proto_time(value: dict[str, Any]) -> float:
    return int(value.get("sec", 0)) + int(value.get("nsec", 0)) / 1_000_000_000
