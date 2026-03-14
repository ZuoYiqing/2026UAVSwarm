from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich import print
from rich.panel import Panel

from swarm_ai_platform.api.server import app as fastapi_app
from swarm_ai_platform.orchestrator.pipeline import SwarmPipeline
from swarm_ai_platform.sim.run_episode import run_simulation
from swarm_ai_platform.utils.io import read_json, write_json, ensure_dir

cli = typer.Typer(add_completion=False)


def _load_example() -> tuple[dict, dict]:
    mission = read_json("examples/mission_demo.json")
    scene = read_json("examples/scene_demo.json")
    return mission, scene


@cli.command()
def demo(
    out_dir: str = typer.Option("generated", help="Output directory"),
) -> None:
    """One-command end-to-end demo: RAG -> decision -> protocol -> codegen -> simulation."""
    mission, scene = _load_example()
    pipeline = SwarmPipeline(kb_dir="kb")
    out = ensure_dir(out_dir)
    res = pipeline.run(mission, scene, out_dir=out)

    # Simulation
    sim_rep = run_simulation(res.mission, res.scene, res.decision)
    write_json(out / "sim_report.json", sim_rep)

    print(Panel.fit("SwarmAI Platform Demo Finished", title="OK"))
    print("[bold]Artifacts[/bold]:", str(res.generated_dir))
    print("- decision.json")
    print("- protocol.json")
    print("- codegen/messages.h")
    print("- codegen/messages.py")
    print("- sim_report.json")

    print("\n[bold]Quick Summary[/bold]")
    print({
        "coverage_ratio": sim_rep.get("coverage_ratio"),
        "drop_rate": sim_rep.get("drop_rate"),
        "first_target_report_time_s": sim_rep.get("first_target_report_time_s"),
        "first_gs_action_time_s": sim_rep.get("first_gs_action_time_s"),
    })


@cli.command()
def plan(
    mission_path: str = typer.Option(..., help="Path to mission_json"),
    scene_path: str = typer.Option(..., help="Path to scene_json"),
    out_dir: str = typer.Option("generated", help="Output directory"),
) -> None:
    """Generate decision_json and protocol_json (plus codegen)."""
    mission = read_json(mission_path)
    scene = read_json(scene_path)
    pipeline = SwarmPipeline(kb_dir="kb")
    out = ensure_dir(out_dir)
    res = pipeline.run(mission, scene, out_dir=out)
    print(Panel.fit("Plan Generated", title="OK"))
    print(res.notes)
    print("Artifacts dir:", res.generated_dir)


@cli.command()
def sim(
    mission_path: str = typer.Option(..., help="Path to mission_json"),
    scene_path: str = typer.Option(..., help="Path to scene_json"),
    decision_path: str = typer.Option(..., help="Path to decision_json"),
    out_dir: str = typer.Option("generated", help="Output directory"),
) -> None:
    """Run simulation and produce metrics."""
    mission = read_json(mission_path)
    scene = read_json(scene_path)
    decision = read_json(decision_path)
    rep = run_simulation(mission, scene, decision)
    out = ensure_dir(out_dir)
    write_json(out / "sim_report.json", rep)
    print(Panel.fit("Simulation Done", title="OK"))
    print(rep)


@cli.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host"),
    port: int = typer.Option(8000, help="Port"),
) -> None:
    """Start FastAPI server."""
    import uvicorn

    uvicorn.run("swarm_ai_platform.api.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    cli()
