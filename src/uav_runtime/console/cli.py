"""CLI 命令骨架（submit-mission / submit-action / show-status / show-audit / replay-last）。"""
from __future__ import annotations

import argparse
import json

from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator
from uav_runtime.runtime.replay import replay_last


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="uav-runtime")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("submit-mission")
    s = sub.add_parser("submit-action")
    s.add_argument("action")
    sub.add_parser("show-status")
    sub.add_parser("show-audit")
    sub.add_parser("replay-last")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rt = RuntimeOrchestrator()
    if args.cmd == "submit-action":
        req = ActionRequest(args.action, {}, CommandSource.SELF_LOCAL, AuthorityScope.SELF_ONLY)
        out = rt.handle_action_request(req)
    elif args.cmd == "replay-last":
        out = replay_last("audit/runtime.audit.jsonl", n=5)
    else:
        out = {"ok": True, "cmd": args.cmd}
    print(json.dumps(out, ensure_ascii=False))
    return 0
