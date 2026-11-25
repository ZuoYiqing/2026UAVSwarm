"""Opt-in local 4B intent candidates for the read-only planning demo."""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, replace
from http.client import HTTPConnection, HTTPException
import json
from threading import Lock, Thread
from time import monotonic
from typing import Any

from uav_runtime.agent._vendor_intent_recognizer_v0 import Binding
from uav_runtime.http.intent_resolution import PreviewIntentResolution
from uav_runtime.http.model_preview_config import ModelPreviewConfig
from uav_runtime.http.planner_preview import FallbackReason


PREVIEW_PATH = "/api/planner/plan-mission"
MAX_MODEL_PAYLOAD_BYTES = 8192
MAX_MODEL_RESPONSE_BYTES = 65536
_ROLES = {"t": "targets", "r": "reference_only", "x": "excluded_targets"}
_PROMPT = (
    "解析巡检原话，只返回JSON。t是核对目标的目录编号数组，按任务顺序；"
    "r是仅定位的编号，x是明确排除的编号。仅定位同时进r和x。"
    "参照对象不能进t。明确只核对指定目标时only=true，否则false。"
    "不明确时t为空，禁猜编号。不要生成动作。"
)
_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": [*_ROLES, "only"],
    "properties": {
        **{role: {"type": "array", "items": {"type": "integer"}, "maxItems": 16} for role in _ROLES},
        "only": {"type": "boolean"},
    },
}


@dataclass(frozen=True, slots=True)
class ModelSelection:
    resolution: PreviewIntentResolution | None = None
    fallback_reason: FallbackReason | None = None


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate model JSON field")
        result[key] = value
    return result


def _json(data: bytes | str) -> Any:
    return json.loads(data, object_pairs_hook=_unique_keys)


def _request_candidate(user_message: str, config: ModelPreviewConfig) -> Any:
    # Config admits only loopback or the private WSL gateway; no redirects or proxy.
    request = {
        "model": config.alias,
        "messages": [{"role": "system", "content": _PROMPT}, {"role": "user", "content": user_message}],
        "temperature": 0, "seed": 11, "stream": False, "max_tokens": 112,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "read_only_preview_intent", "strict": True, "schema": _SCHEMA},
        },
    }
    headers = {"Content-Type": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    connection = HTTPConnection(config.host, config.port, timeout=config.timeout_s)
    started = monotonic()
    try:
        connection.request("POST", "/v1/chat/completions", json.dumps(request), headers)
        with connection.getresponse() as response:
            if response.status != 200:
                raise OSError("local inference refused the request")
            raw = response.read(MAX_MODEL_RESPONSE_BYTES + 1)
    finally:
        connection.close()
    if monotonic() - started > config.timeout_s:
        raise TimeoutError("local inference deadline exceeded")
    if len(raw) > MAX_MODEL_RESPONSE_BYTES:
        raise ValueError("local model response exceeds the limit")
    reply = _json(raw)
    if not isinstance(reply, dict) or reply.get("model") != config.alias:
        raise ValueError("unexpected model identity")
    choices = reply.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("expected exactly one model response")
    choice = choices[0]
    message = choice.get("message")
    if (choice.get("finish_reason") != "stop" or not isinstance(message, dict)
            or message.get("tool_calls") or message.get("function_call")
            or not isinstance(message.get("content"), str)):
        raise ValueError("incomplete or invalid model response")
    return _json(message["content"])


def _validated_candidate(
    candidate: Any, rule: PreviewIntentResolution, catalog_ids: tuple[str, ...],
) -> PreviewIntentResolution:
    if (not isinstance(candidate, dict) or set(candidate) != set(_SCHEMA["required"])
            or candidate["only"] is not rule.parameters.only_listed_targets):
        raise ValueError("model did not preserve the preview scope")
    bindings: dict[str, tuple[Binding, ...]] = {}
    for wire_key, role in _ROLES.items():
        expected = getattr(rule.parameters, role)
        indexes = candidate[wire_key]
        if (not isinstance(indexes, list) or len(indexes) != len(expected)
                or any(type(i) is not int or not 1 <= i <= len(catalog_ids) for i in indexes)):
            raise ValueError("model changed the set of entities")
        ids = tuple(catalog_ids[i - 1] for i in indexes)
        if ids != tuple(binding.entity_id for binding in expected):
            raise ValueError("model changed an entity, its role or its order")
        # Adopt the model's choices; the literal source spans remain independently
        # verified by the rules. The model does not get to fabricate evidence.
        bindings[role] = tuple(Binding(entity_id, binding.evidence) for entity_id, binding in zip(ids, expected))
    return replace(rule, reason_code="LOCAL_MODEL_CONFIRMED_INTENT",
                   parameters=replace(rule.parameters, **bindings))


class LocalPreviewModel:
    def __init__(self, config: ModelPreviewConfig | None = None) -> None:
        self._config = config or ModelPreviewConfig()
        self._slot = Lock()

    def select(self, objective: str, rule: PreviewIntentResolution) -> ModelSelection:
        # No inference for ambiguity, forbidden roles, unknown objectives, status
        # or explicit selectors. A model cannot add a target the scene did not bind.
        catalog = rule.catalog
        if catalog is None or rule.mission_type != "inspection_snapshot" or not rule.supports_template_outline():
            return ModelSelection()
        catalog_ids = tuple(entry.entity_id for entry in catalog.entries)
        data = {
            "原话": objective,
            "目录": [
                {"编号": index, "名称": entry.label, "别名": entry.aliases,
                 **({"仅参照": True} if entry.entity_id in catalog.reference_only_ids else {})}
                for index, entry in enumerate(catalog.entries, start=1)
            ],
        }
        # Do not leak the rule answer or use it as a model prompt hint.
        user_message = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        try:
            if len(user_message.encode("utf-8")) > MAX_MODEL_PAYLOAD_BYTES:
                return ModelSelection(fallback_reason="model_low_confidence")
        except UnicodeError:
            return ModelSelection(fallback_reason="model_low_confidence")
        if not self._slot.acquire(blocking=False):
            return ModelSelection(fallback_reason="model_unavailable")
        pending: Future[PreviewIntentResolution] = Future()

        def infer() -> None:
            try:
                candidate = _request_candidate(user_message, self._config)
                pending.set_result(_validated_candidate(candidate, rule, catalog_ids))
            except Exception as exc:
                pending.set_exception(exc)
            finally:
                self._slot.release()

        try:
            Thread(target=infer, name="local-preview-inference", daemon=True).start()
        except RuntimeError:
            self._slot.release()
            return ModelSelection(fallback_reason="model_unavailable")
        try:
            # Bound the caller wait even if a slow backend dribbles each socket
            # read just before its timeout. The worker retains the one-call slot.
            return ModelSelection(resolution=pending.result(timeout=self._config.timeout_s))
        except (OSError, HTTPException):
            return ModelSelection(fallback_reason="model_unavailable")
        except (ValueError, RecursionError):
            return ModelSelection(fallback_reason="model_low_confidence")
