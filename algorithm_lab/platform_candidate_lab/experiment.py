"""One synthetic UAV-02 request against an already running local model.

The report is an offline inference observation, not a flight or autonomy result.
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path
from time import perf_counter

from .candidate import decide
from .contracts import utc_now
from .local_model import LocalInferenceClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-url", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-ms", type=int, default=10_000)
    args = parser.parse_args()
    fixture = Path(__file__).parent / "fixtures" / "uav02_hold_request.json"
    request = json.loads(fixture.read_text(encoding="utf-8"))
    moment = utc_now()
    request["observation"]["sample_timestamp"] = moment.isoformat().replace("+00:00", "Z")
    request["authorization"]["expires_at"] = (
        moment + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    request["decision_timeout_ms"] = args.timeout_ms
    client = LocalInferenceClient(args.model_url, args.model_id)
    started = perf_counter()
    result = decide(request, client, allow_fake=True)
    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    record = {
        "experiment_kind": "synthetic_offline_model_candidate",
        "flight_executed": False,
        "source": "fake",
        "input": request,
        "result": result,
        "elapsed_ms": elapsed_ms,
    }
    # Preserve an immutable record under an ignored D: artifacts directory.
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(record, target, ensure_ascii=False, sort_keys=True, indent=2,
                  allow_nan=False)
        target.write("\n")
    print(json.dumps({"status": result["status"], "decision": result["decision"],
                      "failure_reason_code": result["failure_reason_code"],
                      "elapsed_ms": elapsed_ms, "output": str(args.output)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
