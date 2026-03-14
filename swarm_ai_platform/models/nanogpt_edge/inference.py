from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import torch

from swarm_ai_platform.models.nanogpt_edge.config import NanoGPTConfig
from swarm_ai_platform.models.nanogpt_edge.model import NanoGPT
from swarm_ai_platform.models.nanogpt_edge.tokenizer import ByteTokenizer


@dataclass
class LoadedModel:
    model: NanoGPT
    tokenizer: ByteTokenizer


def load_model(ckpt_path: str | Path, device: str | None = None) -> LoadedModel:
    ckpt_path = Path(ckpt_path)
    ckpt = torch.load(ckpt_path, map_location="cpu")
    cfg = NanoGPTConfig(**ckpt.get("config", {}))
    tok = ByteTokenizer()
    cfg.vocab_size = tok.vocab_size()

    model = NanoGPT(cfg)
    model.load_state_dict(ckpt.get("model", {}), strict=False)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    return LoadedModel(model=model, tokenizer=tok)


def generate_text(loaded: LoadedModel, prompt: str, max_new_tokens: int = 200, temperature: float = 1.0, top_k: Optional[int] = 50) -> str:
    device = next(loaded.model.parameters()).device
    ids = loaded.tokenizer.encode(prompt, add_bos=True)
    x = torch.tensor(ids, dtype=torch.long, device=device).unsqueeze(0)
    y = loaded.model.generate(x, max_new_tokens=max_new_tokens, temperature=temperature, top_k=top_k)
    out = loaded.tokenizer.decode(y[0].tolist())
    return out


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", type=str, default="checkpoints/nanogpt_edge/ckpt_final.pt")
    p.add_argument("--prompt", type=str, default="Once upon a time")
    p.add_argument("--max_new_tokens", type=int, default=120)
    args = p.parse_args()

    loaded = load_model(args.ckpt)
    out = generate_text(loaded, args.prompt, max_new_tokens=args.max_new_tokens)
    print(out)


if __name__ == "__main__":
    main()
