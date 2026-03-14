from __future__ import annotations

from pathlib import Path

from swarm_ai_platform.models.nanogpt_edge.inference import generate_text, load_model
from swarm_ai_platform.rag.store import KBStore, format_context


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", type=str, default="checkpoints/nanogpt_edge_sft/ckpt_sft_final.pt")
    p.add_argument("--kb_dir", type=str, default="kb")
    p.add_argument("--query", type=str, default="TARGET_REPORT 字段")
    args = p.parse_args()

    kb = KBStore()
    kb.ingest_dir(args.kb_dir)
    ctx = format_context(kb.retrieve(args.query, top_k=4))

    prompt = f"你是一个协议助手。请参考以下资料回答问题。\n\n资料:\n{ctx}\n\n问题: {args.query}\n回答:"

    loaded = load_model(args.ckpt)
    out = generate_text(loaded, prompt, max_new_tokens=200, temperature=0.8, top_k=50)
    print(out)


if __name__ == "__main__":
    main()
