"""Deterministic rehearsal rules; never used to authorize a real action."""


def disposition(quality: int) -> tuple[str, str, str] | None:
    if quality < 10:
        return "return_home", "degraded_link_return_home", f"演习链路分 {quality} < 10，模拟返航"
    if quality < 40:
        return "hold_position", "degraded_link_hold", f"演习链路分 {quality} < 40，模拟保持"
    return None
