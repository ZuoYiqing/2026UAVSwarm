from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class KBChunk:
    id: str
    source: str
    text: str


def _simple_split(text: str, max_chars: int = 900) -> List[str]:
    """Split by blank lines, then pack to max_chars."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buf = ""
    for p in paras:
        if not buf:
            buf = p
            continue
        if len(buf) + 2 + len(p) <= max_chars:
            buf += "\n\n" + p
        else:
            chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    return chunks


class KBStore:
    """A tiny, dependency-light knowledge base.

    - Default: keyword overlap scoring
    - Optional: sentence-transformers embeddings if installed

    This is intentionally simple for a runnable demo.
    """

    def __init__(self) -> None:
        self.chunks: List[KBChunk] = []
        self._embedder = None
        self._embeddings = None

        # Optional embedding backend
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception:
            self._embedder = None

    def ingest_dir(self, kb_dir: str | Path) -> None:
        kb_dir = Path(kb_dir)
        files = list(kb_dir.glob("**/*"))
        for f in files:
            if not f.is_file():
                continue
            if f.suffix.lower() not in {".md", ".txt", ".json"}:
                continue
            raw = f.read_text(encoding="utf-8", errors="ignore")
            parts = _simple_split(raw)
            for i, p in enumerate(parts):
                self.chunks.append(KBChunk(id=f"{f.name}:{i}", source=f.as_posix(), text=p))

        # Build embeddings if available
        if self._embedder is not None and self.chunks:
            texts = [c.text for c in self.chunks]
            self._embeddings = self._embedder.encode(texts, normalize_embeddings=True)

    def retrieve(self, query: str, top_k: int = 4) -> List[KBChunk]:
        if not self.chunks:
            return []

        if self._embedder is not None and self._embeddings is not None:
            q = self._embedder.encode([query], normalize_embeddings=True)[0]
            # cosine similarity with normalized vectors
            import numpy as np

            scores = (self._embeddings @ q).tolist()
            idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
            return [self.chunks[i] for i in idx]

        # Fallback: keyword overlap
        q_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
        scored = []
        for c in self.chunks:
            terms = set(re.findall(r"[\w\u4e00-\u9fff]+", c.text.lower()))
            score = len(q_terms & terms) / (len(q_terms) + 1e-6)
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]


def format_context(chunks: List[KBChunk]) -> str:
    out = []
    for c in chunks:
        out.append(f"[SOURCE] {c.source}\n{c.text}")
    return "\n\n".join(out)
