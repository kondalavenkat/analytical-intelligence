from dataclasses import dataclass
from ..models.standard_document import StandardDocument, DocumentSubtype, PolicyAction


@dataclass
class PolicyResult:
    action: PolicyAction
    score: float
    threshold: float
    document_subtype: str
    reason: str | None = None


# ── Per-document-type confidence thresholds ───────────────────────────────────
# Configurable here. Could also be loaded from DB/config file in Phase 2.
CONFIDENCE_THRESHOLDS: dict[str, float] = {
    "invoice":        0.95,   # Financial document — very high
    "bank_statement": 0.98,   # Banking critical — strictest
    "salary_slip":    0.92,   # Payroll — high
    "receipt":        0.85,   # Medium-high
    "report":         0.80,   # Medium
    "knowledge":      0.70,   # Informational — lower
    "generic":        0.75,   # Default
}


class ConfidencePolicyEngine:
    """
    Evaluates extracted document confidence against per-document-type thresholds.

    Returns a tiered PolicyAction:

    | Confidence        | Action                       |
    |-------------------|------------------------------|
    | >= threshold      | AUTO_PROCESS                 |
    | >= threshold - 10%| AUTO_PROCESS + WARN logged   |
    | >= 70%            | MANUAL_REVIEW (user approval)|
    | >= 50%            | RETRY (try different engine) |
    | < 50%             | REJECT                       |
    """

    @classmethod
    def evaluate(cls, doc: StandardDocument) -> PolicyResult:
        from ..models.standard_document import FileType
        
        # Bypass confidence checks for structured data (e.g. databases, CSVs)
        if doc.technical_file_type == FileType.STRUCTURED:
            return PolicyResult(
                action=PolicyAction.AUTO_PROCESS,
                score=1.0,
                threshold=0.0,
                document_subtype="generic",
            )
            
        subtype    = doc.business_type.value if doc.business_type else "generic"
        threshold  = CONFIDENCE_THRESHOLDS.get(subtype, 0.75)
        score      = doc.confidence

        print(f"[ConfidencePolicyEngine] subtype={subtype}, "
              f"score={score:.1%}, threshold={threshold:.1%}")

        if score >= threshold:
            return PolicyResult(
                action=PolicyAction.AUTO_PROCESS,
                score=score,
                threshold=threshold,
                document_subtype=subtype,
            )

        warn_threshold = threshold - 0.10
        if score >= warn_threshold:
            return PolicyResult(
                action=PolicyAction.WARN,
                score=score,
                threshold=threshold,
                document_subtype=subtype,
                reason=(
                    f"Confidence {score:.0%} is slightly below the required "
                    f"{threshold:.0%} for {subtype}. Warning logged."
                ),
            )

        if score >= 0.70:
            return PolicyResult(
                action=PolicyAction.MANUAL_REVIEW,
                score=score,
                threshold=threshold,
                document_subtype=subtype,
                reason=(
                    f"{subtype.replace('_', ' ').title()} requires "
                    f"{threshold:.0%} confidence. Got {score:.0%}. "
                    "Manual review is required before processing."
                ),
            )

        if score >= 0.50:
            return PolicyResult(
                action=PolicyAction.RETRY,
                score=score,
                threshold=threshold,
                document_subtype=subtype,
                reason=(
                    f"OCR confidence too low ({score:.0%}). "
                    "Retrying with fallback extraction engine."
                ),
            )

        return PolicyResult(
            action=PolicyAction.REJECT,
            score=score,
            threshold=threshold,
            document_subtype=subtype,
            reason=(
                f"Confidence {score:.0%} is critically low. "
                "Document rejected. Please upload a clearer image."
            ),
        )
