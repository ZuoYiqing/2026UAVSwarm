"""Versioned, non-authorizing HTTP envelope for planner previews."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, get_args

if TYPE_CHECKING:
    from uav_runtime.agent.planner import PlanResult


IntentSource = Literal["explicit", "rules", "local_model", "none"]
PlanSource = Literal["template", "algorithm", "none"]
FallbackReason = Literal["model_unavailable", "model_invalid_output", "model_abstained", "model_low_confidence"]

PLAN_PREVIEW_CONTRACT_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class PlanPreviewProvenance:
    """Supplied by the producer that actually ran, never by the HTTP caller."""

    intent_source: IntentSource
    plan_source: PlanSource
    fallback_reason: FallbackReason | None = None

    def __post_init__(self) -> None:
        if self.intent_source not in ("explicit", "rules", "local_model", "none"):
            raise ValueError("invalid_preview_intent_source")
        if self.plan_source not in ("template", "algorithm", "none"):
            raise ValueError("invalid_preview_plan_source")
        if self.intent_source == "none" and self.plan_source != "none":
            raise ValueError("preview_plan_requires_resolved_intent")
        if self.fallback_reason is not None:
            if self.fallback_reason not in get_args(FallbackReason):
                raise ValueError("invalid_preview_fallback_reason")
            if self.intent_source not in ("rules", "none"):
                raise ValueError("invalid_preview_fallback_intent_source")

    @classmethod
    def after_model_fallback(
        cls,
        *,
        intent_source: Literal["rules", "none"],
        plan_source: PlanSource,
        reason: FallbackReason,
    ) -> PlanPreviewProvenance:
        """For an actual downgrade, require its cause even if no plan results."""
        if reason is None:
            raise ValueError("preview_fallback_reason_required")
        return cls(intent_source=intent_source, plan_source=plan_source, fallback_reason=reason)


def serialize_plan_preview(result: PlanResult, provenance: PlanPreviewProvenance) -> dict[str, Any]:
    if (result.plan is None) != (provenance.plan_source == "none"):
        raise ValueError("preview_plan_source_mismatch")
    return {
        **result.to_dict(),
        "contract_version": PLAN_PREVIEW_CONTRACT_VERSION,
        "intent_source": provenance.intent_source,
        "plan_source": provenance.plan_source,
        "fallback_reason": provenance.fallback_reason,
        "execution_authorized": False,
    }
