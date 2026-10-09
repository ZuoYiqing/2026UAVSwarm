"""File-based CLI; never creates a server or flight connection."""
import argparse
import json
import time
from pathlib import Path
from .inference import load_model, predict
from .offline import bundle, guard, inventory, verify_bundle


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("--output", required=True)
    train.add_argument("--seed", type=int, default=11)
    train.add_argument("--epochs", type=int, default=40)
    train.add_argument("--probe-epochs", type=int, default=60)
    infer = sub.add_parser("infer")
    infer.add_argument("--model", required=True)
    infer.add_argument("--input", required=True)
    pack = sub.add_parser("bundle")
    pack.add_argument("--run", required=True)
    pack.add_argument("--output", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", required=True)
    sub.add_parser("inventory")
    args = parser.parse_args()
    try:
        if args.command == "train":
            if not 1 <= args.epochs <= 200 or not 1 <= args.probe_epochs <= 200:
                raise ValueError("EPOCH_BUDGET_INVALID")
            guard(2.0)
            from .experiment import run
            start = time.monotonic()
            def bounded_guard():
                guard(1.5)
                if time.monotonic() - start > 300:
                    raise RuntimeError("EXPERIMENT_TIME_BUDGET_EXCEEDED")
            run(args.output, args.seed, args.epochs, args.probe_epochs, bounded_guard)
            return 0
        if args.command == "infer":
            request = json.loads(Path(args.input).read_text(encoding="utf-8"))
            result = predict(load_model(args.model), request)
        elif args.command == "bundle":
            result = bundle(args.run, args.output)
        elif args.command == "verify":
            result = {"integrity_verified": True, "manifest": verify_bundle(args.bundle)}
        else:
            result = inventory()
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, RuntimeError, OSError, ImportError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc), "execution_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
