from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NanoGPTConfig:
    # Tokenizer
    vocab_size: int = 259  # default: byte-level (256 bytes + 3 specials)
    block_size: int = 256

    # Model size
    n_layer: int = 8
    n_head: int = 8
    n_embd: int = 512
    dropout: float = 0.0

    # FFN / MoE
    use_moe: bool = True
    moe_num_experts: int = 4
    moe_top_k: int = 2
    ffn_hidden_mult: float = 4.0

    # RoPE
    rope_base: int = 10000

    # Training
    bias: bool = False  # GPT-style often disables bias

    def head_dim(self) -> int:
        assert self.n_embd % self.n_head == 0
        return self.n_embd // self.n_head
