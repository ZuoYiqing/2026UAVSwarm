"""Action / Capability Registry v0.1 consistency tests."""
from __future__ import annotations

from uav_runtime.adapters.mavlink_mapping import SUPPORTED_MAVLINK_ACTIONS
from uav_runtime.adapters.payload_mapping import SUPPORTED_PAYLOAD_ACTIONS
from uav_runtime.policy.action_registry import (
    ACTION_CAPABILITY_REGISTRY,
    fallback_action_types,
    get_action_capability,
    unsafe_action_types,
)
from uav_runtime.policy.fallback_actions import LOST_LINK_FALLBACK_ACTIONS, UNSAFE_PAYLOAD_ACTIONS


def test_fallback_allowlist_actions_exist_in_registry() -> None:
    assert LOST_LINK_FALLBACK_ACTIONS <= set(ACTION_CAPABILITY_REGISTRY)


def test_payload_mapping_supported_actions_exist_in_registry() -> None:
    assert set(SUPPORTED_PAYLOAD_ACTIONS) <= set(ACTION_CAPABILITY_REGISTRY)
    for action in SUPPORTED_PAYLOAD_ACTIONS:
        cap = get_action_capability(action)
        assert cap is not None
        assert "payload" in cap.supported_adapters
        assert cap.dangerous is False


def test_mavlink_mapping_supported_actions_exist_in_registry() -> None:
    assert set(SUPPORTED_MAVLINK_ACTIONS) <= set(ACTION_CAPABILITY_REGISTRY)
    for action in SUPPORTED_MAVLINK_ACTIONS:
        cap = get_action_capability(action)
        assert cap is not None
        assert "mavlink" in cap.supported_adapters
        assert cap.domain == "flight"


def test_unsafe_actions_are_denied_metadata_and_not_adapter_supported() -> None:
    unsafe = {"payload_release", "drop", "deploy", "strike", "attack"}
    assert unsafe <= set(ACTION_CAPABILITY_REGISTRY)
    assert unsafe <= unsafe_action_types()

    for action in unsafe:
        cap = get_action_capability(action)
        assert cap is not None
        assert cap.dangerous is True
        assert cap.fallback_allowed is False
        assert cap.supported_adapters == ()
        assert cap.policy_default == "deny"
        assert action not in SUPPORTED_PAYLOAD_ACTIONS
        assert action not in SUPPORTED_MAVLINK_ACTIONS


def test_link_lost_fallback_actions_have_safe_registry_metadata() -> None:
    for action in LOST_LINK_FALLBACK_ACTIONS:
        cap = get_action_capability(action)
        assert cap is not None
        assert cap.fallback_allowed is True
        assert "lost" in cap.allowed_link_states
        assert cap.risk_level <= 1
        assert cap.dangerous is False


def test_registry_fallback_and_unsafe_sets_match_policy_taxonomy_core() -> None:
    assert fallback_action_types() == LOST_LINK_FALLBACK_ACTIONS
    assert {"payload_release", "drop", "deploy", "strike", "attack"} <= unsafe_action_types()
    assert {"payload_release", "drop", "deploy", "strike", "attack"} <= UNSAFE_PAYLOAD_ACTIONS


def test_capability_manifest_defaults_hide_dangerous_actions() -> None:
    from uav_runtime.policy.action_registry import capability_manifest

    manifest = capability_manifest()
    assert manifest
    action_types = {row["action_type"] for row in manifest}
    assert "payload_release" not in action_types
    assert "drop" not in action_types
    assert "strike" not in action_types

    required_fields = {
        "action_type",
        "domain",
        "skill_group",
        "risk_level",
        "supported_adapters",
        "fallback_allowed",
        "allowed_link_states",
        "requires_confirmation_by_default",
        "dangerous",
        "policy_default",
        "notes",
    }
    assert required_fields <= set(manifest[0])


def test_capability_manifest_can_include_dangerous_actions() -> None:
    from uav_runtime.policy.action_registry import capability_manifest

    action_types = {row["action_type"] for row in capability_manifest(include_dangerous=True)}
    assert {"payload_release", "drop", "strike", "attack"} <= action_types


def test_capability_manifest_filters_fallback_domain_and_adapter() -> None:
    from uav_runtime.policy.action_registry import capability_manifest

    fallback_rows = capability_manifest(fallback_only=True)
    assert fallback_rows
    assert all(row["fallback_allowed"] is True for row in fallback_rows)

    payload_rows = capability_manifest(domain="payload")
    assert payload_rows
    assert all(row["domain"] == "payload" for row in payload_rows)
    assert all(row["dangerous"] is False for row in payload_rows)

    mavlink_rows = capability_manifest(adapter="mavlink")
    assert mavlink_rows
    assert all("mavlink" in row["supported_adapters"] for row in mavlink_rows)
