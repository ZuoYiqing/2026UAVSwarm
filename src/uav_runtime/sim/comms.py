from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LinkModel:
    drop_rate: float = 0.1

    def transmit(self, messages: list[dict]) -> tuple[list[dict], list[dict]]:
        ok: list[dict] = []
        dropped: list[dict] = []
        threshold = int(self.drop_rate * 100)
        for i, msg in enumerate(messages):
            if (i * 37) % 100 < threshold:
                dropped.append(msg)
            else:
                ok.append(msg)
        return ok, dropped
