"""Read-only platform projections; ground never recalculates local/scene poses."""
from __future__ import annotations

import copy
from .contract import PlatformError, stamp, timestamp


VIEW_PATHS = {"telemetry": "/api/telemetry/latest", "vehicles": "/api/vehicles",
              "runtime_snapshot": "/api/snapshot", "vehicle_snapshot": "/api/vehicle-snapshot"}
VIEW_VALID_MS = 3000


def produce_view(service, dispatch):
    projections = None
    if service.mode == "sitl" and dispatch is not None:
        before = service.observe()
        projections = {}
        for key, path in VIEW_PATHS.items():
            code, value = dispatch("GET", path)
            if code != 200:
                raise PlatformError("platform_view_unavailable", 503)
            projections[key] = value
        validate_projections(projections)
        # A fresh HEARTBEAT/battery snapshot must not make an old local pose
        # usable. Reuse the owner's per-position sample evidence, not its
        # arbitrary latest telemetry timestamp. Nothing is sent to the model.
        observation = service.observe()
        sample = before.get("sample_timestamp")
        try:
            position_age = (service.clock() - timestamp(sample)) * 1000
        except (PlatformError, TypeError):
            position_age = None
        position_fresh = (before.get("source") == observation.get("source") == "px4_telemetry"
                          and before.get("stale") is False and observation.get("stale") is False
                          and position_age is not None and 0 <= position_age <= projections["telemetry"]["stale_after_ms"])
        for row in projections["vehicle_snapshot"]["vehicles"]:
            spatial, telemetry = row.setdefault("spatial", {}), row.setdefault("telemetry", {})
            raw = (spatial.get("raw_vehicle_local_pose") or {}).get("position_m") or {}
            first, last = before.get("local_position") or {}, observation.get("local_position") or {}
            coherent = (sample is not None and sample == observation.get("sample_timestamp")
                        and all(raw.get(axis) is not None and raw.get(axis) == first.get(field) == last.get(field)
                                for axis, field in (("x", "x_m"), ("y", "y_m"), ("z", "z_down_m"))))
            fresh_pose = position_fresh and coherent
            spatial.update({"sample_timestamp": sample if coherent else None, "source_timestamp": sample if coherent else None,
                            "sample_age_ms": position_age if coherent else None,
                            "stale": bool(spatial.get("stale", True)) or not fresh_pose})
            spatial["public_position_usable"] = bool(spatial.get("public_position_usable")) and fresh_pose
            if not fresh_pose:
                row["connected"] = False
                telemetry["stale"] = True
            ages = [age for age in (position_age, telemetry.get("age_ms")) if isinstance(age, (int, float))]
            telemetry["age_ms"] = max(ages) if ages else None
    return {"contract_version": "1.0", "node_id": service.node_id,
            "store_id": service.store.store_id, "run_id": service.run_id,
            "execution_mode": service.mode, "source_timestamp": stamp(service.clock()),
            "valid_for_ms": VIEW_VALID_MS, "execution_authorized": False, "projections": projections}


def validate_projections(projections):
    if not isinstance(projections, dict) or set(projections) != set(VIEW_PATHS):
        raise PlatformError("platform_view_invalid", 502)
    for key, row_key, identity in (("telemetry", "nodes", "node_id"), ("vehicles", "vehicles", "node_id"),
                                    ("runtime_snapshot", "nodes", "node_id"), ("vehicle_snapshot", "vehicles", "id")):
        value = projections[key]
        if not isinstance(value, dict) or not isinstance(value.get(row_key), list):
            raise PlatformError("platform_view_invalid", 502)
        rows = value[row_key]
        if len(rows) > 1 or any(not isinstance(row, dict) or row.get(identity) != "UAV-02" for row in rows):
            raise PlatformError("platform_view_node_mismatch", 502)
    for key in ("telemetry", "runtime_snapshot"):
        if any(row.get("source") != "px4_telemetry" or row.get("system_id") != 2 or row.get("component_id") != 1
               for row in projections[key]["nodes"]):
            raise PlatformError("platform_view_transport_mismatch", 502)
    registry = projections["vehicles"]["vehicles"]
    stale_after = projections["telemetry"].get("stale_after_ms")
    if type(stale_after) is not int or not 0 < stale_after <= 120000:
        raise PlatformError("platform_view_freshness_invalid", 502)
    if len(registry) != 1 or len(projections["vehicle_snapshot"]["vehicles"]) != 1:
        raise PlatformError("platform_view_node_missing", 502)
    if any(registry[0].get(key) != value for key, value in
           (("system_id", 2), ("component_id", 1), ("endpoint", "udpin:127.0.0.1:14541"))):
        raise PlatformError("platform_view_transport_mismatch", 502)
    if any(row.get("node_id") != "UAV-02" for row in projections["runtime_snapshot"].get("active_actions", [])):
        raise PlatformError("platform_view_node_mismatch", 502)


