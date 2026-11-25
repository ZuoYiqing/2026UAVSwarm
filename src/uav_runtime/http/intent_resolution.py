"""Bind objective-only previews to a catalog from the active Runtime scene."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# Algorithm owns the original. Runtime imports a pinned, verbatim copy for
# offline deployment; the source/corpus hash pins are enforced by unit tests.
from uav_runtime.agent._vendor_intent_recognizer_v0 import (
    CatalogEntry,
    IntentParameters,
    RuleIntentRecognizer,
)


ResolutionStatus = Literal["resolved", "needs_clarification", "unsupported"]
_STATUSES: dict[str, ResolutionStatus] = {
    "bound": "resolved",
    "clarify": "needs_clarification",
    "unknown": "unsupported",
}


@dataclass(frozen=True, slots=True)
class _Catalog:
    scene_id: str
    map_version: str
    catalog_id: str
    entries: tuple[CatalogEntry, ...]
    preview_only_ids: frozenset[str]
    reference_only_ids: frozenset[str]

    def identity(self) -> dict[str, str]:
        return {"scene_id": self.scene_id, "map_version": self.map_version, "catalog_id": self.catalog_id}


@dataclass(frozen=True, slots=True)
class PreviewIntentResolution:
    status: ResolutionStatus
    reason_code: str
    mission_type: str | None = None
    question: str | None = None
    parameters: IntentParameters = field(default_factory=IntentParameters)
    catalog: _Catalog | None = None

    @property
    def intent_source(self) -> Literal["rules", "none"]:
        return "rules" if self.catalog is not None else "none"

    def bindings(self) -> dict[str, Any]:
        params = self.parameters
        preview_only = self.catalog.preview_only_ids if self.catalog is not None else frozenset()
        return {
            "targets": [asdict(binding) for binding in params.targets if binding.entity_id not in preview_only],
            "preview_only_targets": [asdict(binding) for binding in params.targets if binding.entity_id in preview_only],
            "reference_only": [asdict(binding) for binding in params.reference_only],
            "excluded_targets": [asdict(binding) for binding in params.excluded_targets],
            "only_listed_targets": params.only_listed_targets,
            "status_scope": params.status_scope,
        }

    def to_dict(self) -> dict[str, Any]:
        bindings = self.bindings()
        bindings["target_order_basis"] = self.parameters.target_order_basis
        # Splitting physical and preview-only roles preserves relative order, but
        # loses interleaving. Publish it only on the read-only wire projection.
        if bindings["targets"] and bindings["preview_only_targets"]:
            bindings["target_order"] = [binding.entity_id for binding in self.parameters.targets]
        return {
            "status": self.status,
            "mission_type": self.mission_type,
            "reason_code": self.reason_code,
            "question": self.question,
            "catalog": self.catalog.identity() if self.catalog is not None else None,
            "bindings": bindings,
        }

    def supports_template_outline(self) -> bool:
        """Only known binding shapes have a preview; guarded keys are explicit-only."""
        if self.status != "resolved":
            return False
        params = self.parameters
        if self.mission_type == "inspection_snapshot":
            return bool(params.targets) and params.status_scope is None
        if self.mission_type == "status_only":
            return (
                params.status_scope in {"online", "connection", "summary"}
                and params == IntentParameters(status_scope=params.status_scope)
            )
        if self.mission_type == "simple_takeoff_land":
            return params == IntentParameters()
        return False


class _CatalogError(ValueError):
    pass


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _catalog_role_ids(raw: dict[str, Any], key: str) -> frozenset[str]:
    ids = raw.get(key, [])
    if not isinstance(ids, list) or not all(_nonempty_text(entity_id) for entity_id in ids):
        raise _CatalogError("INTENT_CATALOG_INVALID")
    unique_ids = frozenset(ids)
    if len(unique_ids) != len(ids):
        raise _CatalogError("INTENT_CATALOG_INVALID")
    return unique_ids


def _catalog_from_scene(scene_id: str, scene: dict[str, Any] | None) -> _Catalog:
    # The caller supplies the loaded registry scene, never JSON from the
    # request. Do not infer labels from scene descriptions or from a test set.
    raw = scene.get("intent_catalog") if scene is not None else None
    if raw is None:
        raise _CatalogError("INTENT_CATALOG_UNAVAILABLE")
    if not isinstance(raw, dict) or raw.get("contract_version") != "1.0":
        raise _CatalogError("INTENT_CATALOG_INVALID")
    map_version = scene.get("map_version")
    if (not _nonempty_text(scene_id) or not _nonempty_text(map_version)
            or scene.get("scene_id") != scene_id or raw.get("scene_id") != scene_id
            or raw.get("map_version") != map_version):
        raise _CatalogError("INTENT_CATALOG_IDENTITY_MISMATCH")
    catalog_id, rows = raw.get("catalog_id"), raw.get("entries")
    if not _nonempty_text(catalog_id) or not isinstance(rows, list):
        raise _CatalogError("INTENT_CATALOG_INVALID")

    # Scene targets keep their physical meaning. An extra semantic entity
    # must be explicitly assigned a non-physical role by the scene producer.
    targets = scene.get("targets")
    if not isinstance(targets, list):
        raise _CatalogError("INTENT_CATALOG_INVALID")
    target_ids: set[str] = set()
    for row in targets:
        if not isinstance(row, dict) or not _nonempty_text(row.get("target_id")) or row["target_id"] in target_ids:
            raise _CatalogError("INTENT_CATALOG_INVALID")
        target_ids.add(row["target_id"])

    preview_only = _catalog_role_ids(raw, "preview_only_entity_ids")
    reference_only = _catalog_role_ids(raw, "reference_only_entity_ids")
    obstacles = scene.get("obstacles", [])
    if not isinstance(obstacles, list):
        raise _CatalogError("INTENT_CATALOG_INVALID")
    obstacle_ids = {
        row["obstacle_id"] for row in obstacles
        if isinstance(row, dict) and _nonempty_text(row.get("obstacle_id"))
    }
    if (preview_only & reference_only or target_ids & (preview_only | reference_only)
            or preview_only & obstacle_ids):
        raise _CatalogError("INTENT_CATALOG_INVALID")
    allowed_ids = target_ids | preview_only | reference_only

    entries = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise _CatalogError("INTENT_CATALOG_INVALID")
        entity_id, label = row.get("entity_id"), row.get("label")
        aliases, group = row.get("aliases", []), row.get("exclusive_group")
        if (not _nonempty_text(entity_id) or entity_id in seen or not _nonempty_text(label)
                or not isinstance(aliases, list) or not all(_nonempty_text(alias) for alias in aliases)
                or (group is not None and not _nonempty_text(group))):
            raise _CatalogError("INTENT_CATALOG_INVALID")
        if entity_id not in allowed_ids:
            raise _CatalogError("INTENT_CATALOG_ENTITY_NOT_IN_SCENE")
        entries.append(CatalogEntry(entity_id, label, tuple(aliases), group))
        seen.add(entity_id)
    if not (preview_only | reference_only) <= seen:
        raise _CatalogError("INTENT_CATALOG_INVALID")
    return _Catalog(scene_id, map_version, catalog_id, tuple(entries), preview_only, reference_only)


def resolve_preview_intent(
    objective: str, *, scene_id: str, scene: dict[str, Any] | None,
) -> PreviewIntentResolution:
    try:
        catalog = _catalog_from_scene(scene_id, scene)
    except _CatalogError as exc:
        return PreviewIntentResolution("unsupported", str(exc))

    recognized = RuleIntentRecognizer(catalog.entries).recognize(objective)
    params = recognized.parameters
    if any(binding.entity_id in catalog.reference_only_ids for binding in params.targets):
        # Never drop the disallowed target and silently preview a valid subset.
        return PreviewIntentResolution(
            status="needs_clarification",
            reason_code="TARGET_REFERENCE_ONLY",
            question="所选对象仅可作参照，不能作为巡检目标。请明确本轮要预览的目标。",
            parameters=IntentParameters(reference_only=params.reference_only, excluded_targets=params.excluded_targets),
            catalog=catalog,
        )
    return PreviewIntentResolution(
        status=_STATUSES[recognized.status],
        reason_code=recognized.reason_code,
        mission_type=recognized.mission_type,
        question=recognized.clarification,
        parameters=params,
        catalog=catalog,
    )
