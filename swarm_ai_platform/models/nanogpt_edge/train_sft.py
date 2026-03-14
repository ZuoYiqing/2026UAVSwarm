from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import List, Tuple

import torch

from swarm_ai_platform.models.nanogpt_edge.config import NanoGPTConfig
from swarm_ai_platform.models.nanogpt_edge.model import NanoGPT
from swarm_ai_platform.models.nanogpt_edge.tokenizer import ByteTokenizer


def cosine_lr(step: int, total_steps: int, base_lr: float) -> float:
    if step >= total_steps:
        return 0.0
    return 0.5 * base_lr * (1 + math.cos(math.pi * step / total_steps))


def format_alpaca(instruction: str, inp: str, output: str) -> Tuple[str, int]:
    """Return full text and the byte index where output starts."""
    parts = [
        "### Instruction:\n" + instruction.strip() + "\n\n",
        "### Input:\n" + (inp.strip() if inp is not None else "") + "\n\n",
        "### Output:\n",
    ]
    prefix = "".join(parts)
    full = prefix + output.strip() + "\n"
    return full, len(prefix.encode("utf-8", errors="ignore"))


def load_jsonl(path: str | Path) -> List[dict]:
    path = Path(path)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def build_sft_tensors(rows: List[dict], tok: ByteTokenizer, block_size: int) -> Tuple[torch.Tensor, torch.Tensor]:
    """Build (x, y) tensors for SFT.

    Labels for tokens before output start are set to -1 (ignored).
    """
    xs: List[List[int]] = []
    ys: List[List[int]] = []

    for r in rows:
        instruction = r.get("instruction", "")
        inp = r.get("input", "")
        output = r.get("output", "")
        full, out_start_byte = format_alpaca(instruction, inp, output)

        ids = tok.encode(full, add_bos=True, add_eos=True)
        if len(ids) < 2:
            continue

        # labels are next token ids
        x = ids[:-1]
        y = ids[1:]

        # Determine the token index corresponding to out_start_byte.
        # Since tokenization is byte-level, this is straightforward.
        # +1 for BOS token in front.
        out_start_token = 1 + out_start_byte

        # Ignore loss before output start
        y_masked = y.copy()
        for i in range(min(out_start_token, len(y_masked))):
            y_masked[i] = -1

        # Truncate/pad to block_size
        if len(x) > block_size:
            x = x[:block_size]
            y_masked = y_masked[:block_size]
        else:
            pad_len = block_size - len(x)
            x = x + [tok.PAD] * pad_len
            y_masked = y_masked + [-1] * pad_len

        xs.append(x)
        ys.append(y_masked)

    X = torch.tensor(xs, dtype=torch.long)
    Y = torch.tensor(ys, dtype=torch.long)
    return X, Y


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--base_ckpt", type=str, default="checkpoints/nanogpt_edge/ckpt_final.pt")
    p.add_argument("--sft_data", type=str, default="data/sft/demo_sft.jsonl")
    p.add_argument("--out_dir", type=str, default="checkpoints/nanogpt_edge_sft")
    p.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--steps", type=int, default=800)
    p.add_argument("--lr", type=float, default=5e-4)
    p.add_argument("--batch_size", type=int, default=8)
    p.add_argument("--block_size", type=int, default=256)
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tok = ByteTokenizer()
    rows = load_jsonl(args.sft_data)

    X, Y = build_sft_tensors(rows, tok, block_size=args.block_size)
    dataset = torch.utils.data.TensorDataset(X, Y)
    loader = torch.utils.data.DataLoader(dataset, batch_size=args.batch_size, shuffle=True)

    # Load base model
    ckpt = torch.load(args.base_ckpt, map_location="cpu")
    cfg = NanoGPTConfig(**ckpt["config"])
    cfg.block_size = args.block_size
    cfg.vocab_size = tok.vocab_size()

    model = NanoGPT(cfg)
    model.load_state_dict(ckpt["model"], strict=False)
    model.to(args.device)

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)

    step = 0
    while step < args.steps:
        for xb, yb in loader:
            step += 1
            model.train()
            lr = cosine_lr(step, args.steps, args.lr)
            for g in opt.param_groups:
                g["lr"] = lr

            xb = xb.to(args.device)
            yb = yb.to(args.device)
            _, loss = model(xb, yb)
            assert loss is not None

            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()

            if step % 50 == 0:
                print(f"step={step} lr={lr:.2e} sft_loss={loss.item():.4f}")

            if step % 200 == 0:
                ckpt_out = {"config": asdict(cfg), "model": model.state_dict(), "step": step}
                path = out_dir / f"ckpt_sft_step{step}.pt"
                torch.save(ckpt_out, path)
                print("saved", path)

            if step >= args.steps:
                break

    ckpt_out = {"config": asdict(cfg), "model": model.state_dict(), "step": args.steps}
    path = out_dir / "ckpt_sft_final.pt"
    torch.save(ckpt_out, path)
    print("saved", path)


if __name__ == "__main__":
    main()
