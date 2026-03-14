from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from swarm_ai_platform.sim.comms import MessageBus
from swarm_ai_platform.sim.types import Link, Message
from swarm_ai_platform.sim.world import World2D


def _partition_area(area: Dict[str, Any], uav_ids: List[str]) -> Dict[str, Dict[str, float]]:
    x_min = float(area.get("x_min_km", 0))
    x_max = float(area.get("x_max_km", 100))
    y_min = float(area.get("y_min_km", 0))
    y_max = float(area.get("y_max_km", 100))
    n = max(1, len(uav_ids))
    width = (x_max - x_min) / n
    out: Dict[str, Dict[str, float]] = {}
    for i, uid in enumerate(uav_ids):
        out[uid] = {
            "x_min_km": x_min + i * width,
            "x_max_km": x_min + (i + 1) * width,
            "y_min_km": y_min,
            "y_max_km": y_max,
        }
    return out


@dataclass
class UAV:
    uav_id: str
    role: str
    x_km: float
    y_km: float
    speed_km_s: float = 0.25  # demo
    heading_deg: float = 90.0
    lane_x_km: float = 0.0
    dir_y: int = 1
    reported_targets: Set[int] = field(default_factory=set)
    mode: str = "Search"  # Search/Track/Return
    track_target_id: int = 0


@dataclass
class SimReport:
    coverage_ratio: float
    msg_stats: Dict[str, Dict[str, int]]
    first_target_report_time_s: int | None
    first_gs_action_time_s: int | None
    drop_rate: float


