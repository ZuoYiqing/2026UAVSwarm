"""Constrained language-model selection from a small, read-only catalog."""
from __future__ import annotations

from .contracts import ContractError, canonical_json, digest, parse_json
from .local_model_client import ModelError

SELECT_SYSTEM = (
    "为一个已提取的目标短语选对应目录条目。只输出一个JSON对象，字段choice。"
    "明确匹配时填相应的候选编号（字符串）。不唯一填clarify，不存在填unknown。"
    "没有同义或描述证据时不要猜。候选编号与顺序不表示正确答案。"
    '例如候选中一号是存放伞的架子，短语“放雨伞的架子”就答{"choice":"1"}。'
)


def choose(phrase: str, items: list[dict], client, trace: dict) -> str:
    """Expose descriptions and numbered options; bind catalog IDs only in code."""
    if not 1 <= len(items) <= 3 or len({item["entity_id"] for item in items}) != len(items):
        raise ContractError("INVALID_CANDIDATE_SCOPE")
    numbers = {str(i): item["entity_id"] for i, item in enumerate(items, 1)}
    values = [*numbers, "clarify", "unknown"]
    schema = {"type": "object", "additionalProperties": False, "required": ["choice"],
              "properties": {"choice": {"type": "string", "enum": values}}}
    public = {"phrase": phrase, "candidates": [
        {"number": str(i), "labels": item["labels"], "description": item["description"]}
        for i, item in enumerate(items, 1)
    ]}
    messages = [{"role": "system", "content": SELECT_SYSTEM},
                {"role": "user", "content": canonical_json(public)}]
    trace.update(model_request=public, prompt_sha256=digest(messages), schema_sha256=digest(schema))
    try:
        reply = client.complete(messages, schema, seed=0, max_tokens=32, constrained=True)
    except ModelError as exc:
        trace["incomplete_response_evidence"] = exc.response_evidence
        raise
    raw = reply["content"]
    trace.update(model_raw_response=raw, usage=reply.get("usage"), model_reported=reply.get("model"))
    answer = parse_json(raw)
    if (not isinstance(answer, dict) or set(answer) != {"choice"}
            or not isinstance(answer["choice"], str) or answer["choice"] not in values):
        raise ContractError("CHOICE_OUTSIDE_PINNED_SCHEMA")
    return numbers.get(answer["choice"], answer["choice"])
