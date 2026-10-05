#!/usr/bin/env python3
"""观察复核（L2）记录的命令行工具：新建 / 校验 / 列出。

为什么需要它：复核记录是本阶段 L2 的唯一产物，而它**必须可追溯**。
这里提供一条不依赖 Runtime、不依赖相机的路径 —— 因为 `CAPTURE` 端点尚未实现，
现在没有任何东西能自动产生 `capture_id`。

用法::

    # 新建一条复核记录（会校验；不合法则拒绝写入）
    python scripts/observe_review.py new \
        --task-id TASK-1 --target-id target-001 \
        --capture-id cap-0123456789abcdef \
        --image-ref sha256:<64 hex> \
        --width 1280 --height 960 --encoding RGB8 \
        --captured-at 2026-10-05T11:59:30Z \
        --vehicle-id UAV-01 --camera-id front_rgb \
        --criterion-version l2-criterion-v0.1 \
        --reviewer human:zyq \
        --outcome observed --note "目标位于画面中央偏右" \
        --out-dir artifacts/observations/reviews

    # 校验一份已有记录（被改动过的会被拒）
    python scripts/observe_review.py validate path/to/rev-....json

    # 列出一个目录下的记录
    python scripts/observe_review.py list artifacts/observations/reviews

⚠️ **这些记录目前不能当验收证据。** 没有 L1 端点时 `capture_id` 与图像哈希
都靠人工录入，校验器只能保证格式与哈希**自洽**，不能保证它们来自真实采集。
详见 ``docs/OBSERVE_review_record_spec_v0_1.md`` 第 5 节。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from uav_runtime.observation.review_record import (  # noqa: E402
    VALID_OUTCOMES,
    ReviewValidationError,
    build_review,
    read_review,
    record_sha256,
    validate_review,
    write_review,
)

DEFAULT_OUT_DIR = REPO_ROOT / "artifacts" / "observations" / "reviews"


def _cmd_new(args: argparse.Namespace) -> int:
    image = {
        "ref": args.image_ref,
        "sha256": args.image_ref.removeprefix("sha256:"),
        "width": args.width,
        "height": args.height,
        "encoding": args.encoding,
        "captured_at": args.captured_at,
        "vehicle_id": args.vehicle_id,
        "camera_id": args.camera_id,
    }
    try:
        record = build_review(
            task_id=args.task_id,
            target_id=args.target_id,
            capture_id=args.capture_id,
            image=image,
            criterion_version=args.criterion_version,
            reviewer=args.reviewer,
            reviewed_at=args.reviewed_at or _now(),
            outcome=args.outcome,
            region=_parse_region(args.region),
            note=args.note,
        )
    except ReviewValidationError as exc:
        print("❌ 记录不合法，未写入：", file=sys.stderr)
        _print_violations(exc.violations)
        return 1

    path = write_review(record, Path(args.out_dir))
    print("✅ 已写入")
    print(f"   review_id : {record['review_id']}")
    print(f"   sha256    : {record_sha256(record)}")
    print(f"   outcome   : {record['outcome']}   confidence: {record['confidence']!r}")
    print(f"   路径      : {path}")
    print()
    print("   ⚠️ 本记录不能当验收证据：capture_id 与图像哈希由人工录入，")
    print("      校验器只能保证格式与哈希自洽，不能证明它们来自真实采集。")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"❌ 文件不存在：{path}", file=sys.stderr)
        return 1
    try:
        record = validate_review(read_review(path))
    except ReviewValidationError as exc:
        print(f"❌ 不合法：{path}", file=sys.stderr)
        _print_violations(exc.violations)
        return 1
    except json.JSONDecodeError as exc:
        print(f"❌ 不是合法 JSON：{exc}", file=sys.stderr)
        return 1
    print(f"✅ 合法：{path}")
    print(f"   review_id : {record['review_id']}")
    print(f"   outcome   : {record['outcome']}")
    print(f"   reviewer  : {record['reviewer']}")

    # 文件名里的哈希与实际内容不符 → 记录被改动过。
    digest = record_sha256(record)
    if digest[:16] not in path.name:
        print()
        print("⚠️ 文件名里的内容哈希与实际内容不一致 —— 这份记录被改动过。")
        print(f"   文件名: {path.name}")
        print(f"   实际  : {digest[:16]}")
        return 2
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    if not directory.exists():
        print(f"目录不存在：{directory}")
        return 0
    files = sorted(directory.glob("*.json"))
    if not files:
        print(f"（{directory} 下没有记录）")
        return 0
    print(f"{len(files)} 份记录（{directory}）")
    print()
    print(f"  {'review_id':<22} {'outcome':<15} {'task':<10} {'reviewer':<16} 校验")
    valid = invalid = 0
    for path in files:
        try:
            record = validate_review(read_review(path))
        except (ReviewValidationError, json.JSONDecodeError) as exc:
            invalid += 1
            reason = "JSON 坏" if isinstance(exc, json.JSONDecodeError) else "不合法"
            print(f"  {path.stem[:22]:<22} {'':<15} {'':<10} {'':<16} ❌ {reason}")
            continue
        valid += 1
        intact = "✅" if record_sha256(record)[:16] in path.name else "⚠️改动过"
        print(
            f"  {record['review_id']:<22} {record['outcome']:<15} "
            f"{str(record.get('task_id'))[:10]:<10} {str(record.get('reviewer'))[:16]:<16} {intact}"
        )
    print()
    print(f"  合法 {valid} / 不合法 {invalid}")
    return 0 if invalid == 0 else 1


def _parse_region(raw: str | None) -> dict[str, int] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--region 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("--region 必须是对象，如 '{\"x\":512,\"y\":384,\"w\":256,\"h\":192}'")
    return {str(k): int(v) for k, v in parsed.items()}


def _print_violations(violations: list[dict]) -> None:
    for item in violations:
        code = item.get("code")
        field = item.get("field", "")
        print(f"   · [{code}] {field}", file=sys.stderr)
        hint = item.get("hint")
        if hint:
            print(f"     {hint}", file=sys.stderr)
        if "value" in item:
            print(f"     实际值: {item['value']!r}", file=sys.stderr)


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="观察复核（L2）记录工具。注意：本阶段的记录不能当验收证据。"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="新建一条复核记录")
    new.add_argument("--task-id", required=True)
    new.add_argument("--target-id", required=True)
    new.add_argument("--capture-id", required=True)
    new.add_argument("--image-ref", required=True, help="形如 sha256:<64 位小写十六进制>")
    new.add_argument("--width", type=int, required=True)
    new.add_argument("--height", type=int, required=True)
    new.add_argument("--encoding", default="RGB8")
    new.add_argument("--captured-at", required=True)
    new.add_argument("--vehicle-id", required=True)
    new.add_argument("--camera-id", default="front_rgb")
    new.add_argument("--criterion-version", required=True)
    new.add_argument("--reviewer", required=True, help="必须以 human: 开头（本阶段只接受人工复核）")
    new.add_argument("--reviewed-at", default=None, help="默认取当前时间")
    new.add_argument("--outcome", required=True, choices=list(VALID_OUTCOMES))
    new.add_argument("--region", default=None, help="图像区域 JSON，如 '{\"x\":512,\"y\":384,\"w\":256,\"h\":192}'")
    new.add_argument("--note", default=None, help="文字说明（not_observed / undetermined 必须给）")
    new.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    new.set_defaults(func=_cmd_new)

    validate = sub.add_parser("validate", help="校验一份记录")
    validate.add_argument("path")
    validate.set_defaults(func=_cmd_validate)

    listing = sub.add_parser("list", help="列出一个目录下的记录")
    listing.add_argument("directory", nargs="?", default=str(DEFAULT_OUT_DIR))
    listing.set_defaults(func=_cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
