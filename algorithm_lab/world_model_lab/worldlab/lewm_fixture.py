"""Deterministic synthetic RGB inputs. No simulator or dataset is claimed."""
import json
import struct
import zlib
from pathlib import Path


def png_frame(index):
    width = 224
    pixels = bytearray([245] * (width * width * 3))
    def rectangle(left, top, right, bottom, color):
        for y in range(top, bottom):
            for x in range(left, right):
                offset = 3 * (y * width + x)
                pixels[offset:offset + 3] = bytes(color)
    rectangle(80, 85, 160, 105, (115, 115, 115))
    rectangle(110, 105, 130, 155, (115, 115, 115))
    rectangle(40 + index * 8, 160, 56 + index * 8, 176, (35, 95, 210))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + bytes(pixels[y * width * 3:(y + 1) * width * 3]) for y in range(width))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, width, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def create_fixture(output):
    output = Path(output)
    if output.exists():
        raise ValueError("FIXTURE_EXISTS_NO_OVERWRITE")
    output.mkdir(parents=True)
    for index in range(3):
        (output / f"frame{index}.png").write_bytes(png_frame(index))
    request = {"contract_version": "lewm_pusht_load_smoke_v0.1", "fixture_kind": "synthetic_rgb_io_smoke",
               "images": [f"frame{i}.png" for i in range(3)],
               "normalized_action_blocks": [[0.0] * 10 for _ in range(3)]}
    (output / "request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    return output / "request.json"
