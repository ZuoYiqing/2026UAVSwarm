"""Change only the model profile; reuse the immutable held-out evaluator."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import evaluate as frozen

FREEZE = "4596632544005ae7a7c2de993bd6b99e9af9c7cf"
CORPUS_LF_SHA256 = "d9196e2df7e4726ef68771e7047de2e21283b299df93e857e050e6c4fc350f54"
WEIGHTS_SHA256 = "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4"
PORT = 18116


def start_4b(args):
    if args.freeze_commit != FREEZE:
        raise ValueError("Use the original held-out freeze commit.")
    frozen.git("merge-base", "--is-ancestor", FREEZE, "HEAD")
    for item in (frozen.CASES, Path(frozen.__file__), Path(frozen.rules.__file__)):
        frozen.assert_frozen(item, FREEZE)
    frozen.git(
        "diff", "--exit-code", FREEZE, "--",
        "src/uav_runtime", "scenarios/simple_recon_v0_1", "config/vehicles.sitl.json",
    )
    raw = frozen.CASES.read_bytes()
    assert frozen.sha256(frozen.lf(raw)).hexdigest() == CORPUS_LF_SHA256
    deck = json.loads(raw)
    catalog = frozen.routes.VEHICLE_REGISTRY.scene["intent_catalog"]
    assert len(catalog["entries"]) == 7
    assert frozen.sha256(frozen.canonical(catalog)).hexdigest() == deck["catalog_sha256"]
    assert [row["target_id"] for row in frozen.routes.VEHICLE_REGISTRY.scene["targets"]] == ["target-001"]
    assert frozen.sha256(frozen.lf(Path(frozen.rules.__file__).read_bytes())).hexdigest() == deck["rules_sha256_lf"]
    assert len({row["objective"] for row in deck["cases"]}) == 20
    profile = dict(deck["model"], id="qwen3.5-4b-q4-lab", profile="qwen3.5-4b", weights_sha256=WEIGHTS_SHA256)
    assert (profile["seeds"], profile["temperature"], profile["context_tokens"], profile["max_tokens"]) == (
        [11, 29, 53], 0.2, 2048, 384,
    )
    launch = json.loads(args.launch_record.read_text(encoding="utf-8-sig"))
    assert launch["offline_flag"] is True and launch["startup_status"] == "ready"
    assert (launch["model_alias"], launch["model_profile"], launch["port"]) == (
        profile["id"], profile["profile"], PORT,
    )
    assert frozen.file_hash(launch["model"]) == WEIGHTS_SHA256
    command = launch["arguments"]
    assert "llama-b10964" in launch["executable"] and "--offline" in command
    for option, expected in (
        ("--host", "127.0.0.1"), ("--port", str(PORT)), ("--parallel", "1"),
        ("--ctx-size", str(profile["context_tokens"])), ("--reasoning", "off"), ("--gpu-layers", "all"),
    ):
        assert command[command.index(option) + 1] == expected
    client = frozen.LocalModelClient(
        f"http://127.0.0.1:{PORT}/v1", profile["id"], timeout_s=45, sampling_temperature=profile["temperature"],
    )
    # Only the in-memory identity for this run changes; cases.json and
    # evaluate.py (prompt, constraints and scoring) remain byte-for-byte fixed.
    return dict(deck, model=profile), catalog, client


if __name__ == "__main__":
    with patch.object(frozen, "start", start_4b):
        frozen.main()
