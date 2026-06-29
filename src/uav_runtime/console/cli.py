"""Command-line entry points for demo, tests, and operator-facing diagnostics.

给新同学的阅读提示：
- CLI 是最容易上手的入口：先跑 list-capabilities / check-backend / submit-action。
- CLI 不绕过 RuntimeOrchestrator；submit-action 仍会经过 Policy Gate 和 audit/replay。
- list-capabilities 是只读 registry visibility，不执行任何动作，也不连接硬件。
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from uav_runtime.policy.action_registry import capability_manifest
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend
from uav_runtime.runtime.adapter_selection import DEFAULT_ADAPTER_NAME
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator
from uav_runtime.runtime.replay import replay_last

PAYLOAD_ACTIONS = {
    "camera_capture",
    "gimbal_set_angle",
    "speaker_play_message",
    "light_set_state",
    "sensor_read",
    "health_query",
}
# CLI 用这个集合给 payload adapter 的动作选择 skill_group="payload"。
# 真实策略仍由 Policy Gate 决定，不能把这里当作安全白名单。


def _print_output(payload: object, pretty: bool = False) -> None:
    # 所有 CLI 输出保持 JSON，便于脚本、演示页面和人工检查复用。
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def _add_pretty_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output for demo readability")


def build_parser() -> argparse.ArgumentParser:
    # argparse parser 是 CLI contract 的中心。新增命令时请同步 tests/test_cli.py。
    p = argparse.ArgumentParser(prog="uav-runtime")
    _add_pretty_arg(p)

    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("submit-mission")
    _add_pretty_arg(m)
    m.add_argument("--mission-id", default="mission-demo")
    m.add_argument("--adapter", default=DEFAULT_ADAPTER_NAME)
    m.add_argument("--backend-mode", choices=["stub", "sitl"], default="stub")
    m.add_argument("--backend-enabled", action="store_true")
    m.add_argument("--transport-endpoint", default="")
    m.add_argument("--connect-timeout-ms", type=int, default=3000)
    m.add_argument("--timeout-ms", type=int, default=3000)
    m.add_argument("--retry-count", type=int, default=0)

    s = sub.add_parser("submit-action")
    _add_pretty_arg(s)
    s.add_argument("action")
    s.add_argument("--mission-id", default="mission-demo")
    s.add_argument("--adapter", default=DEFAULT_ADAPTER_NAME)
    s.add_argument("--backend-mode", choices=["stub", "sitl"], default="stub")
    s.add_argument("--backend-enabled", action="store_true")
    s.add_argument("--transport-endpoint", default="")
    s.add_argument("--connect-timeout-ms", type=int, default=3000)
    s.add_argument("--timeout-ms", type=int, default=3000)
    s.add_argument("--retry-count", type=int, default=0)
    s.add_argument("--risk-hint", type=int, default=1)
    s.add_argument("--require-confirm", action="store_true")
    s.add_argument(
        "--demo-link-state",
        choices=["healthy", "degraded", "lost"],
        default="healthy",
        help="demo-only control-plane state input; consumed by runtime policy context builder",
    )

    show_status = sub.add_parser("show-status")
    _add_pretty_arg(show_status)

    show_audit = sub.add_parser("show-audit")
    _add_pretty_arg(show_audit)

    c = sub.add_parser("check-backend")
    _add_pretty_arg(c)
    c.add_argument("--backend", choices=["px4_sitl"], default="px4_sitl")
    c.add_argument("--backend-mode", choices=["stub", "sitl"], default="sitl")
    c.add_argument("--backend-enabled", action="store_true")
    c.add_argument("--transport-endpoint", default="")
    c.add_argument("--connect-timeout-ms", type=int, default=3000)
    c.add_argument("--timeout-ms", type=int, default=3000)
    c.add_argument("--retry-count", type=int, default=0)

    caps = sub.add_parser("list-capabilities")
    _add_pretty_arg(caps)
    # Capability manifest filters are read-only inventory helpers.  They must not
    # trigger runtime execution or mutate policy/adapter state.
    caps.add_argument("--domain", choices=["flight", "payload", "system", "coordination"], default=None)
    caps.add_argument("--adapter", default=None)
    caps.add_argument("--fallback-only", action="store_true")
    caps.add_argument("--include-dangerous", action="store_true")

    r = sub.add_parser("replay-last")
    _add_pretty_arg(r)
    r.add_argument("--path", default="audit/runtime.audit.jsonl")
    r.add_argument("-n", type=int, default=5)

    return p


def _build_request_from_args(args: argparse.Namespace) -> ActionRequest:
    # Convert CLI flags into the protocol-level ActionRequest shape expected by runtime.
    # Keep this thin; avoid hiding policy logic in CLI helpers.
    if args.cmd == "submit-mission":
        return ActionRequest(
            action="submit_mission",
            params={"mission_id": args.mission_id, "demo_link_state": "healthy"},
            source=CommandSource.SELF_LOCAL,
            scope=AuthorityScope.SELF_ONLY,
            mission_id=args.mission_id,
            action_type="submit_mission",
            skill_group="coordination",
            target_set=["self"],
            risk_hint=1,
            priority_hint=50,
            requires_confirmation_hint=False,
        )

    selected_adapter = str(getattr(args, "adapter", DEFAULT_ADAPTER_NAME) or DEFAULT_ADAPTER_NAME)
    # Payload skeleton actions use skill_group="payload" so Policy Gate/profile can
    # reason about them separately from flight_core.
    skill_group = "payload" if selected_adapter == "payload" and args.action in PAYLOAD_ACTIONS else "flight_core"

    return ActionRequest(
        action=args.action,
        params={"demo_link_state": args.demo_link_state},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        mission_id=args.mission_id,
        action_type=args.action,
        skill_group=skill_group,
        target_set=["self"],
        risk_hint=args.risk_hint,
        priority_hint=50,
        requires_confirmation_hint=bool(args.require_confirm),
    )


def _attach_policy_snapshot(result: dict[str, Any], audit_path: str) -> dict[str, Any]:
    # For demo readability, attach the latest matching policy_decision_event beside
    # the result.  The authoritative record remains the audit JSONL file.
    request_id = result.get("request_id")
    if not request_id:
        return {"result": result}

    events = replay_last(audit_path, n=50)
    decision_event = next(
        (
            e
            for e in reversed(events)
            if e.get("type") == "policy_decision_event" and e.get("request_id") == request_id
        ),
        None,
    )

    if decision_event is None:
        return {"result": result}
    return {"result": result, "policy_decision_event": decision_event}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "list-capabilities":
        # Read-only fast path: do not instantiate RuntimeOrchestrator, do not create
        # audit files, and do not connect to PX4/payload hardware.
        out = {
            "capabilities": capability_manifest(
                domain=getattr(args, "domain", None),
                adapter=getattr(args, "adapter", None),
                fallback_only=bool(getattr(args, "fallback_only", False)),
                include_dangerous=bool(getattr(args, "include_dangerous", False)),
            )
        }
        _print_output(out, pretty=bool(getattr(args, "pretty", False)))
        return 0

    selected_adapter = str(getattr(args, "adapter", DEFAULT_ADAPTER_NAME) or DEFAULT_ADAPTER_NAME)
    mav_cfg = MavlinkBackendConfig(
        backend_mode=str(getattr(args, "backend_mode", "stub") or "stub"),
        backend_enabled=bool(getattr(args, "backend_enabled", False)),
        transport_endpoint=str(getattr(args, "transport_endpoint", "") or ""),
        connect_timeout_ms=int(getattr(args, "connect_timeout_ms", 3000) or 3000),
        timeout_ms=int(getattr(args, "timeout_ms", 3000) or 3000),
        retry_count=int(getattr(args, "retry_count", 0) or 0),
    )
    rt = RuntimeOrchestrator(adapter_name=selected_adapter, mavlink_backend_config=mav_cfg)

    if args.cmd in {"submit-mission", "submit-action"}:
        req = _build_request_from_args(args)
        result = rt.handle_action_request(req)
        out = _attach_policy_snapshot(result, str(rt.audit.path))
    elif args.cmd == "check-backend":
        session = MavlinkBackendSession.from_config(mav_cfg)
        backend = Px4SitlBackend(mav_cfg, session)
        out = backend.readiness_diagnostic()
    elif args.cmd == "replay-last":
        out = replay_last(args.path, n=args.n)
    else:
        out = {"ok": True, "cmd": args.cmd}

    _print_output(out, pretty=bool(getattr(args, "pretty", False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