class SwarmSim:
    """A lightweight 2D swarm simulation.

    - focuses on message flow + decision rules validation
    - not a flight dynamics simulator
    """

    def __init__(self, mission: Dict[str, Any], scene: Dict[str, Any], decision: Dict[str, Any], *, rng_seed: int = 7) -> None:
        self.mission = mission
        self.scene = scene
        self.decision = decision
        self.rng_seed = rng_seed

        # For demo metrics we use a small sensor footprint so coverage ratio becomes meaningful quickly.
        # You can tune grid_res_km / coverage_radius_km to match your application.
        self.world = World2D(mission.get("area", {}), grid_res_km=1.0, coverage_radius_km=10.0, rng_seed=rng_seed)

        # Build links
        links: List[Link] = []
        for l in scene.get("links", []):
            links.append(
                Link(
                    src=str(l.get("src")),
                    dst=str(l.get("dst")),
                    bandwidth_bps=int(l.get("bandwidth_bps", 200000)),
                    latency_ms=int(l.get("latency_ms", 0)),
                    loss_rate=float(l.get("loss_rate", 0.1)),
                )
            )
        self.bus = MessageBus(links, rng_seed=rng_seed)

        # Identify nodes
        nodes = scene.get("nodes", [])
        self.gs_id = next((n.get("id") for n in nodes if n.get("role") in {"global_controller", "ground_station", "gs"}), "GS")
        self.head_id = next((n.get("id") for n in nodes if n.get("role") in {"cluster_head", "head"}), "UAV_1")
        self.member_ids = [n.get("id") for n in nodes if n.get("role") in {"member", "uav_member"}]

        self.uav_ids = [self.head_id] + self.member_ids
        self.subareas = _partition_area(mission.get("area", {}), self.uav_ids)

        # Init UAVs on their subarea corner
        self.uavs: Dict[str, UAV] = {}
        for uid in self.uav_ids:
            sa = self.subareas[uid]
            self.uavs[uid] = UAV(
                uav_id=uid,
                role="cluster_head" if uid == self.head_id else "member",
                x_km=sa["x_min_km"],
                y_km=sa["y_min_km"],
                lane_x_km=sa["x_min_km"],
            )

        self.first_target_report_time_s: int | None = None
        self.first_gs_action_time_s: int | None = None
        self._seq = 0
        self._acted_targets: set[int] = set()

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) % 65536
        return self._seq

    def _send(self, msg_type: str, src: str, dst: str, payload: Dict[str, Any], t: int) -> None:
        self.bus.send(Message(msg_type=msg_type, src=src, dst=dst, payload=payload, timestamp_s=t))

    def _uav_move_and_sense(self, u: UAV, t: int) -> None:
        sa = self.subareas[u.uav_id]

        # If tracking, move towards target roughly
        if u.mode == "Track" and u.track_target_id:
            tgt = next((x for x in self.world.targets if x.target_id == u.track_target_id), None)
            if tgt is not None:
                dx = tgt.x_km - u.x_km
                dy = tgt.y_km - u.y_km
                dist = math.hypot(dx, dy) + 1e-6
                step = min(u.speed_km_s, dist)
                u.x_km += step * dx / dist
                u.y_km += step * dy / dist
        else:
            # lawnmower within subarea
            u.y_km += u.dir_y * u.speed_km_s
            if u.y_km >= sa["y_max_km"]:
                u.y_km = sa["y_max_km"]
                u.dir_y = -1
                u.lane_x_km += 1.0
            elif u.y_km <= sa["y_min_km"]:
                u.y_km = sa["y_min_km"]
                u.dir_y = 1
                u.lane_x_km += 1.0

            if u.lane_x_km > sa["x_max_km"]:
                u.lane_x_km = sa["x_min_km"]
            u.x_km = u.lane_x_km

        # Clamp
        u.x_km = max(sa["x_min_km"], min(sa["x_max_km"], u.x_km))
        u.y_km = max(sa["y_min_km"], min(sa["y_max_km"], u.y_km))

        # Coverage
        self.world.mark_coverage(u.x_km, u.y_km)

        # Sensing targets within radius
        # Enlarged for demo so the GS response path is exercised reliably.
        detect_r = 12.0
        for tgt in self.world.targets:
            if tgt.target_id in u.reported_targets:
                continue
            dist = math.hypot(tgt.x_km - u.x_km, tgt.y_km - u.y_km)
            if dist <= detect_r:
                u.reported_targets.add(tgt.target_id)
                # Build report
                report = {
                    "uav_id": u.uav_id,
                    "target_id": tgt.target_id,
                    "x_pos": tgt.x_km,
                    "y_pos": tgt.y_km,
                    "speed": tgt.speed,
                    "heading": tgt.heading_deg,
                    "confidence": 85,
                    "threat_level": tgt.threat_level,
                    "seq": self._next_seq(),
                }
                self._send("TARGET_REPORT", src=u.uav_id, dst=self.head_id, payload=report, t=t)
                if self.first_target_report_time_s is None:
                    self.first_target_report_time_s = t

        # Periodic status
        if t % 5 == 0:
            status = {
                "uav_id": u.uav_id,
                "x_pos": u.x_km,
                "y_pos": u.y_km,
                "altitude": 120.0,
                "heading": u.heading_deg,
                "speed": u.speed_km_s * 1000.0,  # m/s-ish
                "fuel_level": 90,
                "mission_phase": 1 if u.mode == "Search" else (2 if u.mode == "Track" else 0),
                "seq": self._next_seq(),
            }
            # Status to GS (and optionally to head) via links in scene
            self._send("UAV_STATUS", src=u.uav_id, dst=self.gs_id, payload=status, t=t)

    def _cluster_head_process(self, t: int) -> None:
        inbox = self.bus.recv_all(self.head_id)
        # Collect reports. Persist a small target DB so we can resend summaries periodically
        # (helps under packet loss).
        tgt_db: Dict[int, Dict[str, Any]] = dict(getattr(self, "_tgt_db", {}))
        for msg in inbox:
            if msg.msg_type == "TARGET_REPORT":
                tid = int(msg.payload.get("target_id", 0))
                tgt_db[tid] = msg.payload
            elif msg.msg_type == "CMD_ACTION":
                # Assign a member to track
                tid = int(msg.payload.get("target_id", 0))
                action = int(msg.payload.get("action", 0))
                if action == 1 and self.member_ids:
                    # pick first member for demo
                    u = self.uavs[self.member_ids[0]]
                    u.mode = "Track"
                    u.track_target_id = tid
                    cmd = {
                        "cluster_id": 1,
                        "target_uav": 2,
                        "sub_task": 2,
                        "area_id": 0,
                        "ref_target_id": tid,
                        "seq": self._next_seq(),
                    }
                    # send a few times for reliability under loss (demo)
                    for _ in range(3):
                        self._send("CLUSTER_CMD", src=self.head_id, dst=u.uav_id, payload=cmd, t=t)

        # persist
        self._tgt_db = tgt_db

        # Periodic summary to GS (default 5s)
        if tgt_db and (t % 5 == 0):
            max_threat = max(int(r.get("threat_level", 0)) for r in tgt_db.values())
            summary = {
                "cluster_id": 1,
                "target_count": len(tgt_db),
                "summary_flags": 0,
                "reserved": 0,
                "max_threat": max_threat,
                "targets": list(tgt_db.values()),
                "seq": self._next_seq(),
            }
            self._send("TARGET_SUMMARY", src=self.head_id, dst=self.gs_id, payload=summary, t=t)

    def _gs_process(self, t: int) -> None:
        inbox = self.bus.recv_all(self.gs_id)
        for msg in inbox:
            if msg.msg_type == "TARGET_SUMMARY":
                max_threat = int(msg.payload.get("max_threat", 0))
                if max_threat >= 2:
                    # respond with action to track highest threat target
                    targets = msg.payload.get("targets", [])
                    if targets:
                        tid = int(targets[0].get("target_id", 0))
                        if tid in self._acted_targets:
                            continue
                        cmd = {
                            "target_id": tid,
                            "action": 1,
                            "priority": 8,
                            "time_limit_s": 60,
                            "seq": self._next_seq(),
                        }
                        self._send("CMD_ACTION", src=self.gs_id, dst=self.head_id, payload=cmd, t=t)
                        self._acted_targets.add(tid)
                        if self.first_gs_action_time_s is None:
                            self.first_gs_action_time_s = t

    def run(self) -> SimReport:
        self.world.reset()
        self.world.add_random_targets(n=3)

        T = int(self.mission.get("time_limit_s", 600))
        for t in range(T + 1):
            self.bus.reset_budget()

            # UAV move + generate messages
            for uid in self.uav_ids:
                self._uav_move_and_sense(self.uavs[uid], t=t)

            # deliver msgs
            self.bus.step(now_s=t)

            # cluster head + GS process
            self._cluster_head_process(t=t)
            self._gs_process(t=t)

            # deliver cmds produced at this tick
            self.bus.reset_budget()
            self.bus.step(now_s=t)

        coverage = self.world.coverage_ratio()

        msg_stats = {
            k: {
                "sent": v.sent,
                "delivered": v.delivered,
                "dropped": v.dropped,
                "bytes_sent": v.bytes_sent,
            }
            for k, v in self.bus.stats_by_type.items()
        }

        total_sent = sum(v["sent"] for v in msg_stats.values()) or 1
        total_dropped = sum(v["dropped"] for v in msg_stats.values())
        drop_rate = total_dropped / total_sent

        return SimReport(
            coverage_ratio=coverage,
            msg_stats=msg_stats,
            first_target_report_time_s=self.first_target_report_time_s,
            first_gs_action_time_s=self.first_gs_action_time_s,
            drop_rate=drop_rate,
        )


def run_simulation(mission: Dict[str, Any], scene: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
    sim = SwarmSim(mission, scene, decision)
    rep = sim.run()
    return {
        "coverage_ratio": rep.coverage_ratio,
        "drop_rate": rep.drop_rate,
        "first_target_report_time_s": rep.first_target_report_time_s,
        "first_gs_action_time_s": rep.first_gs_action_time_s,
        "message_stats": rep.msg_stats,
    }
