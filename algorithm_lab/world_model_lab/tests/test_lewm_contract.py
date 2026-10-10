import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from worldlab.lewm_contract import checked_assets, checked_request
from worldlab.lewm_fixture import create_fixture, png_frame
from worldlab.offline import file_hash


class LeWMSmokeTests(unittest.TestCase):
    def test_fixture_determinism_and_rgb_header(self):
        self.assertEqual(png_frame(0), png_frame(0))
        self.assertNotEqual(png_frame(0), png_frame(1))
        self.assertEqual(png_frame(0)[:8], b"\x89PNG\r\n\x1a\n")

    def test_valid_and_bad_contracts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = create_fixture(Path(folder) / "fixture")
            request, images = checked_request(path)
            self.assertEqual(len(images), 3)
            for field, value in (("images", ["../outside.png"] * 3), ("images", ["frame0.png"]),
                                 ("normalized_action_blocks", [[0] * 2] * 3),
                                 ("normalized_action_blocks", [[float("nan")] * 10] * 3),
                                 ("normalized_action_blocks", [[True] * 10] * 3),
                                 ("fixture_kind", "real_drone")):
                with self.subTest(field=field, value=value):
                    bad = copy.deepcopy(request)
                    bad[field] = value
                    path.write_text(json.dumps(bad), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        checked_request(path)

    def test_fixture_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "fixture"
            create_fixture(output)
            with self.assertRaises(ValueError):
                create_fixture(output)

    def test_stream_hash_and_corrupt_asset_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            blob = b"visual-asset" * 110000
            path = root / "weights.pt"
            path.write_bytes(blob)
            expected = hashlib.sha256(blob).hexdigest()
            self.assertEqual(file_hash(path), expected)
            with patch("worldlab.lewm_contract.ASSETS", {"weights.pt": expected}):
                self.assertEqual(checked_assets(root), root.resolve())
                path.write_bytes(b"corrupted")
                with self.assertRaisesRegex(ValueError, "ASSET_INTEGRITY_FAILED"):
                    checked_assets(root)

    def test_memory_refusal_records_no_load(self):
        from scripts import lewm_offline_probe as probe
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "run"
            arguments = ["probe", "--assets", folder, "--output", str(output)]
            with patch("sys.argv", arguments), patch.object(probe, "checked_assets", return_value=Path(folder)), \
                 patch.object(probe, "guard", side_effect=RuntimeError("MEMORY_GUARD: test")), \
                 patch("builtins.print"):
                self.assertEqual(probe.main(), 2)
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["status"], "blocked")
            self.assertFalse(report["model_loaded"])
            self.assertFalse(report["inference_completed"])
            self.assertFalse(report["board_validated"])
