from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from swarm_ai_platform.orchestrator.planner import Planner, RulePlanner
from swarm_ai_platform.orchestrator.protocol_synthesizer import ProtocolSynthesizer
from swarm_ai_platform.protocol.codegen import write_codegen
from swarm_ai_platform.rag.store import KBStore, format_context
from swarm_ai_platform.utils.io import ensure_dir, write_json
from swarm_ai_platform.utils.schema import assert_valid, decision_schema, mission_schema, protocol_schema, scene_schema


@dataclass
class PipelineResult:
    mission: Dict[str, Any]
    scene: Dict[str, Any]
    decision: Dict[str, Any]
    protocol: Dict[str, Any]
    generated_dir: Path
    codegen_dir: Path
    notes: str


class SwarmPipeline:
    def __init__(
        self,
        planner: Optional[Planner] = None,
        kb_dir: Optional[str | Path] = None,
    ) -> None:
        self.planner = planner or RulePlanner()
        self.protocol_synth = ProtocolSynthesizer()
        self.kb = KBStore()
        if kb_dir is not None:
            self.kb.ingest_dir(kb_dir)

    def run(
        self,
        mission: Dict[str, Any],
        scene: Dict[str, Any],
        out_dir: str | Path,
        *,
        query_for_kb: str = "protocol fields message definitions",
    ) -> PipelineResult:
        # Validate inputs
        assert_valid(mission, mission_schema(), name="mission_json")
        assert_valid(scene, scene_schema(), name="scene_json")

        out_dir = ensure_dir(out_dir)

        # RAG retrieve context
        chunks = self.kb.retrieve(query_for_kb, top_k=4) if self.kb.chunks else []
        kb_context = format_context(chunks) if chunks else ""

        # Decision
        plan_art = self.planner.generate(mission, scene, kb_context=kb_context)
        decision = plan_art.decision_json
        assert_valid(decision, decision_schema(), name="decision_json")

        # Protocol
        protocol = self.protocol_synth.synthesize(decision, scene)
        assert_valid(protocol, protocol_schema(), name="protocol_json")

        # Write artifacts
        write_json(out_dir / "decision.json", decision)
        write_json(out_dir / "protocol.json", protocol)

        # Codegen
        codegen_dir = out_dir / "codegen"
        c_h, py_f = write_codegen(codegen_dir, protocol)

        notes = plan_art.notes
        if kb_context:
            write_json(out_dir / "kb_context.json", {"query": query_for_kb, "chunks": [c.__dict__ for c in chunks]})

        notes += f"\ncodegen: {c_h.name}, {py_f.name}"
        return PipelineResult(
            mission=mission,
            scene=scene,
            decision=decision,
            protocol=protocol,
            generated_dir=out_dir,
            codegen_dir=codegen_dir,
            notes=notes,
        )
