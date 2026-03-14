from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path

import torch

from swarm_ai_platform.models.nanogpt_edge.config import NanoGPTConfig
from swarm_ai_platform.models.nanogpt_edge.data import batch_iter, load_text_corpus, try_download_tinystories
from swarm_ai_platform.models.nanogpt_edge.model import NanoGPT
from swarm_ai_platform.models.nanogpt_edge.tokenizer import ByteTokenizer


def cosine_lr(step: int, total_steps: int, base_lr: float) -> float:
    if step >= total_steps:
        return 0.0
    return 0.5 * base_lr * (1 + math.cos(math.pi * step / total_steps))


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--out_dir", type=str, default="checkpoints/nanogpt_edge")
    p.add_argument("--data", type=str, default="data/tinystories_subset.txt")
    p.add_argument("--download_tinystories", action="store_true")
    p.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--batch_size", type=int, default=16)
    p.add_argument("--block_size", type=int, default=256)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--eval_every", type=int, default=200)
    p.add_argument("--save_every", type=int, default=500)
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tok = ByteTokenizer()
    if args.download_tinystories:
        try_download_tinystories(args.data)

    ds = load_text_corpus(args.data, tok)

    cfg = NanoGPTConfig(vocab_size=tok.vocab_size(), block_size=args.block_size)
    model = NanoGPT(cfg).to(args.device)
    print("Model params:", model.num_parameters())

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)

    train_it = batch_iter(ds.train, args.batch_size, args.block_size, device=args.device)
    val_it = batch_iter(ds.val, args.batch_size, args.block_size, device=args.device)

    for step in range(1, args.steps + 1):
        model.train()
        lr = cosine_lr(step, args.steps, args.lr)
        for g in opt.param_groups:
            g["lr"] = lr

        x, y = next(train_it)
        _, loss = model(x, y)
        assert loss is not None

        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()

        if step % 50 == 0:
            print(f"step={step} lr={lr:.2e} train_loss={loss.item():.4f}")

        if step % args.eval_every == 0:
            model.eval()
            with torch.no_grad():
                vx, vy = next(val_it)
                _, vloss = model(vx, vy)
            print(f"[eval] step={step} val_loss={vloss.item():.4f}")

        if step % args.save_every == 0:
            ckpt = {
                "config": asdict(cfg),
                "model": model.state_dict(),
                "step": step,
            }
            path = out_dir / f"ckpt_step{step}.pt"
            torch.save(ckpt, path)
            print("saved", path)

    # Final save
    ckpt = {"config": asdict(cfg), "model": model.state_dict(), "step": args.steps}
    path = out_dir / "ckpt_final.pt"
    torch.save(ckpt, path)
    print("saved", path)


if __name__ == "__main__":
    main()
