from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Tuple

import torch

from swarm_ai_platform.models.nanogpt_edge.tokenizer import ByteTokenizer


@dataclass
class DatasetTensors:
    train: torch.Tensor
    val: torch.Tensor


def load_text_corpus(path: str | Path, tokenizer: ByteTokenizer) -> DatasetTensors:
    """Load a plain text corpus and return token tensors.

    The corpus will be encoded as UTF-8 bytes. This is a simple baseline.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    ids = tokenizer.encode(text)
    data = torch.tensor(ids, dtype=torch.long)

    # split 90/10
    n = int(0.9 * len(data))
    train = data[:n]
    val = data[n:]
    return DatasetTensors(train=train, val=val)


def try_download_tinystories(out_txt: str | Path) -> Path:
    """Download TinyStories via HuggingFace datasets (optional).

    Requires: `pip install datasets`
    """
    out_txt = Path(out_txt)
    out_txt.parent.mkdir(parents=True, exist_ok=True)

    try:
        from datasets import load_dataset  # type: ignore
    except Exception as e:
        raise RuntimeError("datasets is not installed. Install with: pip install datasets") from e

    ds = load_dataset("roneneldan/TinyStories")
    # Concatenate a manageable subset by default
    texts = []
    for split in ["train", "validation"]:
        for i, row in enumerate(ds[split]):
            texts.append(row.get("text", ""))
            if i >= 2000:  # keep it small for demo
                break
    out_txt.write_text("\n\n".join(texts), encoding="utf-8")
    return out_txt


def batch_iter(data: torch.Tensor, batch_size: int, block_size: int, *, device: str) -> Iterator[Tuple[torch.Tensor, torch.Tensor]]:
    """Yield batches for next-token prediction."""
    n = data.size(0)
    while True:
        ix = torch.randint(low=0, high=n - block_size - 1, size=(batch_size,))
        x = torch.stack([data[i : i + block_size] for i in ix])
        y = torch.stack([data[i + 1 : i + block_size + 1] for i in ix])
        yield x.to(device), y.to(device)
