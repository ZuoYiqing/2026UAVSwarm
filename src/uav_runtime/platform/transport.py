"""Explicit loopback-only HTTP; no proxy inheritance or redirects."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .contract import PlatformError, canonical


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class JsonClient:
    def __init__(self, base: str, token: str = "", timeout: float = 2.0, max_bytes: int = 65536):
        url = urlsplit(base)
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                or url.username or url.password or url.query or url.fragment):
            raise PlatformError("explicit_loopback_url_required")
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout
        self.max_bytes = max_bytes
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method: str, path: str = "", body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=canonical(body).encode() if body is not None else None)
        try:
            response = self.opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            data = response.read(self.max_bytes + 1)
            if len(data) > self.max_bytes:
                raise PlatformError("upstream_response_too_large", 502)
            value = json.loads(data)
            if not isinstance(value, dict):
                raise PlatformError("invalid_upstream_response", 502)
            return response.status, value
