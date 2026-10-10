"""Package pinned visual assets, minimal probe and optional Windows wheelhouse."""
import argparse
import json
import shutil
import sys
from importlib.metadata import distributions
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worldlab.lewm_contract import ASSETS, checked_assets
from worldlab.lewm_fixture import create_fixture
from worldlab.offline import file_hash, verify_bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--windows-wheelhouse", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    root = checked_assets(args.assets)
    requirements = None
    if args.windows_wheelhouse:
        # Never freeze an unrelated system environment into a deployment bundle.
        def normalized(name):
            return name.lower().replace("_", "-")
        installed = {normalized(d.metadata["Name"]): d.version for d in distributions()
                     if normalized(d.metadata["Name"]) not in {"pip", "setuptools"}}
        expected = {"torch": "2.6.0+cpu", "transformers": "4.40.2", "numpy": "1.26.4",
                    "pillow": "10.2.0", "einops": "0.8.0"}
        if any(installed.get(name) != value for name, value in expected.items()):
            raise ValueError("RUN_PACKAGER_WITH_ISOLATED_WINDOWS_CPU_ENVIRONMENT")
        available = {normalized(p.name.split("-")[0]) for p in (root / "wheelhouse").glob("*.whl")}
        if set(installed) - available:
            raise ValueError("ENVIRONMENT_HAS_PACKAGES_ABSENT_FROM_WHEELHOUSE")
        requirements = sorted(f"{name}=={value}" for name, value in installed.items())
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("BUNDLE_EXISTS_NO_OVERWRITE")
    output.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1]
    paths = ["worldlab/__init__.py", "worldlab/contracts.py", "worldlab/offline.py", "worldlab/inference.py",
             "worldlab/cli.py", "worldlab/lewm_contract.py", "worldlab/lewm.py", "worldlab/lewm_fixture.py",
             "scripts/lewm_offline_probe.py", "requirements-lewm-load.txt", "LEWM_OFFLINE.md",
             "EXPERIMENT_LEWM_20261009.md"]
    for relative in paths:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    for relative in [*ASSETS, "model/README.md"]:
        target = output / "assets" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    create_fixture(output / "examples")
    inference_completed = False
    if args.report:
        report_path = Path(args.report)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        inference_completed = (report.get("status") == "load_and_inference_pass"
                               and report.get("inference_completed") is True
                               and report.get("model_loaded") is True and report.get("assets") == ASSETS)
        shutil.copyfile(report_path, output / "source_probe_report.json")
    manifest = {"format": "worldlab_bundle_v0.1", "model_inference_validated_on_source": inference_completed,
                "target_board_verified": False, "execution_authorized": False,
                "python_minimum": "3.10", "network_isolation": "Python audit hook; OS isolation untested",
                "windows_wheels_included": args.windows_wheelhouse,
                "wheel_target": "Windows CPython 3.11 AMD64 CPU only" if args.windows_wheelhouse else None}
    if args.windows_wheelhouse:
        wheels = root / "wheelhouse"
        shutil.copytree(wheels, output / "wheelhouse")
        (output / "requirements-windows.lock.txt").write_text("\n".join(requirements) + "\n", encoding="utf-8")
    manifest["files"] = {p.relative_to(output).as_posix(): file_hash(p)
                         for p in sorted(output.rglob("*")) if p.is_file()}
    manifest["payload_bytes"] = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify_bundle(output)
    print(json.dumps({"bundle": str(output), "files": len(manifest["files"]),
                      "payload_bytes": manifest["payload_bytes"],
                      "model_inference_validated_on_source": inference_completed}, indent=2))


if __name__ == "__main__":
    main()
