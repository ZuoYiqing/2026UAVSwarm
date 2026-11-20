"""Bounded loopback inference client, with no proxies, redirects or retries."""

from __future__ import annotations

import json
import math
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .contracts import MAX_JSON_BYTES, ContractError, parse_json


class ModelFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelFailure("MODEL_UNAVAILABLE")


class LocalInferenceClient:
    def __init__(self, endpoint: str, model: str):
        parsed = urlsplit(endpoint)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("MODEL_ENDPOINT_INVALID") from exc
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
                or port is None or parsed.path != "/v1/chat/completions"
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("MODEL_ENDPOINT_MUST_BE_LOOPBACK")
        if not isinstance(model, str) or not model.strip() or len(model) > 128:
            raise ValueError("MODEL_ID_INVALID")
        self.endpoint = endpoint
        self.model = model
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def complete(self, messages: list[dict], output_schema: dict, *,
                 timeout_s: float) -> dict[str, str]:
        if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
                or not 0 < timeout_s <= 10):
            raise ValueError("MODEL_TIMEOUT_INVALID")
        payload = {
            "model": self.model, "messages": messages, "seed": 0,
            "temperature": 0, "max_tokens": 128, "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "platform_candidate", "strict": True,
                                "schema": output_schema},
            },
        }
        request = Request(
            self.endpoint, method="POST", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=timeout_s) as response:
                raw = response.read(MAX_JSON_BYTES + 1)
        except (TimeoutError, socket.timeout) as exc:
            raise ModelFailure("MODEL_TIMEOUT") from exc
        except (HTTPError, URLError, OSError, ModelFailure) as exc:
            raise ModelFailure("MODEL_UNAVAILABLE") from exc
        if len(raw) > MAX_JSON_BYTES:
            raise ModelFailure("MODEL_OUTPUT_INVALID")
        try:
            data = parse_json(raw)
            if not isinstance(data, dict):
                raise ContractError("MODEL_ENVELOPE_INVALID")
            choice = data["choices"][0]
            if (not isinstance(choice, dict) or choice.get("finish_reason") != "stop"
                    or not isinstance(choice.get("message"), dict)):
                raise ContractError("MODEL_RESPONSE_INCOMPLETE")
            message = choice["message"]
            if message.get("tool_calls") or message.get("function_call"):
                raise ContractError("MODEL_TOOL_CALL_REFUSED")
            content = message["content"]
            if not isinstance(content, str):
                raise ContractError("MODEL_CONTENT_NOT_TEXT")
            reported = data.get("model")
            if reported is not None and not isinstance(reported, str):
                raise ContractError("MODEL_ID_REPORTED_INVALID")
            return {"content": content, "model": reported or self.model}
        except (ContractError, KeyError, IndexError, TypeError) as exc:
            raise ModelFailure("MODEL_OUTPUT_INVALID") from exc
