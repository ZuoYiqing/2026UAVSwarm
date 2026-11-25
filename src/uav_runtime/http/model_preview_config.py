"""Operator-owned configuration for loopback or the authenticated WSL model relay."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv4Network
import math
from pathlib import Path
import platform
import re
import sys
from urllib.parse import urlsplit


MODEL_ALIAS = "qwen3.5-4b-q4-lab"
MODEL_PORT = 18116
DEFAULT_MODEL_TIMEOUT_SECONDS = 18.0
_PRIVATE = tuple(map(IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))


def is_private_bridge_address(address: IPv4Address) -> bool:
    return any(address in network for network in _PRIVATE)


def parse_model_timeout(value: str) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("model timeout must be a number of seconds") from exc
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ValueError("model timeout must be positive, finite and at most 300 seconds")
    return seconds


def read_model_token(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            raw = stream.read(513)
        token = raw.decode("ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError("could not read the local model token file") from exc
    if len(raw) > 512 or re.fullmatch(r"[A-Za-z0-9._~-]{32,256}", token) is None:
        raise ValueError("local model token must be a 32 to 256 character URL-safe ASCII string")
    return token


def _wsl_default_gateway() -> IPv4Address | None:
    if sys.platform != "linux" or "wsl2" not in platform.release().casefold():
        return None
    try:
        routes = Path("/proc/net/route").read_text(encoding="ascii").splitlines()[1:]
        gateways = [
            (int(row[6]), IPv4Address(bytes.fromhex(row[2])[::-1]))
            for line in routes if len(row := line.split()) >= 8
            and row[1] == row[7] == "00000000" and int(row[3], 16) & 3 == 3
        ]
    except (OSError, ValueError):
        return None
    if not gateways:
        return None
    preferred_metric = min(metric for metric, _ in gateways)
    preferred = {gateway for metric, gateway in gateways if metric == preferred_metric}
    return next(iter(preferred)) if len(preferred) == 1 else None


@dataclass(frozen=True, slots=True)
class ModelPreviewConfig:
    host: str = "127.0.0.1"
    port: int = MODEL_PORT
    alias: str = MODEL_ALIAS
    timeout_s: float = DEFAULT_MODEL_TIMEOUT_SECONDS
    token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ModelPreviewConfig:
        seconds = parse_model_timeout(
            env.get("UAV_RUNTIME_LOCAL_MODEL_TIMEOUT_S", str(DEFAULT_MODEL_TIMEOUT_SECONDS))
        )
        alias = env.get("UAV_RUNTIME_LOCAL_MODEL_ALIAS", MODEL_ALIAS)
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", alias) is None:
            raise ValueError("invalid local model alias")
        url = env.get("UAV_RUNTIME_LOCAL_MODEL_URL", f"http://127.0.0.1:{MODEL_PORT}/v1")
        try:
            parsed = urlsplit(url)
            address = IPv4Address(parsed.hostname or "")
            port = parsed.port
        except ValueError as exc:
            raise ValueError("use an explicit IPv4 model URL: http://<address>:<port>/v1") from exc
        if (url != f"http://{address}:{port}/v1" or port is None or not 1 <= port <= 65535):
            raise ValueError("use an explicit IPv4 model URL: http://<address>:<port>/v1")
        token_file = env.get("UAV_RUNTIME_LOCAL_MODEL_TOKEN_FILE")
        token = read_model_token(Path(token_file)) if token_file else None
        if str(address) != "127.0.0.1" and (
            not token or not is_private_bridge_address(address) or address != _wsl_default_gateway()
        ):
            raise ValueError("the remote model URL must be the authenticated private WSL2 default gateway")
        return cls(str(address), port, alias, seconds, token)
