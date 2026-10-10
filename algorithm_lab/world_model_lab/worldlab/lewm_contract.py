"""Strict, file-only contract for the official PushT checkpoint load smoke."""
import json
from pathlib import Path
from .contracts import number
from .offline import file_hash

SOURCE_REVISION = "8edfeb336732b5f3ce7b8b210d0ba370a09e2cac"
MODEL_REVISION = "22b330c28c27ead4bfd1888615af1340e3fe9052"
ASSETS = {
    "model/weights.pt": "48938400ae3464c9680731287f583a9cb516f55a8ec64ea13a91be47fb15b607",
    "model/config.json": "2564086e961e7b5c7c04dffc451091115b389a590645ff19653c64fd0bc16e09",
    "vendor/le-wm/jepa.py": "9cd5914da775926ff925f0ed6d06f745c0bb9be500919d7a2158913bec1334a9",
    "vendor/le-wm/module.py": "262ade4a34589dd2cdf3d04c63189ce90694662b8c59c3605a8ee433be29d1e1",
    "vendor/le-wm/LICENSE": "0e66685ed351839b0baf614c4207aa2c5e6ab9dbe419aac9c38d0998a000200c",
}


def checked_assets(root):
    root = Path(root).resolve()
    for relative, expected in ASSETS.items():
        path = root / relative
        if not path.is_file() or path.is_symlink() or file_hash(path) != expected:
            raise ValueError(f"ASSET_INTEGRITY_FAILED:{relative}")
    return root


def checked_request(path):
    path = Path(path).resolve()
    request = json.loads(path.read_text(encoding="utf-8"))
    fields = {"contract_version", "fixture_kind", "images", "normalized_action_blocks"}
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError("VISUAL_REQUEST_FIELDS_INVALID")
    if request["contract_version"] != "lewm_pusht_load_smoke_v0.1":
        raise ValueError("VISUAL_CONTRACT_UNSUPPORTED")
    if request["fixture_kind"] != "synthetic_rgb_io_smoke":
        raise ValueError("FIXTURE_SCOPE_UNSUPPORTED")
    if not isinstance(request["images"], list) or len(request["images"]) != 3:
        raise ValueError("THREE_RGB_FRAMES_REQUIRED")
    images = []
    for relative in request["images"]:
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError("IMAGE_PATH_INVALID")
        image = (path.parent / relative).resolve()
        if not image.is_relative_to(path.parent) or not image.is_file():
            raise ValueError("IMAGE_PATH_ESCAPE_OR_MISSING")
        if image.stat().st_size > 2_000_000:
            raise ValueError("IMAGE_FILE_TOO_LARGE")
        images.append(image)
    actions = request["normalized_action_blocks"]
    if not isinstance(actions, list) or len(actions) != 3:
        raise ValueError("THREE_ACTION_BLOCKS_REQUIRED")
    for block in actions:
        if not isinstance(block, list) or len(block) != 10:
            raise ValueError("PUSHT_ACTION_DIMENSION_INVALID")
        for value in block:
            number(value, "normalized_action", 3)
    return request, images
