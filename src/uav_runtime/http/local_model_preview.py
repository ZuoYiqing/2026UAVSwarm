"""Opt-in model decisions for the read-only planning demo."""
from __future__ import annotations

from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, replace
from http.client import HTTPConnection, HTTPException
import json
import re
from threading import Lock, Thread
from time import monotonic
from typing import Any

from uav_runtime.agent._vendor_intent_recognizer_v0 import Binding, CatalogEntry, IntentParameters
from uav_runtime.http.intent_resolution import PreviewIntentResolution
from uav_runtime.http.model_preview_config import ModelPreviewConfig
from uav_runtime.http.planner_preview import FallbackReason


PREVIEW_PATH = "/api/planner/plan-mission"
MAX_MODEL_PAYLOAD_BYTES = 8192
MAX_MODEL_RESPONSE_BYTES = 65536
MAX_DIAGNOSTIC_CHARS = 1024
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
_PROMPT_FRAGMENTS = tuple(fragment for fragment in re.split("[。；]", _PROMPT) if fragment)
_PROTECTED_PROMPT_TEXT = (*_PROMPT_FRAGMENTS, *(json.dumps(piece)[1:-1] for piece in _PROMPT_FRAGMENTS))
_SENSITIVE_REPLY = re.compile(
    r"(?i)(?:\b(?:authorization|api[_ -]?key|bearer|token|system[_ -]?(?:prompt|message)|reasoning_content)\b"
    r"|[a-z]:[\\/]|\\\\|(?:^|[\s\"'=:(])/[^\s\"']+|\.(?:gguf|safetensors)\b)"
)


