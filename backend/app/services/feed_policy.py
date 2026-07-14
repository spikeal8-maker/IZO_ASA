"""Pure publication eligibility rules for the public feed."""

from __future__ import annotations

from dataclasses import dataclass


BLOCKED_PUBLICATION_MODES = frozenset({"inpaint", "mask", "remove_background", "remove_bg"})
REVIEW_PUBLICATION_MODES = frozenset({
    "image_to_image",
    "edit",
    "outpaint",
    "faceswap",
    "try_on",
    "texture_transfer",
})
DIRECT_PUBLICATION_MODES = frozenset({"text_to_image", "paint", "sketch", "drawing_to_image"})


@dataclass(frozen=True)
class FeedPublicationDecision:
    state: str
    reason: str | None = None

    @property
    def blocked(self) -> bool:
        return self.state == "blocked"

    @property
    def requires_review(self) -> bool:
        return self.state == "pending_review"


def publication_decision(
    mode: str | None,
    *,
    has_verified_generation: bool,
) -> FeedPublicationDecision:
    normalized = str(mode or "").strip().lower()
    if not has_verified_generation:
        return FeedPublicationDecision("blocked", "generation_provenance_missing")
    if normalized in BLOCKED_PUBLICATION_MODES:
        return FeedPublicationDecision("blocked", f"source_mode_not_publishable:{normalized}")
    if normalized in REVIEW_PUBLICATION_MODES:
        return FeedPublicationDecision("pending_review", f"source_mode_requires_review:{normalized}")
    if normalized in DIRECT_PUBLICATION_MODES:
        return FeedPublicationDecision("approved")
    return FeedPublicationDecision("pending_review", f"source_mode_unknown:{normalized or 'missing'}")
