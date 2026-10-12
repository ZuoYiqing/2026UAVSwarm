"""Small JSON schema helpers for the local Runtime HTTP Bridge.

The bridge intentionally uses plain dictionaries/dataclasses instead of a large
web framework contract so tests and local development can run without extra
runtime dependencies.  These helpers normalize browser JSON into the existing
uav_runtime config objects without exposing shell commands.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig


class RequestValidationError(ValueError):
    """Stable HTTP-boundary validation error for frontend handling."""

    def __init__(self, error: str, field: str, message: str, *, value: Any = None, supported: list[str] | None = None) -> None:
        super().__init__(message)
        self.error, self.field, self.message = error, field, message
        self.value, self.supported = value, supported

    def to_dict(self) -> dict[str, Any]:
        value = self.value
        if isinstance(value, float) and not math.isfinite(value):
            value = "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
        result: dict[str, Any] = {
            "error": self.error, "message": self.message, "field": self.field,
            "node_id": None, "details": {}, "value": value,
        }
        if self.supported is not None:
            result["supported"] = self.supported
        return result


def _bool(value: Any, default: bool = False, *, field: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise RequestValidationError(
        "invalid_parameter",
        field,
        f"{field} must be a boolean",
        value=value,
    )


def _int(value: Any, default: int, *, field: str, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise RequestValidationError("invalid_parameter", field, f"{field} must be an integer", value=value)
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise RequestValidationError("invalid_parameter", field, f"{field} must be an integer", value=value)
    if not minimum <= parsed <= maximum:
        raise RequestValidationError("invalid_parameter", field, f"{field} must be within [{minimum}, {maximum}]", value=value)
    return parsed


def _float(value: Any, default: float, *, field: str, minimum_exclusive: float, maximum: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise RequestValidationError("invalid_parameter", field, f"{field} must be numeric", value=value)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise RequestValidationError("invalid_parameter", field, f"{field} must be numeric", value=value)
    if not math.isfinite(parsed) or not minimum_exclusive < parsed <= maximum:
        raise RequestValidationError("invalid_parameter", field, f"{field} must be finite and within ({minimum_exclusive}, {maximum}]", value=value)
    return parsed


def _optional_identifier(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    parsed = str(value).strip()
    if not parsed or len(parsed) > 128 or any(char.isspace() for char in parsed):
        raise RequestValidationError(
            "invalid_parameter",
            field,
            f"{field} must be a non-empty, whitespace-free string of at most 128 characters",
            value=value,
        )
    return parsed


@dataclass(slots=True)
class BackendRequest:
    node_id: str | None = None
    system_id: int | None = None
    component_id: int | None = None
    backend: str = "px4_sitl"
    backend_mode: str = "sitl"
    backend_enabled: bool = False
    transport_endpoint: str = ""
    connect_timeout_ms: int = 3000
    command_timeout_ms: int = 10000
    observe_timeout_ms: int = 25000
    timeout_ms: int = 3000
    retry_count: int = 0
    request_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None
    command_source: str = "ground_station"

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "BackendRequest":
        backend = str(payload.get("backend", "px4_sitl") or "px4_sitl")
        backend_mode = str(payload.get("backend_mode", "sitl") or "sitl")
        if backend != "px4_sitl":
            raise RequestValidationError("unsupported_backend", "backend", "HTTP bridge v0.1 only supports px4_sitl", value=backend, supported=["px4_sitl"])
        if backend_mode != "sitl":
            raise RequestValidationError("unsupported_backend_mode", "backend_mode", "HTTP bridge v0.1 only supports sitl", value=backend_mode, supported=["sitl"])
        command_source = str(payload.get("command_source", "ground_station") or "ground_station")
        if command_source not in {"ground_station", "agent"}:
            raise RequestValidationError(
                "invalid_command_source",
                "command_source",
                "command_source must be ground_station or agent",
                value=command_source,
                supported=["ground_station", "agent"],
            )
        return cls(
            node_id=str(payload["node_id"]) if payload.get("node_id") else None,
            system_id=(
                None
                if payload.get("system_id") is None
                else _int(payload.get("system_id"), 1, field="system_id", minimum=1, maximum=255)
            ),
            component_id=(
                None
                if payload.get("component_id") is None
                else _int(payload.get("component_id"), 1, field="component_id", minimum=1, maximum=255)
            ),
            backend=backend,
            backend_mode=backend_mode,
            backend_enabled=_bool(payload.get("backend_enabled"), False, field="backend_enabled"),
            # Preserve udpin: endpoints exactly.  PX4 SITL onboard MAVLink expects
            # pymavlink to listen on udpin:127.0.0.1:14540; do not rewrite to udp://.
            transport_endpoint=str(payload.get("transport_endpoint", "") or ""),
            connect_timeout_ms=_int(payload.get("connect_timeout_ms"), 3000, field="connect_timeout_ms", minimum=1000, maximum=60000),
            command_timeout_ms=_int(payload.get("command_timeout_ms"), 10000, field="command_timeout_ms", minimum=1000, maximum=60000),
            observe_timeout_ms=_int(payload.get("observe_timeout_ms"), 25000, field="observe_timeout_ms", minimum=1000, maximum=120000),
            timeout_ms=_int(payload.get("timeout_ms"), 3000, field="timeout_ms", minimum=1000, maximum=120000),
            retry_count=_int(payload.get("retry_count"), 0, field="retry_count", minimum=0, maximum=10),
            request_id=_optional_identifier(payload.get("request_id"), field="request_id"),
            trace_id=_optional_identifier(payload.get("trace_id"), field="trace_id"),
            idempotency_key=_optional_identifier(payload.get("idempotency_key"), field="idempotency_key"),
            command_source=command_source,
        )

    def to_mavlink_config(self) -> MavlinkBackendConfig:
        return MavlinkBackendConfig(
            backend_mode=self.backend_mode,
            backend_enabled=self.backend_enabled,
            transport_endpoint=self.transport_endpoint,
            target_system=self.system_id,
            target_component=self.component_id,
            connect_timeout_ms=self.connect_timeout_ms,
            command_timeout_ms=self.command_timeout_ms,
            observe_timeout_ms=self.observe_timeout_ms,
            timeout_ms=self.timeout_ms,
            retry_count=self.retry_count,
        )


@dataclass(slots=True)
class SmokeTakeoffRequest(BackendRequest):
    altitude_m: float = 3.0
    threshold_ratio: float = 0.70
    auto_land: bool = True

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "SmokeTakeoffRequest":
        base = BackendRequest.from_json(payload)
        return cls(
            **asdict(base),
            altitude_m=_float(payload.get("altitude_m"), 3.0, field="altitude_m", minimum_exclusive=0, maximum=120),
            threshold_ratio=_float(payload.get("threshold_ratio"), 0.70, field="threshold_ratio", minimum_exclusive=0, maximum=1),
            auto_land=_bool(payload.get("auto_land"), True, field="auto_land"),
        )


@dataclass(slots=True)
class TakeoffRequest(BackendRequest):
    altitude_m: float = 3.0
    altitude_tolerance_m: float = 0.3
    stable_duration_ms: int = 1000

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "TakeoffRequest":
        base = BackendRequest.from_json(payload)
        altitude_m = _float(
            payload.get("altitude_m"),
            3.0,
            field="altitude_m",
            minimum_exclusive=0,
            maximum=120,
        )
        altitude_tolerance_m = _float(
            payload.get("altitude_tolerance_m"),
            0.3,
            field="altitude_tolerance_m",
            minimum_exclusive=0,
            maximum=10,
        )
        if altitude_tolerance_m >= altitude_m:
            raise RequestValidationError(
                "invalid_parameter",
                "altitude_tolerance_m",
                "altitude_tolerance_m must be less than altitude_m",
                value=altitude_tolerance_m,
            )
        return cls(
            **asdict(base),
            altitude_m=altitude_m,
            altitude_tolerance_m=altitude_tolerance_m,
            stable_duration_ms=_int(
                payload.get("stable_duration_ms"),
                1000,
                field="stable_duration_ms",
                minimum=100,
                maximum=30000,
            ),
        )


@dataclass(slots=True)
class LandRequest(BackendRequest):
    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "LandRequest":
        base = BackendRequest.from_json(payload)
        return cls(**asdict(base))


@dataclass(slots=True)
class HoldPositionRequest(BackendRequest):
    """保持当前位置悬停（HOLD）。

    不需要坐标：HOLD 的语义就是"待在现在这里"。因此也**不需要标定平移量**，
    与 goto 不同 —— 没有坐标换算就不会有换算错误。

    判据是**位置稳定**而不是模式切换成功：飞控接受 LOITER 不等于飞机停住了。
    """

    tolerance_m: float = 2.0
    hold_s: float = 3.0
    timeout_s: float = 20.0

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "HoldPositionRequest":
        base = BackendRequest.from_json(payload)

        def positive(field: str, default: float, *, allow_zero: bool = True) -> float:
            raw = payload.get(field, default)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise RequestValidationError(
                    "invalid_parameter", field, f"{field} 必须是数字", value=raw
                )
            value = float(raw)
            if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
                raise RequestValidationError(
                    "invalid_parameter", field,
                    f"{field} 必须是非负有限数" if allow_zero else f"{field} 必须大于 0",
                    value=raw,
                )
            return value

        return cls(
            **asdict(base),
            tolerance_m=positive("tolerance_m", 2.0, allow_zero=False),
            hold_s=positive("hold_s", 3.0, allow_zero=False),
            timeout_s=positive("timeout_s", 20.0, allow_zero=False),
        )


@dataclass(slots=True)
class ReturnHomeRequest(BackendRequest):
    """Observe fresh stable arrival at the actual PX4 home through RTL.

    This is not a promise that RTL will stop or land at a designated site.
    ``min_progress_m`` remains a diagnostic field only.
    """

    timeout_s: float = 60.0
    min_progress_m: float = 5.0
    home_tolerance_m: float = 0.75
    stable_duration_ms: int = 1000

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "ReturnHomeRequest":
        base = BackendRequest.from_json(payload)
        values = {}
        for field, default in (("timeout_s", 60.0), ("min_progress_m", 5.0)):
            raw = payload.get(field, default)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise RequestValidationError(
                    "invalid_parameter", field, f"{field} 必须是数字", value=raw
                )
            value = float(raw)
            if not math.isfinite(value) or value <= 0:
                raise RequestValidationError(
                    "invalid_parameter", field, f"{field} 必须是正的有限数", value=raw
                )
            values[field] = value
        tolerance = payload.get("home_tolerance_m", 0.75)
        if (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float))
                or not math.isfinite(float(tolerance)) or not 0.05 <= float(tolerance) <= 5.0):
            raise RequestValidationError("invalid_parameter", "home_tolerance_m", "home_tolerance_m must be within [0.05, 5.0]", value=tolerance)
        return cls(
            **asdict(base), **values,
            home_tolerance_m=float(tolerance),
            stable_duration_ms=_int(payload.get("stable_duration_ms"), 1000,
                                    field="stable_duration_ms", minimum=300, maximum=10000),
        )


@dataclass(slots=True)
class GotoRequest(BackendRequest):
    """飞到共享 scene_ned 坐标系下的指定点。

    坐标语义：``north_m`` / ``east_m`` / ``down_m`` 是 **scene_ned**（共享场景坐标系，
    z 向下为正），不是载具本机坐标。Runtime 用标定测得的平移量换算成本机的
    vehicle_local_ned 再下发：``local = scene - translation_scene_ned_m``。

    **标定无效时动作会被拒绝，不会"尽力而为"地飞。** 缺少平移量却把 scene 坐标
    当本机坐标发出，飞机会飞到一个偏移量之外的错误位置（UAV-02/03 偏 8 米）。
    """

    north_m: float = 0.0
    east_m: float = 0.0
    down_m: float = -3.0
    arrival_tolerance_m: float = 1.0
    hold_s: float = 1.0

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "GotoRequest":
        base = BackendRequest.from_json(payload)

        def finite_in_range(field: str, default: float, low: float, high: float) -> float:
            raw = payload.get(field, default)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise RequestValidationError(
                    "invalid_parameter", field, f"{field} 必须是数字", value=raw
                )
            value = float(raw)
            if not math.isfinite(value) or value < low or value > high:
                raise RequestValidationError(
                    "invalid_parameter",
                    field,
                    f"{field} 必须在 [{low}, {high}] 内且为有限值",
                    value=raw,
                )
            return value

        return cls(
            **asdict(base),
            north_m=finite_in_range("north_m", 0.0, -5000.0, 5000.0),
            east_m=finite_in_range("east_m", 0.0, -5000.0, 5000.0),
            # z 向下为正：-500 到 500 对应 ±500 米高度范围
            down_m=finite_in_range("down_m", -3.0, -500.0, 500.0),
            arrival_tolerance_m=finite_in_range("arrival_tolerance_m", 1.0, 0.05, 50.0),
            hold_s=finite_in_range("hold_s", 1.0, 0.0, 30.0),
        )


@dataclass(slots=True)
class PlanExecuteRequest:
    """Submit a Mission Plan IR for real execution on Runtime.

    This is the contract the algorithm side produces against: it hands over a
    structured plan, Runtime sequences it and applies the Policy Gate before
    every action.

    **Scene identity is required.**  ``plan.scene_id`` and ``plan.map_version``
    must be present and non-empty.  Runtime refuses a plan it cannot check
    against its own active scene, because coordinates only mean something
    relative to a scene: a plan built for one map executed against another
    would fly to positions derived from the wrong reference.

    **Approval is explicit and mandatory.**  It would be convenient to
    auto-approve a submitted plan, but real execution moves aircraft, so the
    caller must state the operator identity and an approve decision.  A
    ``reject`` decision is accepted as a valid request that executes nothing.
    """

    plan: dict[str, Any]
    operator_id: str
    decision: str = "approve"

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "PlanExecuteRequest":
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            raise RequestValidationError(
                "invalid_parameter", "plan", "plan 必须是对象", value=plan
            )
        plan_id = plan.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise RequestValidationError(
                "invalid_parameter", "plan.plan_id", "plan.plan_id 必须是非空字符串",
                value=plan_id,
            )
        # 场景身份：必填。缺失的计划无法与 Runtime 的活动场景核对，
        # 而"无法核对"正是最该拒绝的情况 —— 不能因为字段缺少就跳过校验。
        for field in ("scene_id", "map_version"):
            value = plan.get(field)
            if not isinstance(value, str) or not value.strip():
                raise RequestValidationError(
                    "invalid_parameter",
                    f"plan.{field}",
                    f"plan.{field} 必须是非空字符串（执行前要与 Runtime 的活动场景核对）",
                    value=value,
                )
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            raise RequestValidationError(
                "invalid_parameter", "plan.steps", "plan.steps 必须是非空数组",
                value=steps,
            )
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise RequestValidationError(
                    "invalid_parameter", f"plan.steps[{index}]", "步骤必须是对象", value=step
                )
            if not isinstance(step.get("step_id"), str) or not step["step_id"].strip():
                raise RequestValidationError(
                    "invalid_parameter",
                    f"plan.steps[{index}].step_id",
                    "每个步骤都需要非空 step_id",
                    value=step.get("step_id"),
                )
            if not isinstance(step.get("action_type"), str) or not step["action_type"].strip():
                raise RequestValidationError(
                    "invalid_parameter",
                    f"plan.steps[{index}].action_type",
                    "每个步骤都需要非空 action_type",
                    value=step.get("action_type"),
                )
            params = step.get("params", {})
            if not isinstance(params, dict):
                raise RequestValidationError(
                    "invalid_parameter",
                    f"plan.steps[{index}].params",
                    "params 必须是对象",
                    value=params,
                )
            node_id = step.get("node_id", "")
            if not isinstance(node_id, str):
                raise RequestValidationError(
                    "invalid_parameter",
                    f"plan.steps[{index}].node_id",
                    "node_id 必须是字符串（可以为空，但执行时会被拒绝）",
                    value=node_id,
                )

        operator_id = payload.get("operator_id")
        if not isinstance(operator_id, str) or not operator_id.strip():
            # Runtime 拒绝匿名执行：真实执行需要可追溯的操作者身份。
            raise RequestValidationError(
                "invalid_parameter", "operator_id", "operator_id 必须是非空字符串",
                value=operator_id,
            )

        decision = str(payload.get("decision", "approve") or "approve")
        if decision not in ("approve", "reject"):
            raise RequestValidationError(
                "invalid_parameter", "decision", "decision 只能是 approve 或 reject",
                value=decision,
            )
        return cls(plan=dict(plan), operator_id=operator_id.strip(), decision=decision)


@dataclass(slots=True)
class PlanMissionRequest:
    mission_type: str
    source: str = "ground_station"
    profile: str = "standard"
    dry_run: bool = True
    objective: str = ""

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "PlanMissionRequest":
        return cls(
            mission_type=str(payload.get("mission_type", "") or ""),
            source=str(payload.get("source", "ground_station") or "ground_station"),
            profile=str(payload.get("profile", "standard") or "standard"),
            dry_run=_bool(payload.get("dry_run"), True, field="dry_run"),
            objective=str(payload.get("objective", "") or ""),
        )
