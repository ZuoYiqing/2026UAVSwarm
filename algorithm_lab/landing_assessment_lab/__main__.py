"""Run the offline assessor on one JSON request."""

import argparse
import json
from pathlib import Path

from .assessor import ContractError, assess


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        request = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = assess(request)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            with Path(args.output).open("x", encoding="utf-8") as stream:
                stream.write(payload)
        print(payload, end="")
        return 0
    except (ContractError, OSError, ValueError) as error:
        print(json.dumps({"status": "invalid_request", "reason": str(error), "execution_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
