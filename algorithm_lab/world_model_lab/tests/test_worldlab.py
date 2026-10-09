import copy
import json
import tempfile
import unittest
from pathlib import Path

from worldlab.contracts import digest, features, integrate, validate
from worldlab.inference import SHAPES, load_model, predict
from worldlab.offline import compare_golden, file_hash, verify_bundle
from worldlab.simulation import dataset, request_for


def empty_model():
    model = {"format": "tiny_state_jepa_v0.1", "dt_s": 0.1}
    for name, sizes in SHAPES.items():
        model[name] = [{"weight": [[0.0] * ni for _ in range(no)], "bias": [0.0] * no}
                       for ni, no in zip(sizes[:-1], sizes[1:])]
    return model


class ContractsTests(unittest.TestCase):
    def setUp(self):
        self.request = request_for(dataset(101, 1)[0][0])

    def test_valid(self):
        states, actions, future = validate(self.request)
        self.assertEqual((len(states), len(actions), len(future)), (8, 7, 10))
        self.assertEqual(len(features(states, actions)), 69)

    def test_bad_requests_fail_closed(self):
        changes = [("coordinate_frame", "vehicle_local_ned"), ("coordinate_frame", "enu"),
                   ("node_id", ""), ("scene_id", " "), ("map_version", ""), ("dt_s", 0.2),
                   ("snapshot_age_s", 0.51), ("snapshot_age_s", -0.1), ("snapshot_age_s", True),
                   ("candidate_acceleration_ned_mps2", []), ("action_history", []),
                   ("state_history", []), ("contract_version", "unknown")]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                request = copy.deepcopy(self.request)
                request[key] = value
                with self.assertRaises(ValueError):
                    validate(request)

    def test_nonfinite_bool_and_bad_vectors(self):
        for vector in ([float("nan"), 0, 0], [float("inf"), 0, 0], [True, 0, 0], [5, 0, 0], [0, 0]):
            request = copy.deepcopy(self.request)
            request["candidate_acceleration_ned_mps2"][0] = vector
            with self.assertRaises(ValueError):
                validate(request)

    def test_timing_and_extra_fields(self):
        request = copy.deepcopy(self.request)
        request["state_history"][3]["t_s"] += 0.01
        with self.assertRaises(ValueError):
            validate(request)
        request = dict(self.request, execution_authorized=True)
        with self.assertRaises(ValueError):
            validate(request)

    def test_ned_sign_and_translation(self):
        result = integrate([0.0] * 6, [0, 0, -1])
        self.assertLess(result[2], 0)
        states, actions, _ = validate(self.request)
        moved = [[s[i] + 100 if i < 3 else s[i] for i in range(6)] for s in states]
        for a, b in zip(features(states, actions), features(moved, actions)):
            self.assertAlmostEqual(a, b)

    def test_prediction_is_not_authorization(self):
        a = predict(empty_model(), self.request)
        b = predict(empty_model(), self.request)
        self.assertEqual(digest(a), digest(b))
        self.assertFalse(a["execution_authorized"])
        self.assertFalse(a["safety_verified"])
        self.assertEqual(len(a["predictions"]), 10)

    def test_dataset_group_split(self):
        first, domains = dataset(101, 2)
        second, other = dataset(202, 2)
        self.assertEqual(digest(first), digest(dataset(101, 2)[0]))
        self.assertTrue({d["domain_id"] for d in domains}.isdisjoint({d["domain_id"] for d in other}))
        self.assertEqual(len(first), 14)
        self.assertNotEqual(digest(first), digest(second))

    def test_model_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.json"
            path.write_text(json.dumps(empty_model()), encoding="utf-8")
            self.assertEqual(load_model(path), empty_model())
            bad = empty_model()
            bad["encoder"][0]["weight"][0].pop()
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_model(path)

    def test_golden_rounding_not_semantic_changes(self):
        expected = predict(empty_model(), self.request)
        actual = copy.deepcopy(expected)
        actual["predictions"][0]["position_ned_m"][0] += 1e-6
        self.assertLess(compare_golden(actual, expected), 1e-5)
        actual["execution_authorized"] = True
        with self.assertRaises(ValueError):
            compare_golden(actual, expected)
        actual = copy.deepcopy(expected)
        actual["predictions"][0]["position_ned_m"][0] += 1e-3
        with self.assertRaises(ValueError):
            compare_golden(actual, expected)

    def test_bundle_hash_and_path_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = root / "model.json"
            model.write_text("{}", encoding="utf-8")
            manifest = {"format": "worldlab_bundle_v0.1", "files": {"model.json": file_hash(model)}}
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            verify_bundle(root)
            model.write_text("tampered", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_bundle(root)
            manifest["files"] = {"../outside": "0" * 64}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_bundle(root)


if __name__ == "__main__":
    unittest.main()
