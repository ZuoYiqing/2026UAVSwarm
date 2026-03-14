from __future__ import annotations

import argparse
import json

from .commands import cmd_health, cmd_plan, cmd_sim


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="uav-runtime")
    p.add_argument("command", choices=["health", "plan", "sim"])
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "health":
        out = cmd_health()
    elif args.command == "plan":
        out = cmd_plan()
    else:
        out = cmd_sim()
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
