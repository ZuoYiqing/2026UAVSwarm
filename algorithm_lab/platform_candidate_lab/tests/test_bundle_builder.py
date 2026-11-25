"""Small offline checks for the bundle builder; never copy or load a model."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from platform_candidate_lab.scripts import build_compact_cpu_bundle as builder


class BundleBuilderTests(unittest.TestCase):
    def test_hash_check_accepts_exact_bytes_and_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.bin"
            path.write_bytes(b"fixed-offline-artifact")
            expected = hashlib.sha256(b"fixed-offline-artifact").hexdigest()
            builder.require_hash(path, expected)
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "asset hash mismatch"):
                builder.require_hash(path, expected)

    def test_fixed_source_and_production_command_boundary(self):
        self.assertIn("model_view.py", builder.SOURCE_FILES)
        self.assertEqual(builder.SOURCE_COMMIT,
                         "735af7485a5d953bdea2e48c8d634e256d325af5")
        readme = builder.bundle_readme()
        self.assertIn("must **omit --allow-fake**", readme)
        self.assertIn("original 2026-10-24", readme)
        self.assertIn("ctx512 token budget", readme)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = builder.DESTINATION
            try:
                builder.DESTINATION = Path(temporary)
                with self.assertRaises(FileExistsError):
                    builder.build()
            finally:
                builder.DESTINATION = original


if __name__ == "__main__":
    unittest.main()
