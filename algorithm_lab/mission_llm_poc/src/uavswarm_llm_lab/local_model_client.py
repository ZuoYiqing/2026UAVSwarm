"""Opt-in loopback text inference only. No tools, redirects, proxies or retries."""
from __future__ import annotations

import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .contracts import ContractError, parse_json


class ModelError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("MODEL_REDIRECT_REFUSED")


class LocalModelClient:
    def __init__(self, base_url: str, model: str, timeout_s: float = 90):
        url = urlsplit(base_url)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
                or url.username is not None or url.password is not None
                or url.query or url.fragment or url.path.rstrip("/") != "/v1"
                or url.port is None):
            raise ModelError("Expected http://127.0.0.1:<port>/v1 or http://[::1]:<port>/v1")
        if not model.strip() or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ModelError("Model and positive finite timeout are required")
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.timeout_s = timeout_s

    def complete(self, messages: list, output_schema: dict, *, seed: int,
                 max_tokens: int, constrained: bool) -> dict:
        if type(seed) is not int or type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
            raise ModelError("Invalid inference limits")
        payload = {"model": self.model, "messages": messages, "temperature": 0,
                   "seed": seed, "max_tokens": max_tokens, "stream": False}
        if constrained:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "mission_proposal", "strict": True,
                                "schema": output_schema}}
        request = Request(self.endpoint, data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=self.timeout_s) as response:
                body = response.read(1_048_577)
            if len(body) > 1_048_576:
                raise ModelError("MODEL_RESPONSE_TOO_LARGE")
            data = parse_json(body.decode("utf-8"))
            choice = data["choices"][0]
            if not isinstance(choice, dict):
                raise ModelError("MODEL_CHOICE_NOT_OBJECT")
            message = choice["message"]
            if not isinstance(message, dict):
                raise ModelError("MODEL_MESSAGE_NOT_OBJECT")
            if choice.get("finish_reason") != "stop":
                raise ModelError("MODEL_RESPONSE_INCOMPLETE")
            if message.get("tool_calls") or message.get("function_call"):
                raise ModelError("MODEL_TOOL_CALL_REFUSED")
            content = message["content"]
            if not isinstance(content, str):
                raise ModelError("MODEL_CONTENT_NOT_TEXT")
            return {"content": content, "model": data.get("model"),
                    "usage": data.get("usage")}
        except (HTTPError, URLError, TimeoutError, OSError, ContractError,
                UnicodeError, KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"MODEL_REQUEST_FAILED: {type(exc).__name__}: {exc}") from exc
