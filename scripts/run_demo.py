from __future__ import annotations

import json

from uav_runtime.core.mission import Mission
from uav_runtime.core.runtime import Runtime
from uav_runtime.core.scene import Scene


def main() -> int:
    runtime = Runtime()
    res = runtime.run(Mission("demo", ["search"]), Scene((20, 20), 3, []))
    print(json.dumps(res.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
