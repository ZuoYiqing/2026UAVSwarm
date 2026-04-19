"""CLI 命令骨架（submit-mission / submit-action / show-status / show-audit / replay-last）。"""
from __future__ import annotations

import argparse
import json
from typing import Any

from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.runtime.adapter_selection import DEFAULT_ADAPTER_NAME
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator
from uav_runtime.runtime.replay import replay_last


def _print_output(payload: object, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def _add_pretty_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output for demo readability")


def build_parser() -> argparse.ArgumentParser:
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

    r = sub.add_parser("replay-last")
    _add_pretty_arg(r)
    r.add_argument("--path", default="audit/runtime.audit.jsonl")
    r.add_argument("-n", type=int, default=5)

    return p


def _build_request_from_args(args: argparse.Namespace) -> ActionRequest:
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

    return ActionRequest(
        action=args.action,
        params={"demo_link_state": args.demo_link_state},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        mission_id=args.mission_id,
        action_type=args.action,
        skill_group="flight_core",
        target_set=["self"],
        risk_hint=args.risk_hint,
        priority_hint=50,
        requires_confirmation_hint=bool(args.require_confirm),
    )


def _attach_policy_snapshot(result: dict[str, Any], audit_path: str) -> dict[str, Any]:
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
    selected_adapter = str(getattr(args, "adapter", DEFAULT_ADAPTER_NAME) or DEFAULT_ADAPTER_NAME)
    mav_cfg = MavlinkBackendConfig(
        backend_mode=str(getattr(args, "backend_mode", "stub") or "stub"),
        backend_enabled=bool(getattr(args, "backend_enabled", False)),
        transport_endpoint=str(getattr(args, "transport_endpoint", "") or ""),
        timeout_ms=int(getattr(args, "timeout_ms", 3000) or 3000),
        retry_count=int(getattr(args, "retry_count", 0) or 0),
    )
    rt = RuntimeOrchestrator(adapter_name=selected_adapter, mavlink_backend_config=mav_cfg)

    if args.cmd in {"submit-mission", "submit-action"}:
        req = _build_request_from_args(args)
        result = rt.handle_action_request(req)
        out = _attach_policy_snapshot(result, str(rt.audit.path))
    elif args.cmd == "replay-last":
        out = replay_last(args.path, n=args.n)
    else:
        out = {"ok": True, "cmd": args.cmd}

    _print_output(out, pretty=bool(getattr(args, "pretty", False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
