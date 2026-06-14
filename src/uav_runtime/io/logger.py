from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MemoryLogger:
    entries: list[str] = field(default_factory=list)

    def info(self, message: str) -> None:
        self.entries.append(f"INFO:{message}")

    def warning(self, message: str) -> None:
        self.entries.append(f"WARN:{message}")
