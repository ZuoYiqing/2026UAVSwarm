"""Check the exact PNG and raw RGB bytes offered to the offline reviewer."""

import json
import struct
import zlib
from copy import deepcopy
from hashlib import sha256

from tests.unit.test_target_001_capture_fixture import ROOT, replay_fixture


def decode_fixture_png(png, width, height):
    """Decode this fixture's non-interlaced, unfiltered RGB8 rows."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    header, data, end = [], [], []
    chunks = {b"IHDR": header, b"IDAT": data, b"IEND": end}
    offset = 8
    while offset < len(png):
        size, kind = struct.unpack_from(">I4s", png, offset)
        payload = png[offset + 8 : offset + size + 8]
        crc, = struct.unpack_from(">I", png, offset + size + 8)
        assert zlib.crc32(kind + payload) == crc
        chunks[kind].append(payload)
        offset += size + 12
    assert header == [struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)]
    assert end == [b""] and offset == len(png)
    stride = width * 3 + 1
    filtered = zlib.decompress(b"".join(data))
    assert len(filtered) == height * stride and not any(filtered[::stride])
    return b"".join(filtered[i + 1 : i + stride] for i in range(0, len(filtered), stride))


def test_synthetic_visible_marker_and_capture_binding():
    fixture_path = ROOT / "docs/simulation/fixtures/simple_recon_v0_1_target_001_visible_v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    base = json.loads((ROOT / fixture["capture_base"]["path"]).read_text(encoding="utf-8"))
    case = deepcopy(base)
    for section, updates in fixture["overrides"].items():
        case[section].update(updates)
    case["sample"].pop("synthetic_rows_rgb")
    assert fixture["evidence_origin"] == base["evidence_origin"] == "synthetic_test_fixture"
    assert fixture["execution_authorized"] is False
    assert case["arrival"]["runtime_run_id"] != base["arrival"]["runtime_run_id"]

    image = fixture["image"]
    png = (ROOT / image["png_path"]).read_bytes()
    assert sha256(png).hexdigest() == image["png_sha256"]
    width, height = image["width"], image["height"]
    raw = decode_fixture_png(png, width, height)
    assert len(raw) == image["raw_bytes"] == width * height * 3
    sample = case["sample"]
    assert (sample["width"], sample["height"], sample["encoding"]) == (width, height, image["encoding"])
    assert replay_fixture(case, sample, raw) == {
        "arrival": "arrived", "capture": "fixture_valid", "observation": "undetermined",
    }
    assert replay_fixture(base, sample, raw)["capture"] == "capture_context_mismatch"

    reference = fixture["reference_pixels"]
    disk = bytes(reference["marker_rgb"])
    background = bytes(reference["background_rgb"])
    cx, cy = reference["ellipse_center_px"]
    rx, ry = reference["ellipse_radii_px"]
    # This tests the generated specimen, including all pixels outside the marker.
    # It is not a detector and is never run on a camera frame.
    for y in range(height):
        row = bytearray(background * width)
        if abs(y - cy) <= ry:
            for x in range(cx - rx, cx + rx + 1):
                if ((x - cx) * ry) ** 2 + ((y - cy) * rx) ** 2 <= (rx * ry) ** 2:
                    row[x * 3 : x * 3 + 3] = disk
        assert raw[y * width * 3 : (y + 1) * width * 3] == row
    assert reference["region"] == {"x": cx - rx, "y": cy - ry, "w": 2 * rx + 1, "h": 2 * ry + 1}
