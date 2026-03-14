from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from swarm_ai_platform.orchestrator.planner import PlanArtifacts, Planner


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from a model output."""
    # Try fenced block
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    if m:
        return json.loads(m.group(1))
    # Fallback: first {...}
    m = re.search(r"(\{.*\})", text, flags=re.S)
    if not m:
        raise ValueError("No JSON found in model output")
    return json.loads(m.group(1))


@dataclass
class HuggingFaceCausalConfig:
    model_name_or_path: str = "Qwen/Qwen2.5-0.5B-Instruct"
    device: str = "cpu"
    max_new_tokens: int = 512


class TeacherLLMPlanner(Planner):
    """Teacher planner backed by a generic instruct model.

    This is OPTIONAL. It needs `transformers` installed and the model weights available.
    """

    def __init__(self, cfg: HuggingFaceCausalConfig) -> None:
        self.cfg = cfg
        self._pipe = None

    def _lazy_init(self) -> None:
        if self._pipe is not None:
            return
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        except Exception as e:
            raise RuntimeError("transformers not installed. Install with requirements-full.txt") from e

        tok = AutoTokenizer.from_pretrained(self.cfg.model_name_or_path, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(self.cfg.model_name_or_path, trust_remote_code=True)
        model.to(self.cfg.device)
        self._pipe = (tok, model)

    def generate(self, mission: Dict[str, Any], scene: Dict[str, Any], kb_context: str = "") -> PlanArtifacts:
        self._lazy_init()
        tok, model = self._pipe

        prompt = (
            "你是无人集群分层决策助手。请根据 mission_json 与 scene_json 生成严格 JSON 格式的 decision_json。\n"
            "要求：输出必须是单一 JSON 对象，不要输出额外解释。\n\n"
            f"KB_CONTEXT:\n{kb_context}\n\n"
            f"mission_json:\n{json.dumps(mission, ensure_ascii=False)}\n\n"
            f"scene_json:\n{json.dumps(scene, ensure_ascii=False)}\n\n"
            "请输出 decision_json:" 
        )

        inputs = tok(prompt, return_tensors="pt").to(model.device)
        out_ids = model.generate(**inputs, max_new_tokens=self.cfg.max_new_tokens)
        out_text = tok.decode(out_ids[0], skip_special_tokens=True)

        decision = _extract_json(out_text)
        return PlanArtifacts(decision_json=decision, notes="TeacherLLMPlanner (HF) generated decision_json")
