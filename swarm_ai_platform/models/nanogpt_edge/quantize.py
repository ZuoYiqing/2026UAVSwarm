from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import torch
import torch.nn as nn

from swarm_ai_platform.models.nanogpt_edge.config import NanoGPTConfig
from swarm_ai_platform.models.nanogpt_edge.model import NanoGPT


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", type=str, default="checkpoints/nanogpt_edge_sft/ckpt_sft_final.pt")
    p.add_argument("--out", type=str, default="checkpoints/nanogpt_edge_sft/ckpt_sft_int8.pt")
    args = p.parse_args()

    ckpt = torch.load(args.ckpt, map_location="cpu")
    cfg = NanoGPTConfig(**ckpt["config"])
    model = NanoGPT(cfg)
    model.load_state_dict(ckpt["model"], strict=False)
    model.eval()

    # Dynamic quantization (PTQ) for Linear layers
    qmodel = torch.quantization.quantize_dynamic(model, {nn.Linear}, dtype=torch.qint8)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    torch.save({"config": asdict(cfg), "quantized": True, "model": qmodel.state_dict()}, out_path)
    print("saved", out_path)


if __name__ == "__main__":
    main()
