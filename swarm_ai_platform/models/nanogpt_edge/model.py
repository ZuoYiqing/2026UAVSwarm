from __future__ import annotations

import math
from dataclasses import asdict
from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from swarm_ai_platform.models.nanogpt_edge.config import NanoGPTConfig


class RMSNorm(nn.Module):
    """RMSNorm (root mean square layer norm) as used in LLaMA.

    Reference formula:
        y = x * (1/sqrt(mean(x^2) + eps)) * weight

    We omit bias for simplicity.
    """

    def __init__(self, dim: int, eps: float = 1e-6) -> None:
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [..., dim]
        norm = x.pow(2).mean(dim=-1, keepdim=True)
        x = x * torch.rsqrt(norm + self.eps)
        return x * self.weight


class RotaryEmbedding(nn.Module):
    """RoPE: Rotary Position Embedding.

    This module precomputes cos/sin tables up to `max_seq_len`.
    """

    def __init__(self, dim: int, max_seq_len: int, base: int = 10000) -> None:
        super().__init__()
        assert dim % 2 == 0, "RoPE dim must be even"
        inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2).float() / dim))
        t = torch.arange(max_seq_len, dtype=torch.float)
        freqs = torch.einsum("i,j->ij", t, inv_freq)  # [T, dim/2]
        # interleave to full dim
        emb = torch.cat([freqs, freqs], dim=-1)  # [T, dim]
        self.register_buffer("cos_cached", emb.cos(), persistent=False)
        self.register_buffer("sin_cached", emb.sin(), persistent=False)

    @staticmethod
    def _rotate_half(x: torch.Tensor) -> torch.Tensor:
        x1 = x[..., : x.shape[-1] // 2]
        x2 = x[..., x.shape[-1] // 2 :]
        return torch.cat([-x2, x1], dim=-1)

    def apply(self, x: torch.Tensor, seq_len: int) -> torch.Tensor:
        # x: [B, nh, T, hs]
        cos = self.cos_cached[:seq_len].unsqueeze(0).unsqueeze(0)  # [1,1,T,hs]
        sin = self.sin_cached[:seq_len].unsqueeze(0).unsqueeze(0)
        return (x * cos) + (self._rotate_half(x) * sin)


class CausalSelfAttention(nn.Module):
    def __init__(self, cfg: NanoGPTConfig) -> None:
        super().__init__()
        assert cfg.n_embd % cfg.n_head == 0
        self.cfg = cfg
        self.n_head = cfg.n_head
        self.head_dim = cfg.head_dim()
        self.scale = 1.0 / math.sqrt(self.head_dim)

        self.qkv = nn.Linear(cfg.n_embd, 3 * cfg.n_embd, bias=cfg.bias)
        self.proj = nn.Linear(cfg.n_embd, cfg.n_embd, bias=cfg.bias)
        self.dropout = nn.Dropout(cfg.dropout)

        self.rope = RotaryEmbedding(self.head_dim, cfg.block_size, base=cfg.rope_base)

        # Causal mask (T,T)
        self.register_buffer("mask", torch.tril(torch.ones(cfg.block_size, cfg.block_size)).view(1, 1, cfg.block_size, cfg.block_size), persistent=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape
        qkv = self.qkv(x)  # [B,T,3C]
        q, k, v = qkv.split(C, dim=-1)

        # [B, nh, T, hs]
        q = q.view(B, T, self.n_head, self.head_dim).transpose(1, 2)
        k = k.view(B, T, self.n_head, self.head_dim).transpose(1, 2)
        v = v.view(B, T, self.n_head, self.head_dim).transpose(1, 2)

        # Apply RoPE on q,k
        q = self.rope.apply(q, seq_len=T)
        k = self.rope.apply(k, seq_len=T)

        # Attention scores: [B,nh,T,T]
        att = (q @ k.transpose(-2, -1)) * self.scale
        att = att.masked_fill(self.mask[:, :, :T, :T] == 0, float("-inf"))
        att = F.softmax(att, dim=-1)
        att = self.dropout(att)

        y = att @ v  # [B,nh,T,hs]
        y = y.transpose(1, 2).contiguous().view(B, T, C)
        y = self.proj(y)
        y = self.dropout(y)
        return y


class SwiGLU(nn.Module):
    """SwiGLU feed-forward as used in modern LLMs.

    y = (silu(W_g x) * (W_u x)) W_d
    """

    def __init__(self, dim: int, hidden_dim: int, bias: bool = False, dropout: float = 0.0) -> None:
        super().__init__()
        self.wg = nn.Linear(dim, hidden_dim, bias=bias)
        self.wu = nn.Linear(dim, hidden_dim, bias=bias)
        self.wd = nn.Linear(hidden_dim, dim, bias=bias)
        self.drop = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.drop(self.wd(F.silu(self.wg(x)) * self.wu(x)))


class MoE(nn.Module):
    """A simple Top-k MoE layer.

    This implementation uses sparse routing:
    - router produces logits for each expert
    - pick top-k experts per token
    - compute only the selected expert outputs

    Note: For simplicity, we do not include auxiliary load balancing loss. You can add it later.
    """

    def __init__(self, dim: int, hidden_dim: int, num_experts: int = 4, top_k: int = 2, bias: bool = False, dropout: float = 0.0) -> None:
        super().__init__()
        assert top_k >= 1 and top_k <= num_experts
        self.dim = dim
        self.hidden_dim = hidden_dim
        self.num_experts = num_experts
        self.top_k = top_k

        self.router = nn.Linear(dim, num_experts, bias=bias)
        self.experts = nn.ModuleList([SwiGLU(dim, hidden_dim, bias=bias, dropout=dropout) for _ in range(num_experts)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B,T,C]
        B, T, C = x.shape
        x_flat = x.reshape(B * T, C)

        logits = self.router(x_flat)  # [N,E]
        topv, topi = torch.topk(logits, k=self.top_k, dim=-1)  # [N,K]
        weights = F.softmax(topv, dim=-1)  # [N,K]

        out = torch.zeros_like(x_flat)

        # For each expert, gather token indices that route to it (in any top-k slot)
        for e_idx in range(self.num_experts):
            # mask: [N,K]
            mask = topi == e_idx
            if not mask.any():
                continue

            # For each slot k where expert appears, process those tokens
            for k in range(self.top_k):
                tok_mask = mask[:, k]
                if not tok_mask.any():
                    continue
                x_sel = x_flat[tok_mask]
                y_sel = self.experts[e_idx](x_sel)
                w = weights[tok_mask, k].unsqueeze(-1)
                out[tok_mask] += y_sel * w

        return out.view(B, T, C)


class Block(nn.Module):
    def __init__(self, cfg: NanoGPTConfig) -> None:
        super().__init__()
        self.norm1 = RMSNorm(cfg.n_embd)
        self.attn = CausalSelfAttention(cfg)
        self.norm2 = RMSNorm(cfg.n_embd)

        hidden = int(cfg.n_embd * cfg.ffn_hidden_mult)
        if cfg.use_moe:
            self.mlp = MoE(cfg.n_embd, hidden, num_experts=cfg.moe_num_experts, top_k=cfg.moe_top_k, bias=cfg.bias, dropout=cfg.dropout)
        else:
            self.mlp = SwiGLU(cfg.n_embd, hidden, bias=cfg.bias, dropout=cfg.dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.norm1(x))
        x = x + self.mlp(self.norm2(x))
        return x


class NanoGPT(nn.Module):
    """A tiny decoder-only Transformer with modern components (RMSNorm, RoPE, SwiGLU, MoE)."""

    def __init__(self, cfg: NanoGPTConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.transformer = nn.ModuleDict(
            dict(
                wte=nn.Embedding(cfg.vocab_size, cfg.n_embd),
                drop=nn.Dropout(cfg.dropout),
                h=nn.ModuleList([Block(cfg) for _ in range(cfg.n_layer)]),
                ln_f=RMSNorm(cfg.n_embd),
            )
        )
        self.lm_head = nn.Linear(cfg.n_embd, cfg.vocab_size, bias=False)

        # weight tying
        self.lm_head.weight = self.transformer.wte.weight

        self.apply(self._init_weights)

    def _init_weights(self, module: nn.Module) -> None:
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx: torch.Tensor, targets: Optional[torch.Tensor] = None) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """Forward.

        idx: [B,T] token ids
        targets: [B,T] token ids (optional)
        returns: (logits, loss)
        """
        B, T = idx.shape
        if T > self.cfg.block_size:
            raise ValueError(f"Sequence length {T} exceeds block_size {self.cfg.block_size}")

        x = self.transformer.wte(idx)
        x = self.transformer.drop(x)
        for block in self.transformer.h:
            x = block(x)
        x = self.transformer.ln_f(x)
        logits = self.lm_head(x)  # [B,T,V]

        loss = None
        if targets is not None:
            # Flatten
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1), ignore_index=-1)
        return logits, loss

    @torch.no_grad()
    def generate(self, idx: torch.Tensor, max_new_tokens: int = 100, temperature: float = 1.0, top_k: Optional[int] = None) -> torch.Tensor:
        self.eval()
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.cfg.block_size :]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :] / max(1e-6, temperature)
            if top_k is not None:
                v, _ = torch.topk(logits, top_k)
                logits[logits < v[:, [-1]]] = -float("Inf")
            probs = F.softmax(logits, dim=-1)
            next_id = torch.multinomial(probs, num_samples=1)
            idx = torch.cat((idx, next_id), dim=1)
        return idx

    def num_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def to_config_dict(self) -> dict:
        return asdict(self.cfg)
