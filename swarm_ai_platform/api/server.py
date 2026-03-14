from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from swarm_ai_platform.orchestrator.pipeline import SwarmPipeline
from swarm_ai_platform.sim.run_episode import run_simulation
from swarm_ai_platform.utils.io import ensure_dir, write_json


class PlanRequest(BaseModel):
    mission: Dict[str, Any]
    scene: Dict[str, Any]
    out_dir: str = Field(default="generated/api")


class PlanResponse(BaseModel):
    decision: Dict[str, Any]
    protocol: Dict[str, Any]
    notes: str
    artifacts_dir: str


class SimRequest(BaseModel):
    mission: Dict[str, Any]
    scene: Dict[str, Any]
    decision: Dict[str, Any]


app = FastAPI(title="SwarmAI Platform Demo", version="0.1.0")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/plan", response_model=PlanResponse)
def v1_plan(req: PlanRequest) -> PlanResponse:
    pipeline = SwarmPipeline(kb_dir="kb")
    out_dir = ensure_dir(req.out_dir)
    res = pipeline.run(req.mission, req.scene, out_dir)
    return PlanResponse(
        decision=res.decision,
        protocol=res.protocol,
        notes=res.notes,
        artifacts_dir=str(res.generated_dir),
    )


@app.post("/v1/sim/run")
def v1_sim_run(req: SimRequest) -> Dict[str, Any]:
    rep = run_simulation(req.mission, req.scene, req.decision)
    # Also persist report for traceability
    out = ensure_dir("generated/api") / "sim_report.json"
    write_json(out, rep)
    return rep