def aged_view(projections, *, elapsed_ms, fresh, stale_after_ms):
    """Age last-known values without clearing tasks, inventing samples or changing frames."""
    out = copy.deepcopy(projections)
    for key in ("telemetry", "runtime_snapshot", "vehicles"):
        payload = out.get(key) or {}
        for row in payload.get("nodes" if key != "vehicles" else "vehicles", []):
            age_key = "telemetry_freshness_ms" if key == "vehicles" else "age_ms"
            age = row.get(age_key)
            age = age + elapsed_ms if isinstance(age, (int, float)) and not isinstance(age, bool) else None
            row[age_key] = age
            usable = fresh and age is not None and age <= stale_after_ms and not row.get("stale", True)
            row["stale"] = not usable
            row["connected"] = bool(row.get("connected")) and usable
            if not fresh:
                row["observation_status"] = "unknown"
                if key == "vehicles":
                    row["connection_status"] = "unknown"
        if key == "telemetry":
            rows = payload.get("nodes", [])
            payload["fresh"] = bool(rows) and all(not r["stale"] for r in rows)
            payload["status"] = "ok" if payload["fresh"] else "stale" if rows else "unavailable"
            payload["age_ms"] = max((r["age_ms"] for r in rows if r.get("age_ms") is not None), default=None)
            if not payload["fresh"]:
                payload["reason"] = "platform_view_stale"
    for row in (out.get("vehicle_snapshot") or {}).get("vehicles", []):
        telemetry, spatial = row.setdefault("telemetry", {}), row.setdefault("spatial", {})
        age = telemetry.get("age_ms")
        age = age + elapsed_ms if isinstance(age, (int, float)) and not isinstance(age, bool) else None
        position_age = spatial.get("sample_age_ms")
        position_age = position_age + elapsed_ms if type(position_age) in (int, float) else None
        usable = (fresh and age is not None and age <= stale_after_ms and position_age is not None
                  and position_age <= stale_after_ms and not telemetry.get("stale", True))
        telemetry.update({"age_ms": age, "stale": not usable})
        spatial.update({"sample_age_ms": position_age, "stale": not usable})
        row["connected"] = bool(row.get("connected")) and usable
        cal_age, cal_valid = spatial.get("calibration_age_ms"), spatial.get("calibration_valid_for_ms")
        if type(cal_age) in (int, float) and type(cal_valid) in (int, float) and cal_age >= 0 and cal_valid > 0:
            spatial["calibration_age_ms"] = cal_age + elapsed_ms
            if cal_age + elapsed_ms > cal_valid:
                spatial["calibration_status"] = "stale"
        else:
            spatial["calibration_status"] = "unavailable"
        spatial["public_position_usable"] = (bool(spatial.get("public_position_usable")) and usable
                                              and spatial.get("calibration_status") == "calibrated")
        if not fresh:
            row["observation_status"] = "unknown"
    for row in (out.get("runtime_snapshot") or {}).get("active_actions", []):
        row["observation_stale"] = not fresh
    if not fresh:
        for row in (out.get("runtime_snapshot") or {}).get("backend_statuses", []):
            row.update({"connected": False, "readiness": "unknown", "observation_status": "unknown"})
    return out


def merge_projection(local, view, key):
    """Keep the old public endpoint and its shape, append only the remote owned node."""
    out = copy.deepcopy(local)
    remote = (view.get("projections") or {}).get(key) or {}
    identity = "id" if key == "vehicle_snapshot" else "node_id"
    rows_key = "vehicles" if key in {"vehicles", "vehicle_snapshot"} else "nodes"
    remote_rows = copy.deepcopy(remote.get(rows_key, []))
    if key == "vehicle_snapshot" and remote.get("scene_id") != local.get("scene_id"):
        for row in remote_rows:
            row.setdefault("spatial", {})["public_position_usable"] = False
            row["spatial"]["calibration_status"] = "scene_mismatch"
    out[rows_key] = sorted([r for r in out.get(rows_key, []) if r.get(identity) != "UAV-02"] + remote_rows,
                           key=lambda r: str(r.get(identity)))
    out["platform_view"] = {k: v for k, v in view.items() if k != "projections"}
    if key == "telemetry":
        rows = out["nodes"]
        out["fresh"] = bool(rows) and all(not r.get("stale", True) for r in rows)
        out["status"] = "ok" if out["fresh"] else "stale" if rows else "unavailable"
        out["age_ms"] = max((r["age_ms"] for r in rows if r.get("age_ms") is not None), default=None)
    elif key == "runtime_snapshot":
        remote_count = len(view.get("projections", {}).get("vehicles", {}).get("vehicles", []))
        out["fleet_summary"]["total_nodes"] = remote_count + local["fleet_summary"]["total_nodes"]
        out["fleet_summary"]["online_nodes"] = sum(bool(r.get("connected")) for r in out["nodes"])
        out["fleet_summary"]["armed_nodes"] = sum(bool(r.get("armed")) for r in out["nodes"])
        out["active_actions"] = [r for r in out.get("active_actions", []) if r.get("node_id") != "UAV-02"] + remote.get("active_actions", [])
        out["backend_statuses"] = [r for r in out.get("backend_statuses", []) if r.get("node_id") != "UAV-02"] + remote.get("backend_statuses", [])
    return out
