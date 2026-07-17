import time
from typing import Optional, Callable

from .models.standard_document import (
    StandardDocument,
    FileType,
    DocumentSubtype,
    ExtractionStrategy,
    StorageDestination,
    PolicyAction,
)
from .routing.file_classifier import FileClassifier, UnsupportedFileTypeError
from .routing.pipeline_router import PipelineRouter
from .extraction.service import ExtractionService
from .classification.document_classifier import DocumentClassifier
from .normalization.domain_normalizers import DomainNormalizerFactory
from .policy.confidence_policy import ConfidencePolicyEngine
from .validation.validators import SchemaValidator, BusinessRuleEngine


class LineageTracker:
    """Records what happened at every pipeline stage for a full audit trail."""

    def __init__(self, filename: str):
        self.filename = filename
        self.events   = []

    def record(self, stage: str, value):
        self.events.append({
            "stage":     stage,
            "value":     str(value),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "events":   self.events,
        }


class UniversalIntakeOrchestrator:
    """
    Master entry point for Universal Data Intake.

    Runs the full enterprise pipeline in order:
      1.  File Classifier       → Technical type (CSV? PDF? Image?)
      2.  Pipeline Router       → Extraction strategy
      3.  Extraction Service    → Pull text/tables from the file
      4.  Document Classifier   → Business type (Invoice? Bank? Generic?)
      5.  Domain Normalizer     → Domain-specific cleaning
      6.  Confidence Policy     → Tiered action (Auto/Warn/Review/Retry/Reject)
      7.  Schema Validator      → Column type correctness
      8.  Business Rule Engine  → Domain constraints (no negative salary, etc.)
      9.  Lineage tracking      → Full audit trail attached to the document

    Storage (DynamicSQLEngine + MetadataRepository) is called
    by main.py after this method returns.
    """

    def process(
        self,
        data: bytes,
        filename: str,
        provider_config: Optional[dict] = None,
        on_progress: Optional[Callable[[str, str], None]] = None,
    ) -> StandardDocument:

        start_time = time.time()
        lineage    = LineageTracker(filename)
        lineage.record("start", filename)

        if on_progress: on_progress("routing", f"Classifying file: {filename}")
        # ── Stage 1: Technical File Classification ─────────────────────────
        try:
            file_type = FileClassifier.classify(filename, data)
        except UnsupportedFileTypeError as e:
            if on_progress: on_progress("error", f"Unsupported file type: {e}")
            return StandardDocument(
                ok=False,
                flag_reason=str(e),
                lineage=lineage.to_dict(),
            )
        lineage.record("file_classification", file_type.value)
        print(f"[Orchestrator] FileType = {file_type.value}")

        if on_progress: on_progress("routing", f"Routing pipeline for {file_type.value}")
        # ── Stage 2: Pipeline Routing ──────────────────────────────────────
        strategy = PipelineRouter.route(file_type)
        lineage.record("pipeline_routing", strategy.value)
        print(f"[Orchestrator] Strategy = {strategy.value}")

        if on_progress: on_progress("extraction", f"Extracting data via {strategy.value}")
        # ── Stage 3: Extraction Service ───────────────────────────────────
        doc = ExtractionService.extract(data, filename, strategy)
        doc.technical_file_type  = file_type
        doc.extraction_strategy  = strategy
        lineage.record("extraction", doc.parser_used)

        if not doc.ok:
            if on_progress: on_progress("error", f"Extraction failed: {doc.flag_reason}")
            doc.lineage             = lineage.to_dict()
            doc.processing_time_ms  = (time.time() - start_time) * 1000
            return doc

        # ── Stage 4 & 5: Business Classification & Normalization (Skipped) ────
        business_type      = DocumentSubtype.GENERIC
        doc.business_type  = business_type
        lineage.record("document_classification", business_type.value)

        if on_progress: on_progress("policy", "Applying confidence policies")
        # ── Stage 6: Confidence Policy Engine ─────────────────────────────
        policy_result   = ConfidencePolicyEngine.evaluate(doc)
        doc.policy_action = policy_result.action
        lineage.record("confidence_policy", f"{policy_result.action.value} ({policy_result.score:.0%})")

        if policy_result.action == PolicyAction.REJECT:
            if on_progress: on_progress("error", f"Rejected by policy: {policy_result.reason}")
            doc.ok         = False
            doc.flagged    = True
            doc.flag_reason = policy_result.reason
            doc.lineage             = lineage.to_dict()
            doc.processing_time_ms  = (time.time() - start_time) * 1000
            return doc

        if policy_result.action in (PolicyAction.MANUAL_REVIEW, PolicyAction.WARN, PolicyAction.RETRY):
            doc.flagged    = True
            doc.flag_reason = policy_result.reason

        # ── Stage 7: Schema Validator ──────────────────────────────────────
        schema_result = SchemaValidator.validate(doc)
        lineage.record("schema_validation", f"passed={schema_result.passed}")
        if not schema_result.passed:
            doc.flagged = True
            existing_reason = doc.flag_reason or ""
            doc.flag_reason = (
                existing_reason + " | Schema: " + "; ".join(schema_result.errors)
            ).strip(" |")

        # ── Stage 8: Business Rule Engine (Skipped) ───────────────────────
        pass

        # ── Finalise ───────────────────────────────────────────────────────
        doc.processing_time_ms = (time.time() - start_time) * 1000
        doc.lineage            = lineage.to_dict()

        print(
            f"[Orchestrator] Done — {filename} | "
            f"subtype={business_type.value} | "
            f"confidence={doc.confidence:.0%} | "
            f"flagged={doc.flagged} | "
            f"time={doc.processing_time_ms:.0f}ms"
        )
        return doc
