"""Diagnostic reads through existing sessions; never a flight authorization."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from uav_runtime.http.state_store import finite_json
from uav_runtime.runtime.vehicle_registry import VehicleRegistryError


def _observations(registry: Any, selected: Any) -> tuple[dict[str, Any], list[str]]:
    nodes, reasons = {}, []
    for handle in registry.list_vehicles():
        session = handle.session
        state = session.autonomous_state()
        with handle.state_lock:
            busy = bool(handle.runtime_state.active_action or handle.runtime_state.autonomous_action_id)
        persistent = bool(session.connected and session.connection is not None
                          and session.receive_owner_count() == 1 and session.heartbeat_thread_alive())
        disarmed = state.get("fresh") is True and state.get("armed") is False
        nodes[handle.config.node_id] = {
            "system_id": handle.config.system_id, "component_id": handle.config.component_id,
            "endpoint": handle.config.endpoint, "persistent_session": persistent,
            "fresh_disarmed": disarmed, "busy": busy, "state_evidence": state,
        }
        if not persistent:
            reasons.append(f"persistent_session_unavailable:{handle.config.node_id}")
        if not disarmed:
            reasons.append(f"fresh_disarmed_evidence_unavailable:{handle.config.node_id}")
        if busy:
            reasons.append(f"node_busy:{handle.config.node_id}")
        if handle is selected and not (state.get("landed_fresh") is True and state.get("landed_state") == 1):
            reasons.append("fresh_landed_evidence_unavailable")
    return nodes, reasons


def _check_preflight(registry: Any, store: Any, node_id: str) -> dict[str, Any]:
    """Read HOME/config, never connect, arm, set mode, or write parameters.

    A disconnected or busy node is not probed with a temporary connection.
    This point-in-time report must never be used as Policy admission or a
    promise that the next flight will complete. Ground evidence is re-read
    after queries because health/calibration can expire during the wait.
    """
    handle, _ = registry.resolve_vehicle(node_id)
    output: dict[str, Any] = {
        "contract_version": "1.0", "preflight_id": f"preflight-{uuid4()}",
        "node_id": node_id, "source": "runtime_persistent_session",
        "status": "not_ready", "execution_authorized": False, "flight_command_sent": False,
        "home_evidence": None, "rtl_destination_evidence": None,
        "ground_context": None, "error_class": None,
    }
    nodes, reasons = _observations(registry, handle)
    context = store.ground_landing_context(node_id)
    if context is None:
        reasons.append("ground_reference_unavailable")
    if not reasons:
        # Nonblocking diagnostics must never queue behind a flight action.
        locks = []
        try:
            for lock in (handle.command_lock, handle.session.command_lock):
                if not lock.acquire(blocking=False):
                    reasons.append(f"node_busy:{node_id}")
                    break
                locks.append(lock)
            if not reasons:
                nodes, reasons = _observations(registry, handle)
                if not reasons:
                    home = handle.session.request_home_position(timeout_s=2.0)
                    output["home_evidence"] = home
                    if home.get("verified") is not True:
                        reasons.append(str(home.get("failure_reason") or "home_position_unverified"))
                    else:
                        error = home.get("crosscheck_error_m")
                        if (isinstance(error, bool) or not isinstance(error, (int, float))
                                or not math.isfinite(error) or not 0 <= error < 0.75):
                            reasons.append("home_position_uncertainty_exceeds_tolerance")
                    # Recheck isolation before the second query, too.
                    nodes, current_reasons = _observations(registry, handle)
                    reasons.extend(current_reasons)
                    if not current_reasons:
                        destination = handle.session.verify_home_rtl_destination(timeout_s=2.0)
                        output["rtl_destination_evidence"] = destination
                        if destination.get("verified") is not True:
                            reasons.append(str(destination.get("failure_reason") or "rtl_destination_unverified"))
        except Exception as exc:
            reasons.append("preflight_query_exception")
            output["error_class"] = type(exc).__name__
        finally:
            for lock in reversed(locks):
                lock.release()
    nodes, current_reasons = _observations(registry, handle)
    reasons.extend(current_reasons)
    current = store.ground_landing_context(node_id)
    if current is None:
        reasons.append("ground_reference_unavailable")
    elif context is not None:
        if (current[0].get("calibration_version") != context[0].get("calibration_version")
                or current[1] != context[1]):
            reasons.append("ground_reference_changed_or_stale")
        output["ground_context"] = {
            "calibration_version": current[0].get("calibration_version"),
            "local_origin_id": current[0].get("local_origin_id"),
            "run_id": (current[0].get("context") or {}).get("run_id"),
            "ground_reference": current[1],
        }
    if output["home_evidence"] is None or output["rtl_destination_evidence"] is None:
        reasons.append("home_or_rtl_not_checked")
    output.update({"timestamp": datetime.now(timezone.utc).isoformat(), "nodes": nodes,
                   "reason_codes": sorted(set(reasons)), "status": "ready" if not reasons else "not_ready"})
    return finite_json(output)


def check_preflight(registry: Any, store: Any, node_id: str) -> dict[str, Any]:
    try:
        return _check_preflight(registry, store, node_id)
    except VehicleRegistryError:
        raise
    except Exception as exc:
        # Initial/final cache failures are diagnostics too. Never reconnect or
        # infer readiness when a source cannot supply its evidence.
        return {
            "contract_version": "1.0", "preflight_id": f"preflight-{uuid4()}",
            "timestamp": datetime.now(timezone.utc).isoformat(), "node_id": node_id,
            "source": "runtime_persistent_session", "status": "not_ready",
            "execution_authorized": False, "flight_command_sent": False,
            "nodes": {}, "home_evidence": None, "rtl_destination_evidence": None,
            "ground_context": None, "reason_codes": ["preflight_query_exception"],
            "error_class": type(exc).__name__,
        }
