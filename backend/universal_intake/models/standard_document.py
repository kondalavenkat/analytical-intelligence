from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import pandas as pd
from enum import Enum

class FileType(str, Enum):
    STRUCTURED = "structured"
    PDF_DIGITAL = "pdf_digital"
    PDF_SCANNED = "pdf_scanned"
    DOCUMENT = "document"
    IMAGE = "image"
    UNKNOWN = "unknown"

class DocumentSubtype(str, Enum):
    INVOICE = "invoice"
    BANK_STATEMENT = "bank_statement"
    SALARY_SLIP = "salary_slip"
    RECEIPT = "receipt"
    KNOWLEDGE = "knowledge"
    REPORT = "report"
    GENERIC = "generic"

class ExtractionStrategy(str, Enum):
    STRUCTURED = "structured"
    DOCUMENT = "document"
    IMAGE = "image"
    KNOWLEDGE = "knowledge"

class StorageDestination(str, Enum):
    SQL_DATABASE = "sql_database"
    VECTOR_DB = "vector_db"
    OBJECT_STORE = "object_store"

class PolicyAction(str, Enum):
    AUTO_PROCESS = "auto_process"
    WARN = "warn"
    MANUAL_REVIEW = "manual_review"
    RETRY = "retry"
    REJECT = "reject"

@dataclass
class StandardDocument:
    """Universal DTO passed between all layers of the Universal Intake pipeline."""
    
    # Core Data
    ok: bool = True
    df: Optional[pd.DataFrame] = None
    row_count: int = 0
    col_count: int = 0
    columns: List[str] = field(default_factory=list)
    preview: List[List[str]] = field(default_factory=list)
    file_type_ext: str = ""
    
    # Classification Metadata
    technical_file_type: FileType = FileType.UNKNOWN
    business_type: DocumentSubtype = DocumentSubtype.GENERIC
    extraction_strategy: ExtractionStrategy = ExtractionStrategy.STRUCTURED
    storage_destination: StorageDestination = StorageDestination.SQL_DATABASE
    
    # Extraction Metadata
    parser_used: str = ""
    ocr_used: bool = False
    llm_used: bool = False
    raw_text: Optional[str] = None
    page_count: Optional[int] = None
    
    # Quality & Governance
    confidence: float = 1.0
    policy_action: PolicyAction = PolicyAction.AUTO_PROCESS
    flagged: bool = False
    flag_reason: Optional[str] = None
    business_rule_violations: List[str] = field(default_factory=list)
    
    # Lineage & Audit
    processing_time_ms: float = 0.0
    lineage: Dict[str, Any] = field(default_factory=dict)
    
    # Backward Compatibility (for multi-sheet Excel)
    sheet_name: Optional[str] = None
    sheet_names: Optional[List[str]] = None
    sheets: Optional[Dict[str, Any]] = None

    def can_retry_with_different_engine(self) -> bool:
        """Determines if a retry is possible (e.g. Tesseract -> LLM Vision)."""
        return self.ocr_used and not self.llm_used
