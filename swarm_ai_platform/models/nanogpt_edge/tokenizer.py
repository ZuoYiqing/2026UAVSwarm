from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ByteTokenizer:
    """A tiny byte-level tokenizer.

    - ids 0..255: raw bytes
    - 256: <BOS>
    - 257: <EOS>
    - 258: <PAD>

    This is dependency-light and sufficient for the course project.
    If you need better quality, replace with a BPE tokenizer via `tokenizers`.
    """

    BOS: int = 256
    EOS: int = 257
    PAD: int = 258

    def vocab_size(self) -> int:
        return 259

    def encode(self, text: str, add_bos: bool = False, add_eos: bool = False) -> list[int]:
        b = text.encode("utf-8", errors="ignore")
        ids = list(b)
        if add_bos:
            ids = [self.BOS] + ids
        if add_eos:
            ids = ids + [self.EOS]
        return ids

    def decode(self, ids: list[int]) -> str:
        # Strip special tokens
        raw = bytes([i for i in ids if 0 <= i <= 255])
        return raw.decode("utf-8", errors="ignore")
