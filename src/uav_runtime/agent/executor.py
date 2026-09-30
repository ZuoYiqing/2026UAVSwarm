"""Map approved MissionPlan steps onto real Runtime HTTP action endpoints.

This is the piece that turns the agent plan lifecycle from a dry-run skeleton
into something that can actually move aircraft.  It deliberately does **one**
thing: translate a plan step into a call on an already-existing, already
validated Runtime action endpoint, and report the outcome.  It does not decide
what to fly, does not bypass the Policy Gate (the HTTP layer still applies it),
and does not reinterpret a failure as a success.

Two rules this module exists to enforce
--------------------------------------
1. **Unimplemented actions are refused, never silently skipped.**

   The v0.1 templates mention ``report_status``, ``camera_capture``,
   ``health_query``, ``sensor_read``, ``land_safe`` and ``hold_position``.
   None of those has a Runtime endpoint.  A step that "succeeds" without doing
   anything is worse than a step that fails: it produces a plan that looks
   complete while nothing happened.  We already hit that class of bug once —
   a position setpoint with the wrong type mask was accepted, streamed at
   10 Hz, produced no error, and moved nothing.

2. **A step with no target vehicle is refused.**

   There is no sensible default vehicle.  Guessing would mean potentially
   flying the wrong aircraft, so the executor refuses instead.

The caller (PlanExecutionController) decides what a failure means for the rest
of the plan; per current operator policy, the first failure aborts the plan.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

#: Steps that can be executed today, mapped to their Runtime endpoint.
#:
#: Keep this list honest: it must contain exactly the actions that have a live,
#: verified endpoint.  Adding a name here without a working endpoint behind it
#: would reintroduce silent no-ops.
IMPLEMENTED_ACTIONS: dict[str, str] = {
    "takeoff": "/actions/takeoff",
    "smoke_takeoff": "/actions/smoke-takeoff",
    "land": "/actions/land",
    "goto": "/actions/goto",
}

#: Actions that are declared somewhere but deliberately have no endpoint yet,
#: split by **why** they have none.  The distinction matters to a caller: for a
#: flight action, "not implemented yet" is accurate and invites a retry after we
#: build it; for a weapon/payload action, "not implemented yet" would wrongly
#: imply it is coming.
#:
#: This is derived from the policy Action Registry rather than maintained by
#: hand.  A hand-written list drifts: the registry declares 21 actions, and a
#: manual list here had already missed 10 of them, including every risk_level=10
#: payload action.  Those omissions produced "unknown_action_type" — a message
#: that reads as "you made a typo" for actions that are in fact declared.
_REGISTRY_FLIGHT_NOT_IMPLEMENTED = frozenset({
    "hover", "hold", "hold_position", "return_home", "land_safe",
    "reduce_speed", "maintain_heading",
})

_REGISTRY_PAYLOAD_NOT_IMPLEMENTED = frozenset({
    "camera_capture", "gimbal_set_angle", "light_set_state", "speaker_play_message",
})

#: Actions that are **not** in the policy registry but that upstream planners do
#: emit.  ``OBSERVE`` is allowed by the algorithm-side proposal schema
#: (mission_proposal.schema.json enumerates TAKEOFF/GOTO/OBSERVE/HOLD/
#: RETURN_HOME/LAND), so a plan can legitimately ask for it.  Without an entry
#: here it would be refused as ``unknown_action_type`` — which reads as "you
#: made a typo" for an action the caller is explicitly permitted to propose.
_UPSTREAM_ONLY_NOT_IMPLEMENTED = frozenset({
    "observe",
})

_REGISTRY_SYSTEM_NOT_IMPLEMENTED = frozenset({
    "health_query", "report_status", "sensor_read",
})

#: Actions that are declared but have no endpoint, and that Runtime would
#: legitimately execute once an endpoint exists.  Refused with a message saying
#: "not implemented", because that is the literal situation.
#:
#: Includes the payload *sensing/annunciation* actions (camera, gimbal, light,
#: speaker): those are normal mission capabilities awaiting an endpoint, unlike
#: the release/weapon actions which are refused as unsupported.
KNOWN_UNIMPLEMENTED_ACTIONS: frozenset[str] = (
    _REGISTRY_FLIGHT_NOT_IMPLEMENTED
    | _REGISTRY_SYSTEM_NOT_IMPLEMENTED
    | _REGISTRY_PAYLOAD_NOT_IMPLEMENTED
    | _UPSTREAM_ONLY_NOT_IMPLEMENTED
)

#: Declared payload actions that release, drop or deploy something, or that are
#: explicitly weapon-like.  All of these carry risk_level=10 in the registry.
#:
#: These are refused with a **different** reason code on purpose.  They are not
#: "coming soon": they have no endpoint, and the refusal must not read as a
#: roadmap item.  A plan that asks for them is refused as an unsupported
#: capability, not queued behind future work.
_UNSAFE_PAYLOAD_ACTIONS: frozenset[str] = frozenset({
    "attack", "strike", "drop", "deploy", "payload_release",
})

#: Every registry-declared action that this executor knows it cannot run.
KNOWN_UNSUPPORTED_ACTIONS: frozenset[str] = (
    KNOWN_UNIMPLEMENTED_ACTIONS | _REGISTRY_PAYLOAD_NOT_IMPLEMENTED | _UNSAFE_PAYLOAD_ACTIONS
)


class StepExecutionRefused(Exception):
    """The step cannot be executed as written (no endpoint, no target, bad params)."""

    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass(slots=True)
class StepOutcome:
    """Result of attempting one plan step."""

    ok: bool
    action_type: str
    node_id: str
    http_status: int | None = None
    accepted: bool | None = None
    result: str | None = None
    failure_reason: str | None = None
    #: Action-specific completion evidence, passed through untouched so the
    #: plan record keeps whatever the Runtime actually observed.
    evidence: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action_type": self.action_type,
            "node_id": self.node_id,
            "http_status": self.http_status,
            "accepted": self.accepted,
            "result": self.result,
            "failure_reason": self.failure_reason,
            "evidence": dict(self.evidence),
        }


def _default_post(url: str, body: dict[str, Any], timeout_s: float) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, allow_nan=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = json.loads(response.read().decode("utf-8") or "{}")
        return int(response.status), payload


class RealActionExecutor:
    """Execute plan steps by calling Runtime action endpoints over HTTP.

    Args:
        api_base: Runtime API base, e.g. ``http://127.0.0.1:8765/api``.
        post: Injectable transport ``(url, body, timeout_s) -> (status, payload)``.
            Defaults to :func:`urllib.request.urlopen`.  Tests inject a fake so
            the state machine can be covered without a live Runtime.
        timeout_s: Per-step HTTP timeout.  ``goto`` flies a real trajectory, so
            this must be generous; the HTTP layer itself also bounds the action.
    """

    def __init__(
        self,
        *,
        api_base: str = "http://127.0.0.1:8765/api",
        post: Callable[[str, dict[str, Any], float], tuple[int, dict[str, Any]]] | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.api_base = str(api_base).rstrip("/")
        self._post = post or _default_post
        self.timeout_s = float(timeout_s)

    # -- parameter shaping -------------------------------------------------

    @staticmethod
    def _build_body(action_type: str, node_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Translate plan-step params into the endpoint's payload.

        Only keys the endpoint understands are forwarded; everything else is
        dropped deliberately rather than passed through, so a planning-layer
        typo cannot silently become an unknown field the Runtime ignores.
        """
        body: dict[str, Any] = {"node_id": node_id}
        if action_type in ("takeoff", "smoke_takeoff"):
            body["altitude_m"] = float(params.get("altitude_m", 3.0))
            if action_type == "takeoff":
                if "altitude_tolerance_m" in params:
                    body["altitude_tolerance_m"] = float(params["altitude_tolerance_m"])
                if "stable_duration_ms" in params:
                    body["stable_duration_ms"] = int(params["stable_duration_ms"])
        elif action_type == "goto":
            # scene_ned: north/east/down, z positive down.
            for key in ("north_m", "east_m", "down_m"):
                if key in params:
                    body[key] = float(params[key])
            if "arrival_tolerance_m" in params:
                body["arrival_tolerance_m"] = float(params["arrival_tolerance_m"])
            if "hold_s" in params:
                body["hold_s"] = float(params["hold_s"])
        # `land` takes only node_id.
        return body

    @staticmethod
    def _completion_evidence(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Pull the fields that prove the action actually completed.

        These are the fields that distinguish "the command was accepted" from
        "the aircraft did the thing", which is exactly the distinction that
        cost us two live-flight bugs.
        """
        evidence: dict[str, Any] = {}
        if action_type in ("takeoff", "smoke_takeoff"):
            completion = payload.get("completion_evidence")
            if isinstance(completion, dict):
                evidence["completion_reached"] = completion.get("completion_reached")
                evidence["last_altitude_m"] = completion.get("last_altitude_m")
                evidence["completion_state"] = payload.get("completion_state")
            arm = payload.get("arm_ack")
            if isinstance(arm, dict):
                evidence["arm_result_name"] = arm.get("result_name")
            takeoff_ack = payload.get("takeoff_ack")
            if isinstance(takeoff_ack, dict):
                evidence["takeoff_result_name"] = takeoff_ack.get("result_name")
        elif action_type == "land":
            completion = payload.get("completion_evidence")
            if isinstance(completion, dict):
                evidence["completion_reached"] = completion.get("completion_reached")
                evidence["completion_state"] = payload.get("completion_state")
            land_ack = payload.get("land_ack")
            if isinstance(land_ack, dict):
                evidence["land_result_name"] = land_ack.get("result_name")
        elif action_type == "goto":
            evidence["mode_confirmed"] = payload.get("mode_confirmed")
            evidence["arrival_observed"] = payload.get("arrival_observed")
            arrival = payload.get("arrival")
            if isinstance(arrival, dict):
                evidence["arrival_error_m"] = arrival.get("last_error_m")
                evidence["arrival_reason"] = arrival.get("reason")
            restored = payload.get("restored")
            if isinstance(restored, dict):
                # still_in_offboard is the dangerous one: the aircraft would be
                # left under external control with no stream feeding it.
                evidence["restored"] = restored.get("restored")
                evidence["still_in_offboard"] = restored.get("still_in_offboard")
                evidence["observed_sub_mode"] = restored.get("observed_sub_mode")
        return evidence

    # -- execution ---------------------------------------------------------

    def execute_step(self, step: Any) -> StepOutcome:
        """Run one plan step. Never raises for ordinary failures.

        Returns a :class:`StepOutcome` describing exactly what happened, so the
        controller can decide plan-level consequences.  Only programming errors
        (unexpected exception types) would escape, and those are converted too,
        because a plan must never be left in a half-updated state by a surprise.
        """
        raw_action_type = str(getattr(step, "action_type", "") or "")
        # 查表大小写不敏感。上游规划层惯用大写（TAKEOFF/OBSERVE），而端点用小写。
        # 若按原样查表，大写 OBSERVE 会被报成 unknown_action_type —— 那会让调用方
        # 以为是拼写错误，而真正的问题是"该动作尚未实现"。拒绝对了，理由错了。
        action_type = raw_action_type.strip().lower()
        node_id = str(getattr(step, "node_id", "") or "")
        params = dict(getattr(step, "params", {}) or {})

        try:
            endpoint = self._require_endpoint(action_type, raw_action_type=raw_action_type)
            self._require_target(node_id, action_type, step)
            body = self._build_body(action_type, node_id, params)
        except StepExecutionRefused as refusal:
            return StepOutcome(
                ok=False,
                action_type=raw_action_type,
                node_id=node_id,
                failure_reason=refusal.code,
                raw={"message": refusal.message, "detail": refusal.detail},
            )

        url = f"{self.api_base}{endpoint}"
        try:
            status, payload = self._post(url, body, self.timeout_s)
        except urllib.error.HTTPError as exc:
            detail = {}
            try:
                detail = json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001 - body may be empty or not JSON
                detail = {}
            return StepOutcome(
                ok=False,
                action_type=action_type,
                node_id=node_id,
                http_status=int(getattr(exc, "code", 0) or 0),
                failure_reason=str(detail.get("failure_reason") or detail.get("error") or f"http_{getattr(exc, 'code', 'unknown')}"),
                raw=detail if isinstance(detail, dict) else {},
            )
        except Exception as exc:  # noqa: BLE001 - network, timeout, JSON, DNS...
            return StepOutcome(
                ok=False,
                action_type=action_type,
                node_id=node_id,
                failure_reason="transport_error",
                raw={"message": f"{type(exc).__name__}: {exc}"},
            )

        if not isinstance(payload, dict):
            return StepOutcome(
                ok=False,
                action_type=action_type,
                node_id=node_id,
                http_status=status,
                failure_reason="malformed_response",
            )

        # The HTTP API returns 200 with accepted=false for refusals, and 200
        # with result="fail" for completed-but-unsuccessful actions.  Both are
        # failures for planning purposes; treating either as success would
        # recreate the "plan says done, aircraft did nothing" bug.
        accepted = payload.get("accepted")
        result = payload.get("result")
        ok = bool(accepted is True) and result != "fail" and status < 400
        return StepOutcome(
            ok=ok,
            action_type=action_type,
            node_id=node_id,
            http_status=status,
            accepted=accepted if isinstance(accepted, bool) else None,
            result=str(result) if result is not None else None,
            failure_reason=None if ok else str(
                payload.get("failure_reason") or payload.get("code") or "action_not_accepted"
            ),
            evidence=self._completion_evidence(action_type, payload),
            raw=payload,
        )

    # -- refusals ----------------------------------------------------------

    @staticmethod
    def _require_endpoint(action_type: str, *, raw_action_type: str = "") -> str:
        """Look up the endpoint for an already-lowercased action type.

        ``raw_action_type`` is echoed into the refusal detail so a caller that
        sent ``OBSERVE`` sees its own spelling back, rather than a silently
        normalised name that no longer matches what it wrote.
        """
        endpoint = IMPLEMENTED_ACTIONS.get(action_type)
        if endpoint is not None:
            return endpoint
        requested = raw_action_type or action_type
        if action_type in _UNSAFE_PAYLOAD_ACTIONS:
            # 措辞刻意与"尚未实现"区分开：这些不是待办项，而是本执行路径不支持的
            # 能力。若写成"还没实现"，会读成"以后会有"。
            raise StepExecutionRefused(
                "action_not_supported",
                f"动作 {requested!r} 属于载荷投放/攻击类能力（注册表中 risk_level=10），"
                f"本执行路径不提供该能力，也不存在对应端点。这不是「尚未实现」，"
                f"不应被理解为后续会开放。",
                detail={
                    "action_type": action_type,
                    "requested_action_type": requested,
                    "unsafe_payload_actions": sorted(_UNSAFE_PAYLOAD_ACTIONS),
                },
            )
        if action_type in KNOWN_UNSUPPORTED_ACTIONS:
            raise StepExecutionRefused(
                "action_endpoint_not_implemented",
                f"动作 {requested!r} 已在策略注册表中声明，但 Runtime 还没有对应端点，"
                f"无法真实执行。拒绝执行而不是静默跳过 —— 静默跳过会产生"
                f"「计划显示完成但什么都没发生」的假成功。",
                detail={
                    "action_type": action_type,
                    "requested_action_type": requested,
                    "implemented": sorted(IMPLEMENTED_ACTIONS),
                },
            )
        raise StepExecutionRefused(
            "unknown_action_type",
            f"未知动作 {requested!r}，既不在已实现列表中，也不在注册表已声明的动作里。",
            detail={
                "action_type": action_type,
                "requested_action_type": requested,
                "implemented": sorted(IMPLEMENTED_ACTIONS),
            },
        )

    @staticmethod
    def _require_target(node_id: str, action_type: str, step: Any) -> None:
        if node_id:
            return
        raise StepExecutionRefused(
            "step_target_vehicle_missing",
            f"步骤 {getattr(step, 'step_id', '?')!r}（{action_type}）没有指定 node_id。"
            f"系统不会猜测目标载具 —— 猜错等于飞错飞机。",
            detail={"step_id": str(getattr(step, "step_id", ""))},
        )
