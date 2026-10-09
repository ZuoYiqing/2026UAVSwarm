"""Run from a copied bundle. This is Python API blocking, not OS isolation."""
import json
import socket
import sys
from pathlib import Path


def deny_network(event, arguments):
    if event.startswith("socket."):
        raise RuntimeError("NETWORK_FORBIDDEN_BY_SELFTEST")


sys.addaudithook(deny_network)
try:
    socket.socket()
except RuntimeError as error:
    if str(error) != "NETWORK_FORBIDDEN_BY_SELFTEST":
        raise
else:
    raise RuntimeError("NETWORK_GUARD_INEFFECTIVE")
sys.dont_write_bytecode = True
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
from worldlab.inference import load_model, predict
from worldlab.offline import compare_golden, verify_bundle

verify_bundle(root)
model = load_model(root / "model.json")
request = json.loads((root / "example_request.json").read_text(encoding="utf-8"))
expected = json.loads((root / "golden_response.json").read_text(encoding="utf-8"))
result = predict(model, request)
maximum = compare_golden(result, expected)
if "torch" in sys.modules or "numpy" in sys.modules:
    raise RuntimeError("UNEXPECTED_INFERENCE_DEPENDENCY")
print(json.dumps({"integrity": "pass", "golden_prediction": "pass", "network_api_blocked": True,
                  "golden_max_abs_error": maximum, "golden_absolute_tolerance": 1e-5,
                  "os_network_isolation_tested": False, "third_party_inference_dependencies": [],
                  "execution_authorized": False}))
