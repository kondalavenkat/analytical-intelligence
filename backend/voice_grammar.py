"""
voice_grammar.py
─────────────────────────────────────────────────────────────────────
Grammar Fix layer for Whisper transcriptions.

Pipeline (applied in order):
  1. SQL vocabulary correction  – fixes mis-heard SQL/data terms
  2. Typo correction            – common phonetic confusions
  3. Number-word normalisation  – "five" → "5", "twenty three" → "23"
  4. Date-expression handling   – "last quarter" → contextual date range
  5. Punctuation cleanup        – removes stutter artefacts, trims spaces
  6. Optional Ollama refinement – full sentence polish via local LLM

Usage:
    from voice_grammar import fix_transcription, refine_with_ollama

    clean = fix_transcription(raw_text)
    better = refine_with_ollama(clean)   # optional, requires Ollama
"""

import re
import datetime
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# 1. SQL VOCABULARY DICTIONARY
#    Keys are regex patterns (case-insensitive), values are replacements.
#    Ordered from most-specific to most-general to avoid false positives.
# ─────────────────────────────────────────────────────────────────────────────

SQL_VOCAB: dict[str, str] = {
    # Aggregation & functions
    r"\bsum of\b":              "SUM",
    r"\bcount of\b":            "COUNT",
    r"\bcount star\b":          "COUNT(*)",
    r"\baverage of\b":          "AVG",
    r"\bmaximum of\b":          "MAX",
    r"\bminimum of\b":          "MIN",
    r"\bgroup bye\b":           "GROUP BY",
    r"\bgroup by\b":            "GROUP BY",
    r"\border bye\b":           "ORDER BY",
    r"\border by\b":            "ORDER BY",
    r"\bhaving clause\b":       "HAVING",
    r"\bwhere clause\b":        "WHERE",
    r"\binner join\b":          "INNER JOIN",
    r"\bleft join\b":           "LEFT JOIN",
    r"\bright join\b":          "RIGHT JOIN",
    r"\bfull join\b":           "FULL OUTER JOIN",
    r"\bjoin on\b":             "JOIN ON",
    r"\bunion all\b":           "UNION ALL",
    r"\bdistinct\b":            "DISTINCT",
    r"\blimit\b":               "TOP",
    # Comparison operators (spoken forms)
    r"\bgreater than or equal\b":  ">=",
    r"\bless than or equal\b":     "<=",
    r"\bgreater than\b":           ">",
    r"\bless than\b":              "<",
    r"\bnot equal\b":              "!=",
    r"\bequals\b":                 "=",
    r"\bis null\b":                "IS NULL",
    r"\bis not null\b":            "IS NOT NULL",
    r"\bbetween\b":                "BETWEEN",
    # Common Fintech/data column terms mis-heard by Whisper
    r"\brev you\b":             "revenue",
    r"\brev new\b":             "revenue",
    r"\brevenue\b":             "revenue",
    r"\btrans action\b":        "transaction",
    r"\btransaction\b":         "transaction",
    r"\bcust omer\b":           "customer",
    r"\bcustomer i d\b":        "customer_id",
    r"\bproduct i d\b":         "product_id",
    r"\border i d\b":           "order_id",
    r"\buser i d\b":            "user_id",
    r"\bcreated at\b":          "created_at",
    r"\bupdated at\b":          "updated_at",
    r"\btime stamp\b":          "timestamp",
    r"\bdate time\b":           "datetime",
    r"\bpercent age\b":         "percentage",
    r"\bprofit margin\b":       "profit_margin",
    r"\bsales amount\b":        "sales_amount",
    r"\btotal amount\b":        "total_amount",
    r"\bunit price\b":          "unit_price",
    r"\bquantity\b":            "quantity",
    r"\bcategory\b":            "category",
    r"\bregion\b":              "region",
    r"\bcountry code\b":        "country_code",
    # Table/schema navigation terms
    r"\bshow me\b":             "show me",
    r"\blist all\b":            "list all",
    r"\bfind all\b":            "find all",
    r"\bget all\b":             "get all",
    r"\btop (\d+)\b":           r"top \1",
    r"\bfirst (\d+)\b":         r"top \1",
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. TYPO / PHONETIC CORRECTION TABLE
#    Whisper sometimes mis-hears short words; these are phonetic mappings.
# ─────────────────────────────────────────────────────────────────────────────

PHONETIC_FIXES: dict[str, str] = {
    r"\bselect\b":    "select",
    r"\bsalect\b":    "select",
    r"\bsalact\b":    "select",
    r"\bfrom\b":      "from",
    r"\bfrum\b":      "from",
    r"\bfrome\b":     "from",
    r"\bwhere\b":     "where",
    r"\bwear\b":      "where",
    r"\bwer\b":       "where",
    r"\bjoin\b":      "join",
    r"\bjoine\b":     "join",
    r"\bjoyn\b":      "join",
    r"\btabel\b":     "table",
    r"\btable\b":     "table",
    r"\bcolum\b":     "column",
    r"\bcolumn\b":    "column",
    r"\bkolumn\b":    "column",
    r"\bdatbase\b":   "database",
    r"\bdatabaes\b":  "database",
    r"\bquerry\b":    "query",
    r"\bqery\b":      "query",
    r"\bquery\b":     "query",
    r"\brecord\b":    "record",
    r"\brecored\b":   "record",
    r"\bindeks\b":    "index",
    r"\bindec\b":     "index",
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. NUMBER-WORD NORMALISATION
#    Converts spoken numbers to digits (supports up to 999 billion).
# ─────────────────────────────────────────────────────────────────────────────

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_MULTIPLIERS = {
    "hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000,
}


def _words_to_number(text: str) -> Optional[int]:
    """Convert a string of number words to an integer. Returns None on failure."""
    words = text.lower().replace("-", " ").split()
    total = 0
    current = 0
    try:
        for w in words:
            if w in _ONES:
                current += _ONES[w]
            elif w in _TENS:
                current += _TENS[w]
            elif w in _MULTIPLIERS:
                m = _MULTIPLIERS[w]
                if m >= 1000:
                    total += (current if current else 1) * m
                    current = 0
                else:
                    current *= m
            else:
                return None
        return total + current
    except Exception:
        return None


# Regex that matches sequences of number words (greedy)
_NUM_WORD_PATTERN = re.compile(
    r"\b("
    r"(?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|thousand|million|billion)[\s\-]?)+"
    r")\b",
    re.IGNORECASE,
)


def normalize_numbers(text: str) -> str:
    """Replace spoken number sequences with digits."""
    def replace_match(m: re.Match) -> str:
        phrase = m.group(1).strip()
        val = _words_to_number(phrase)
        return str(val) if val is not None else phrase

    return _NUM_WORD_PATTERN.sub(replace_match, text)


# ─────────────────────────────────────────────────────────────────────────────
# 4. DATE EXPRESSION HANDLING
#    Converts context-aware spoken date phrases into concrete date ranges.
# ─────────────────────────────────────────────────────────────────────────────

def _current_quarter() -> tuple[str, str]:
    now = datetime.date.today()
    q = (now.month - 1) // 3 + 1
    start_month = (q - 1) * 3 + 1
    end_month   = start_month + 2
    import calendar
    end_day = calendar.monthrange(now.year, end_month)[1]
    return (
        f"{now.year}-{start_month:02d}-01",
        f"{now.year}-{end_month:02d}-{end_day}",
    )


def _last_quarter() -> tuple[str, str]:
    now = datetime.date.today()
    q = (now.month - 1) // 3 + 1
    lq = q - 1 if q > 1 else 4
    year = now.year if q > 1 else now.year - 1
    start_month = (lq - 1) * 3 + 1
    end_month   = start_month + 2
    import calendar
    end_day = calendar.monthrange(year, end_month)[1]
    return (
        f"{year}-{start_month:02d}-01",
        f"{year}-{end_month:02d}-{end_day}",
    )


_DATE_PATTERNS: list[tuple[str, callable]] = [
    (
        r"\bthis\s+quarter\b",
        lambda _: f"between '{_current_quarter()[0]}' and '{_current_quarter()[1]}'",
    ),
    (
        r"\blast\s+quarter\b",
        lambda _: f"between '{_last_quarter()[0]}' and '{_last_quarter()[1]}'",
    ),
    (
        r"\bthis\s+year\b",
        lambda _: f"in {datetime.date.today().year}",
    ),
    (
        r"\blast\s+year\b",
        lambda _: f"in {datetime.date.today().year - 1}",
    ),
    (
        r"\bthis\s+month\b",
        lambda _: f"in {datetime.date.today().strftime('%Y-%m')}",
    ),
    (
        r"\blast\s+month\b",
        lambda _: (
            lambda d: f"in {d.strftime('%Y-%m')}"
        )(
            (datetime.date.today().replace(day=1) - datetime.timedelta(days=1))
        ),
    ),
    (
        r"\byesterday\b",
        lambda _: f"= '{(datetime.date.today() - datetime.timedelta(days=1)).isoformat()}'",
    ),
    (
        r"\btoday\b",
        lambda _: f"= '{datetime.date.today().isoformat()}'",
    ),
    (
        r"\blast\s+(\d+)\s+days?\b",
        lambda m: (
            f"between '{(datetime.date.today() - datetime.timedelta(days=int(m.group(1)))).isoformat()}' "
            f"and '{datetime.date.today().isoformat()}'"
        ),
    ),
    (
        r"\blast\s+30\s+days?\b",
        lambda _: (
            f"between '{(datetime.date.today() - datetime.timedelta(days=30)).isoformat()}' "
            f"and '{datetime.date.today().isoformat()}'"
        ),
    ),
    (
        r"\blast\s+7\s+days?\b",
        lambda _: (
            f"between '{(datetime.date.today() - datetime.timedelta(days=7)).isoformat()}' "
            f"and '{datetime.date.today().isoformat()}'"
        ),
    ),
    (
        r"\bq1\b",
        lambda _: f"between '{datetime.date.today().year}-01-01' and '{datetime.date.today().year}-03-31'",
    ),
    (
        r"\bq2\b",
        lambda _: f"between '{datetime.date.today().year}-04-01' and '{datetime.date.today().year}-06-30'",
    ),
    (
        r"\bq3\b",
        lambda _: f"between '{datetime.date.today().year}-07-01' and '{datetime.date.today().year}-09-30'",
    ),
    (
        r"\bq4\b",
        lambda _: f"between '{datetime.date.today().year}-10-01' and '{datetime.date.today().year}-12-31'",
    ),
]


def handle_date_expressions(text: str) -> str:
    """Replace spoken date expressions with concrete SQL-friendly date ranges."""
    for pattern, replacement_fn in _DATE_PATTERNS:
        def _replace(m: re.Match, fn=replacement_fn) -> str:
            try:
                return fn(m)
            except Exception:
                return m.group(0)
        text = re.sub(pattern, _replace, text, flags=re.IGNORECASE)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# 5. PUNCTUATION CLEANUP
#    Removes stutter repetitions, double spaces, leading/trailing noise.
# ─────────────────────────────────────────────────────────────────────────────

_STUTTER_RE     = re.compile(r"\b(\w+)(\s+\1){2,}\b", re.IGNORECASE)  # "the the the"
_DOUBLE_RE      = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)         # "the the"
_MULTI_SPACE_RE = re.compile(r"  +")
_LEADING_PUNCT  = re.compile(r"^[\s,.\-!?;:]+")
_TRAILING_PUNCT = re.compile(r"[\s,.\-!?;:]+$")
_UM_UH_RE       = re.compile(r"\b(um+|uh+|hmm+|err+|ahh*)\b", re.IGNORECASE)


def cleanup_punctuation(text: str) -> str:
    """Remove stutter artefacts, filler words, and normalise whitespace."""
    text = _UM_UH_RE.sub("", text)
    text = _STUTTER_RE.sub(r"\1", text)
    text = _DOUBLE_RE.sub(r"\1", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _LEADING_PUNCT.sub("", text)
    text = _TRAILING_PUNCT.sub("", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 6. OPTIONAL OLLAMA PROMPT REFINEMENT
#    Sends the cleaned text to a local Ollama model for final polishing.
#    Falls back gracefully if Ollama is unavailable.
# ─────────────────────────────────────────────────────────────────────────────

_OLLAMA_REFINE_PROMPT = (
    "You are a voice-to-SQL assistant. The user spoke a natural language data query "
    "that was transcribed by Whisper. Your job is to clean it up into a clear, "
    "grammatically correct, single-sentence data question — without answering it or "
    "writing SQL. Keep numbers, dates, and technical terms exactly as given. "
    "Return ONLY the cleaned sentence, no explanation.\n\n"
    "Transcription: {text}\n\nCleaned query:"
)


def refine_with_ollama(
    text: str,
    base_url: str = "http://localhost:11434",
    model: str = "llama3",
    timeout: int = 6,
) -> str:
    """
    Optionally refine the transcription using a local Ollama model.
    Returns the original text if Ollama is unavailable or times out.
    """
    try:
        import requests  # already in requirements.txt
        payload = {
            "model":  model,
            "prompt": _OLLAMA_REFINE_PROMPT.format(text=text),
            "stream": False,
        }
        resp = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=timeout,
        )
        if resp.status_code == 200:
            refined = resp.json().get("response", "").strip()
            return refined if refined else text
    except Exception:
        pass
    return text


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def fix_transcription(
    text: str,
    use_ollama: bool = False,
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3",
) -> str:
    """
    Full grammar-fix pipeline for a Whisper transcription.

    Steps:
      1. Punctuation cleanup  (filler words, stutter)
      2. Phonetic typo fixes
      3. SQL vocabulary mapping
      4. Number-word normalisation
      5. Date-expression expansion
      6. Final whitespace trim
      7. (Optional) Ollama refinement

    Args:
        text:             Raw transcription string from Whisper.
        use_ollama:       Whether to call the Ollama LLM for final polish.
        ollama_base_url:  Ollama server URL (default: localhost:11434).
        ollama_model:     Ollama model name (default: llama3).

    Returns:
        Cleaned, grammar-fixed transcription string.
    """
    if not text:
        return text

    # Step 1 – remove filler words and stutter
    text = cleanup_punctuation(text)

    # Step 2 – phonetic typo correction
    for pattern, replacement in PHONETIC_FIXES.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Step 3 – SQL vocabulary mapping
    for pattern, replacement in SQL_VOCAB.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Step 4 – number word → digit normalisation
    text = normalize_numbers(text)

    # Step 5 – date expression expansion
    text = handle_date_expressions(text)

    # Step 6 – final whitespace cleanup after all substitutions
    text = _MULTI_SPACE_RE.sub(" ", text).strip()

    # Step 7 – optional Ollama refinement
    if use_ollama:
        text = refine_with_ollama(text, base_url=ollama_base_url, model=ollama_model)

    return text
