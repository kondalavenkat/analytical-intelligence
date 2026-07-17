from ..models.standard_document import DocumentSubtype


# Keyword sets for each business document type
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "invoice": [
        "invoice", "bill to", "ship to", "gstin", "gst no", "tax invoice",
        "hsn", "invoice no", "invoice number", "total amount", "sgst", "cgst",
        "igst", "vendor", "supplier", "due date", "purchase order",
    ],
    "bank_statement": [
        "opening balance", "closing balance", "debit", "credit", "transaction",
        "balance", "utr", "ifsc", "account number", "bank statement",
        "withdrawal", "deposit", "statement period", "available balance",
    ],
    "salary_slip": [
        "gross salary", "net salary", "net pay", "basic salary", "basic pay",
        "employee id", "emp id", "pf deduction", "provident fund", "hra",
        "house rent allowance", "salary slip", "payslip", "tds", "ctc",
        "month", "employer", "employee",
    ],
    "receipt": [
        "receipt", "total paid", "payment received", "thank you for your purchase",
        "amount paid", "cash", "mode of payment", "receipt no",
    ],
    "knowledge": [
        "circular", "policy", "sop", "standard operating procedure",
        "guidelines", "regulation", "notification", "rbi", "sebi",
        "compliance", "mandate", "directive", "amendment",
    ],
    "report": [
        "executive summary", "quarterly report", "annual report", "kpi",
        "key performance", "revenue", "profit", "loss", "ebitda",
        "management report", "board report", "financial report",
    ],
}


class DocumentClassifier:
    """
    Stage 4: Business-type classification from extracted text content.
    Answers: WHAT is this document for the business?

    This runs AFTER extraction because the file extension tells us nothing
    about business meaning. invoice.pdf and policy.pdf are both PDFs.
    
    Uses keyword scoring — fast, free, and surprisingly accurate.
    LLM-based classification is Phase 2.
    """

    @classmethod
    def classify(cls, text: str) -> DocumentSubtype:
        if not text or not text.strip():
            return DocumentSubtype.GENERIC

        text_lower = text.lower()
        scores: dict[str, int] = {}

        for domain, keywords in DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in keywords if kw in text_lower)

        best_domain = max(scores, key=scores.get)
        best_score  = scores[best_domain]

        print(f"[DocumentClassifier] Scores: {scores} → best='{best_domain}' ({best_score} hits)")

        if best_score == 0:
            return DocumentSubtype.GENERIC

        return DocumentSubtype(best_domain)
