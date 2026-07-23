"""
Confidence Engine — V2.3 Enterprise Intelligence Platform

Scores and GATES execution based on resolution confidence.

Thresholds:
  ≥ 0.75 → EXECUTE    (high confidence, proceed automatically)
  ≥ 0.50 → ASK_USER   (medium confidence, ask for clarification)
  <  0.50 → STOP       (low confidence, refuse gracefully)

The gate is an active decision, not just metadata.
"""

from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────────
# Thresholds
# ─────────────────────────────────────────────────────────────────
EXECUTE_THRESHOLD = 0.75
ASK_THRESHOLD = 0.50


@dataclass
class ConfidenceScore:
    """Composite confidence across pipeline stages."""
    intent_confidence: float = 0.0
    entity_candidates: List[Tuple[str, float]] = field(default_factory=list)  # [(col, score)]
    metric_candidates: List[Tuple[str, float]] = field(default_factory=list)  # [(col, score)]
    requires_entity: bool = True
    requires_metric: bool = True

    @property
    def entity_score(self) -> Optional[float]:
        """Best entity match score (0–100), normalised to 0–1."""
        if self.entity_candidates:
            return self.entity_candidates[0][1] / 100.0
        return None

    @property
    def metric_score(self) -> Optional[float]:
        """Best metric match score (0–100), normalised to 0–1."""
        if self.metric_candidates:
            return self.metric_candidates[0][1] / 100.0
        return None

    @property
    def overall(self) -> float:
        """
        Weighted overall confidence (0.0 – 1.0).
          LLM intent:    40%
          Entity match:  30%
          Metric match:  30%
        """
        score = self.intent_confidence * 0.40

        if self.requires_entity:
            score += (self.entity_score or 0.0) * 0.30
        else:
            score += 0.30  # entity not required → full marks

        if self.requires_metric:
            score += (self.metric_score or 0.0) * 0.30
        else:
            score += 0.30  # metric not required → full marks

        return round(min(score, 1.0), 3)

    @property
    def gate_decision(self) -> str:
        """
        Return the execution gate decision.
        "execute"  → ≥ 0.75 (high confidence)
        "ask_user" → ≥ 0.50 (needs clarification)
        "stop"     → < 0.50 (too uncertain)
        """
        if self.overall >= EXECUTE_THRESHOLD:
            return "execute"
        elif self.overall >= ASK_THRESHOLD:
            return "ask_user"
        return "stop"

    def build_clarification_message(self, question: str) -> str:
        """
        Build a user-facing message asking for clarification.
        Called when gate_decision == 'ask_user'.
        """
        lines = [
            f"I need a little clarification to answer **\"{question}\"** accurately.\n"
        ]

        # Show entity candidates if ambiguous
        if len(self.entity_candidates) > 1:
            top = self.entity_candidates[0][0]
            others = [c[0] for c in self.entity_candidates[1:3]]
            lines.append(
                f"**Column to group by:** I think you mean **{top}**, "
                f"but did you mean one of these instead? {others}"
            )

        # Show metric candidates if ambiguous
        if len(self.metric_candidates) > 1:
            top = self.metric_candidates[0][0]
            others = [c[0] for c in self.metric_candidates[1:3]]
            lines.append(
                f"**Metric to measure:** I think you mean **{top}**, "
                f"but did you mean one of these instead? {others}"
            )

        lines.append("\nPlease rephrase your question with the exact column names to proceed.")
        return "\n".join(lines)

    def build_stop_message(self, question: str) -> str:
        """
        Build a user-facing message when confidence is too low.
        Called when gate_decision == 'stop'.
        """
        return (
            f"I'm not confident enough to analyse **\"{question}\"** without more context.\n\n"
            f"**Confidence:** {self.overall:.0%}\n\n"
            "Please try:\n"
            "- Specifying exact column names (e.g. *'Revenue by Product'*)\n"
            "- Checking the file is a structured dataset (CSV/Excel)\n"
            "- Asking a more specific question"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall": self.overall,
            "gate_decision": self.gate_decision,
            "intent_confidence": round(self.intent_confidence, 3),
            "entity_candidates": self.entity_candidates,
            "metric_candidates": self.metric_candidates,
            "level": "high" if self.overall >= EXECUTE_THRESHOLD else (
                "medium" if self.overall >= ASK_THRESHOLD else "low"
            ),
        }

    def __repr__(self) -> str:
        return (
            f"ConfidenceScore(overall={self.overall:.2f} "
            f"gate={self.gate_decision} "
            f"intent={self.intent_confidence:.2f} "
            f"entity_best={self.entity_candidates[0] if self.entity_candidates else None} "
            f"metric_best={self.metric_candidates[0] if self.metric_candidates else None})"
        )
