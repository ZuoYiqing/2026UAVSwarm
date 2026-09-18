"""Publish only simulator evidence to the existing loopback Runtime API."""
from __future__ import annotations

import copy
import json
import urllib.parse
import urllib.request
from typing import Any

try:
    from .evidence import freshness
except ImportError:
    from evidence import freshness


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("runtime_evidence_redirect_refused")


def prepare_publication(evidence: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    valid, reason, age_ms = freshness(evidence, now=now)
    if not valid:
        raise ValueError(reason)
    result = copy.deepcopy(evidence)
    remaining = int(result["valid_for_ms"] - (age_ms or 0))
    if remaining < 100:
        raise ValueError("evidence_ttl_exhausted")
    # Runtime 3fa42eb measures TTL from reception. Cap it to the remaining
    # producer lifetime; never rewrite source_timestamp to rejuvenate a file.
    result["valid_for_ms"] = remaining
    return result


def publish(api_base: str, evidence: dict[str, Any], *, kind: str = "simulation") -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(api_base)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") != "/api"):
        raise ValueError("runtime_evidence_requires_loopback_api")
    routes = {"simulation": "/simulation/evidence", "calibration": "/coordinates/calibration"}
    if kind not in routes:
        raise ValueError("unsupported_evidence_kind")
    payload = prepare_publication(evidence)
    request = urllib.request.Request(api_base.rstrip("/") + routes[kind],
        data=json.dumps(payload, allow_nan=False).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=3) as response:
        return {"http_status": response.status, "response": json.load(response),
                "published_source_timestamp": payload["source_timestamp"],
                "published_valid_for_ms": payload["valid_for_ms"]}
