"""Adapter Gateway: convert approved ActionRequest into adapter commands.

给新同学的阅读提示：
- RuntimeOrchestrator 只有在 Policy Gate ALLOW 后才会调用这里。
- Gateway 是“通用执行入口”，负责把协议层 ActionRequest 转成 adapter.execute(command)。
- Adapter 不应直接拿原始 request 做策略判断；策略边界在 policy 层，执行边界在 adapter 层。
- 这里仍是 skeleton：参数裁剪、限速、幂等窗口后续可逐步增强。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from uav_runtime.protocol.schema import ActionRequest


@dataclass(slots=True)
class AdapterGateway:
    adapters: dict[str, object] = field(default_factory=dict)
    _idempotency_seen: set[str] = field(default_factory=set)

    def register(self, adapter: object) -> None:
        # Adapter 只需要暴露 name 和 execute(command)；gateway 不关心硬件细节。
        self.adapters[getattr(adapter, "name")] = adapter

    def to_execution_intent(self, request: ActionRequest) -> dict[str, Any]:
        # intent 是 adapter 前的中间形态，便于未来做参数裁剪、限速、审计和映射。
        return {
            "request_id": request.request_id,
            "action_type": request.action_type,
            "skill_group": request.skill_group,
            "target_set": request.target_set,
            "risk_hint": request.risk_hint,
            "priority_hint": request.priority_hint,
            "params": request.params,
        }

    def _sanitize_params(self, intent: dict[str, Any]) -> dict[str, Any]:
        # TODO: 参数裁剪（range clamp / forbidden params stripping）
        return intent

    def _apply_rate_limit(self, intent: dict[str, Any]) -> tuple[bool, str | None]:
        # TODO: 限速（token bucket / per-skill cooldown）
        return True, None

    def _check_idempotency(self, request: ActionRequest) -> tuple[bool, str | None]:
        # TODO: 幂等检查（request_id + idempotency_key window）
        key = request.idempotency_key
        if not key:
            return True, None
        if key in self._idempotency_seen:
            return False, "duplicate_idempotency_key"
        self._idempotency_seen.add(key)
        return True, None

    def _build_adapter_command(self, intent: dict[str, Any]) -> dict[str, Any]:
        # TODO: adapter command 构造（per-adapter mapping table）
        # 当前把 action_type 放入 command，把 params 放入 arguments，保持 fake/mavlink/payload 路径一致。
        params = dict(intent.get("params") or {})
        sim: dict[str, Any] = {}
        if "__simulate_fail" in params:
            sim["fail"] = bool(params.pop("__simulate_fail"))
        if "__simulate_timeout" in params:
            sim["timeout"] = bool(params.pop("__simulate_timeout"))
        if "__simulate_delay_ms" in params:
            sim["delay_ms"] = int(params.pop("__simulate_delay_ms") or 0)

        command = {"command": intent["action_type"], "arguments": params, "meta": intent}
        if sim:
            command["_simulate"] = sim
        return command

    def _dispatch_command(self, adapter: object, command: dict[str, Any]) -> dict[str, Any]:
        # v0.1 baseline: adapter.execute(command)（command 由 gateway 统一构造）
        try:
            return adapter.execute(command)
        except Exception:
            # fake/stub fallback path. 真实 adapter 接入时应尽量返回结构化错误，
            # 不应依赖这里吞异常；这个分支主要保护 demo/test skeleton。
            return {
                "accepted": True,
                "detail": "simulated",
                "adapter": getattr(adapter, "name", "unknown"),
                "command": command,
            }

    def _normalize_result(self, raw: dict[str, Any], request: ActionRequest) -> dict[str, Any]:
        # TODO: 返回值标准化（canonical action_result contract）
        # 这里保证不同 adapter 的 raw result 至少收敛成统一字段，便于 CLI/audit/replay 读取。
        accepted = bool(raw.get("accepted"))
        detail = str(raw.get("detail", ""))
        code = str(raw.get("code", detail))
        message = str(raw.get("message", detail))
        return {
            "request_id": request.request_id,
            "status": "accepted" if accepted else "rejected",
            "code": code,
            "message": message,
            "accepted": accepted,
            "detail": detail,
            "adapter": raw.get("adapter", ""),
            "evidence_ref": raw.get("evidence_ref"),
            "execution_trace": raw.get("execution_trace"),
        }

    def execute(self, adapter_name: str, request: ActionRequest) -> dict[str, Any]:
        # execute 的输入必须已经通过 Policy Gate；不要在这里新增“策略拒绝”。
        adapter = self.adapters.get(adapter_name)
        if adapter is None:
            return {
                "request_id": request.request_id,
                "status": "rejected",
                "code": "adapter_not_found",
                "message": f"adapter_not_found:{adapter_name}",
                "accepted": False,
                "detail": f"adapter_not_found:{adapter_name}",
                "adapter": adapter_name,
            }

        ok, reason = self._check_idempotency(request)
        if not ok:
            return {
                "request_id": request.request_id,
                "status": "rejected",
                "code": reason,
                "message": reason,
                "accepted": False,
                "detail": reason,
                "adapter": adapter_name,
            }

        intent = self.to_execution_intent(request)
        intent = self._sanitize_params(intent)
        allowed, rate_reason = self._apply_rate_limit(intent)
        if not allowed:
            return {
                "request_id": request.request_id,
                "status": "rejected",
                "code": rate_reason or "rate_limited",
                "message": rate_reason or "rate_limited",
                "accepted": False,
                "detail": rate_reason or "rate_limited",
                "adapter": adapter_name,
            }

        command = self._build_adapter_command(intent)
        raw = self._dispatch_command(adapter, command)
        return self._normalize_result(raw, request)
