"""Strict JSON parsing, schemas, and reproducibility identifiers."""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator


class ContractError(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ContractError(f"non-finite JSON number: {value}")


def parse_json(text: str) -> Any:
    if len(text.encode("utf-8")) > 1_048_576:
        raise ContractError("JSON exceeds 1 MiB")
    try:
        value = json.loads(text, object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
        canonical_json(value)  # Also rejects exponent overflow, e.g. 1e999.
        return value
    except (ValueError, RecursionError, TypeError) as exc:
        raise ContractError(str(exc)) from exc


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    """Python JSON content hash, not RFC 8785 or a cross-language number hash."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def resource_text(relative: str) -> str:
    return files("uavswarm_llm_lab").joinpath(relative).read_text(encoding="utf-8")


def schema(kind: str) -> dict:
    if kind not in {"context", "proposal"}:
        raise ValueError("unknown schema")
    name = "mission_context" if kind == "context" else "mission_proposal"
    return json.loads(resource_text(f"schemas/{name}.schema.json"))


def schema_errors(value: Any, kind: str) -> list[str]:
    try:
        canonical_json(value)
    except (ValueError, TypeError, RecursionError) as exc:
        return [f"non-JSON value: {exc}"]
    errors = Draft202012Validator(schema(kind)).iter_errors(value)
    return sorted(f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
                  for e in errors)