class _InvalidOutput(ValueError):
    def __init__(self, reason: str, raw_text: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw_text = raw_text


@dataclass(frozen=True, slots=True)
class ModelAttempt:
    raw_text: str | None
    adopted: bool
    not_adopted_reason: str | None
    truncated: bool = False
    redacted: bool = False


@dataclass(frozen=True, slots=True)
class ModelSelection:
    resolution: PreviewIntentResolution | None = None
    fallback_reason: FallbackReason | None = None
    attempts: tuple[ModelAttempt, ...] = ()
    stop_reason: str | None = None

    def diagnostics(self) -> dict[str, Any]:
        last = self.attempts[-1]
        return {
            "adopted": self.resolution is not None,
            "not_adopted_reason": self.stop_reason or last.not_adopted_reason,
            "attempts": [asdict(attempt) for attempt in self.attempts],
        }


def _attempt(raw: str | None, reason: str | None, token: str | None) -> ModelAttempt:
    if raw is None:
        return ModelAttempt(None, False, reason)
    # Only message.content reaches this function. Drop a suspicious reply rather
    # than exposing a partial token, prompt, or absolute path after truncation.
    if ((token and token in raw) or any(piece in raw for piece in _PROTECTED_PROMPT_TEXT)
            or _SENSITIVE_REPLY.search(raw)):
        return ModelAttempt("[redacted]", reason is None, reason, redacted=True)
    clipped = raw[:MAX_DIAGNOSTIC_CHARS]
    clipped = clipped.encode("utf-8", errors="replace").decode("utf-8")
    return ModelAttempt(clipped, reason is None, reason, truncated=len(raw) > MAX_DIAGNOSTIC_CHARS)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate model JSON field")
        result[key] = value
    return result


def _not_json_constant(_value: str) -> None:
    raise ValueError("non-JSON constant")


def _json(data: bytes | str) -> Any:
    return json.loads(data, object_pairs_hook=_unique_keys, parse_constant=_not_json_constant)


def _request_candidate(
    user_message: str, config: ModelPreviewConfig, *, seed: int, temperature: float, timeout_s: float,
) -> str:
    # Config admits only loopback or the private WSL gateway; no redirects or proxy.
    request = {
        "model": config.alias,
        "messages": [{"role": "system", "content": _PROMPT}, {"role": "user", "content": user_message}],
        "temperature": temperature, "seed": seed, "stream": False, "max_tokens": 112,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "read_only_preview_intent", "strict": True, "schema": _SCHEMA},
        },
    }
    headers = {"Content-Type": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    connection = HTTPConnection(config.host, config.port, timeout=timeout_s)
    started = monotonic()
    try:
        connection.request("POST", "/v1/chat/completions", json.dumps(request), headers)
        with connection.getresponse() as response:
            if response.status != 200:
                raise OSError("local inference refused the request")
            raw = response.read(MAX_MODEL_RESPONSE_BYTES + 1)
    finally:
        connection.close()
    if monotonic() - started > timeout_s:
        raise TimeoutError("local inference deadline exceeded")
    if len(raw) > MAX_MODEL_RESPONSE_BYTES:
        raise _InvalidOutput("MODEL_RESPONSE_TOO_LARGE")
    try:
        reply = _json(raw)
    except (ValueError, RecursionError) as exc:
        raise _InvalidOutput("MODEL_ENVELOPE_INVALID") from exc
    if not isinstance(reply, dict):
        raise _InvalidOutput("MODEL_ENVELOPE_INVALID")
    choices = reply.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise _InvalidOutput("MODEL_ENVELOPE_INVALID")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise _InvalidOutput("MODEL_ENVELOPE_INVALID")
    content = message.get("content")
    if not isinstance(content, str):
        raise _InvalidOutput("MODEL_TEXT_MISSING")
    if reply.get("model") != config.alias:
        raise _InvalidOutput("MODEL_ID_MISMATCH", content)
    if choice.get("finish_reason") != "stop":
        raise _InvalidOutput("MODEL_RESPONSE_INCOMPLETE", content)
    if message.get("tool_calls") or message.get("function_call"):
        raise _InvalidOutput("MODEL_TOOL_CALL_REFUSED", content)
    return content


def _binding(entry: CatalogEntry, objective: str) -> Binding:
    evidence = max((name for name in (entry.label, *entry.aliases) if name in objective),
                   key=len, default="")
    return Binding(entry.entity_id, evidence)


def _order_basis(original: IntentParameters, selected: tuple[Binding, ...]):
    # The rule basis only describes an order from the utterance. A changed model
    # order is legal, but must not claim the utterance established that order.
    ids = [binding.entity_id for binding in selected]
    keep = set(ids)
    if len(ids) > 1 and [b.entity_id for b in original.targets if b.entity_id in keep] == ids:
        return original.target_order_basis
    return None


def _validated_candidate(
    raw: str, objective: str, rule: PreviewIntentResolution,
) -> PreviewIntentResolution | None:
    try:
        candidate = _json(raw)
    except (ValueError, RecursionError) as exc:
        raise _InvalidOutput("MODEL_JSON_INVALID") from exc
    if (not isinstance(candidate, dict) or set(candidate) != set(_SCHEMA["required"])
            or type(candidate["only"]) is not bool):
        raise _InvalidOutput("MODEL_FIELDS_INVALID")
    catalog = rule.catalog
    assert catalog is not None  # select has already run the scene admission gate
    selected: dict[str, tuple[CatalogEntry, ...]] = {}
    for wire_key, role in _ROLES.items():
        indexes = candidate[wire_key]
        if (not isinstance(indexes, list) or len(indexes) > _SCHEMA["properties"][wire_key]["maxItems"]
                or any(type(i) is not int or not 1 <= i <= len(catalog.entries) for i in indexes)):
            raise _InvalidOutput("MODEL_INDEX_INVALID")
        if len(set(indexes)) != len(indexes):
            raise _InvalidOutput("MODEL_DUPLICATE_SELECTION")
        selected[role] = tuple(catalog.entries[i - 1] for i in indexes)
    bindings = {role: tuple(_binding(entry, objective) for entry in entries)
                for role, entries in selected.items()}
    targets = bindings["targets"]
    if catalog.selects_permanent_reference(targets):
        raise _InvalidOutput("TARGET_REFERENCE_ONLY")
    prohibited = {b.entity_id for items in (bindings["reference_only"], bindings["excluded_targets"],
                                            rule.parameters.reference_only, rule.parameters.excluded_targets)
                  for b in items}
    if any(binding.entity_id in prohibited for binding in targets):
        raise _InvalidOutput("MODEL_ROLE_CONFLICT")
    groups = [entry.exclusive_group for entry in selected["targets"] if entry.exclusive_group is not None]
    if len(groups) != len(set(groups)):
        raise _InvalidOutput("CONFLICTING_TARGETS")
    if not targets:
        return None
    return replace(rule, reason_code="LOCAL_MODEL_SELECTED_INTENT", parameters=replace(
        rule.parameters, **bindings, only_listed_targets=candidate["only"],
        target_order_basis=_order_basis(rule.parameters, targets),
    ))


class LocalPreviewModel:
    def __init__(self, config: ModelPreviewConfig | None = None) -> None:
        self._config = config or ModelPreviewConfig()
        self._slot = Lock()

    def select(self, objective: str, rule: PreviewIntentResolution) -> ModelSelection:
        # Rules decide whether this is a resolvable inspection. They do not supply
        # the model's answer or require that its legal choices be identical.
        catalog = rule.catalog
        if catalog is None or rule.mission_type != "inspection_snapshot" or not rule.supports_template_outline():
            return ModelSelection()
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
        token = self._config.token

        def unavailable(reason: str) -> ModelSelection:
            return ModelSelection(fallback_reason="model_unavailable", attempts=(_attempt(None, reason, token),))

        try:
            if len(user_message.encode("utf-8")) > MAX_MODEL_PAYLOAD_BYTES:
                return unavailable("MODEL_INPUT_TOO_LARGE")
        except UnicodeError:
            return unavailable("MODEL_INPUT_INVALID")
        if not self._slot.acquire(blocking=False):
            return unavailable("MODEL_BUSY")
        deadline = monotonic() + self._config.timeout_s
        pending: Future[ModelSelection] = Future()
        history: list[ModelAttempt] = []
        history_lock = Lock()

        def remember(raw: str | None, reason: str | None) -> None:
            attempt = _attempt(raw, reason, token)
            with history_lock:
                history.append(attempt)

        def timed_out() -> ModelSelection:
            with history_lock:
                completed = tuple(history)
            if len(completed) < 2 and (not completed or not completed[-1].adopted):
                completed += (_attempt(None, "MODEL_TIMEOUT", token),)
            elif completed[-1].adopted:
                completed = (*completed[:-1],
                             replace(completed[-1], adopted=False, not_adopted_reason="MODEL_TIMEOUT"))
            return ModelSelection(fallback_reason="model_unavailable", attempts=completed, stop_reason="MODEL_TIMEOUT")

        def decide() -> ModelSelection:
            for seed, temperature in ((11, 0.0), (29, 0.2)):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return timed_out()
                raw = None
                try:
                    raw = _request_candidate(user_message, self._config, seed=seed,
                                             temperature=temperature, timeout_s=remaining)
                    resolution = _validated_candidate(raw, objective, rule)
                except _InvalidOutput as exc:
                    remember(raw if exc.raw_text is None else exc.raw_text, exc.reason)
                    continue
                except (OSError, HTTPException) as exc:
                    remember(None, "MODEL_TIMEOUT" if isinstance(exc, TimeoutError) else "MODEL_UNAVAILABLE")
                    return ModelSelection(fallback_reason="model_unavailable", attempts=tuple(history))
                if resolution is None:
                    remember(raw, "MODEL_ABSTAINED")
                    return ModelSelection(fallback_reason="model_abstained", attempts=tuple(history))
                remember(raw, None)
                return ModelSelection(resolution=resolution, attempts=tuple(history))
            return ModelSelection(fallback_reason="model_invalid_output", attempts=tuple(history))

        def infer() -> None:
            try:
                pending.set_result(decide())
            except Exception as exc:
                pending.set_exception(exc)
            finally:
                self._slot.release()

        try:
            Thread(target=infer, name="local-preview-inference", daemon=True).start()
        except RuntimeError:
            self._slot.release()
            return unavailable("MODEL_THREAD_UNAVAILABLE")
        try:
            # The total budget is shared by both attempts, even if the backend
            # dribbles bytes just before socket timeouts. Keep its slot until exit.
            return pending.result(timeout=max(0.0, deadline - monotonic()))
        except FutureTimeoutError:
            # Before Python 3.11, Future's wait timeout is not an OSError.
            return timed_out()
