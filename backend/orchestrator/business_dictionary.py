"""
Business Dictionary — V2.3 Enterprise Intelligence Platform

Loads domain-specific vocabulary from knowledge/ JSON files.
Each domain file adds its own synonyms on top of the universal base.

Domain plug-in design: banking customers load banking.json,
retail customers load retail.json — no irrelevant terms loaded.
"""

import json
import os
from typing import Dict, List, Optional

# ─────────────────────────────────────────────────────────────────
# Knowledge directory
# ─────────────────────────────────────────────────────────────────

_KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "knowledge")

_AVAILABLE_DOMAINS = ["base", "retail", "banking", "hr", "healthcare", "insurance"]


def _load_domain_file(domain: str) -> Dict[str, List[str]]:
    """Load a single domain JSON file. Returns empty dict on failure."""
    path = os.path.join(_KNOWLEDGE_DIR, f"{domain}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Remove internal comment key
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}


def build_dictionary(domains: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """
    Build a merged business dictionary from the given domain files.
    Always loads 'base' first.
    """
    active_domains = ["base"] + [d for d in (domains or []) if d != "base"]
    merged: Dict[str, List[str]] = {}
    for domain in active_domains:
        domain_dict = _load_domain_file(domain)
        for canonical, synonyms in domain_dict.items():
            if canonical in merged:
                # Merge without duplicates
                existing = set(merged[canonical])
                merged[canonical] = list(existing | set(synonyms))
            else:
                merged[canonical] = list(synonyms)
    return merged


# ─────────────────────────────────────────────────────────────────
# Default dictionary — loads all domains (general purpose)
# ─────────────────────────────────────────────────────────────────

BUSINESS_DICTIONARY: Dict[str, List[str]] = build_dictionary(_AVAILABLE_DOMAINS)

# Inverted index: synonym (lowercase) → canonical term
_SYNONYM_TO_CANONICAL: Dict[str, str] = {}
for _canonical, _synonyms in BUSINESS_DICTIONARY.items():
    _SYNONYM_TO_CANONICAL[_canonical.lower()] = _canonical
    for _syn in _synonyms:
        _SYNONYM_TO_CANONICAL[_syn.lower()] = _canonical


def resolve_business_term(term: str) -> Optional[str]:
    """
    Resolve a business synonym to its canonical form.
    resolve_business_term("turnover") → "revenue"
    resolve_business_term("borrower") → "customer"
    resolve_business_term("xyz")      → None
    """
    return _SYNONYM_TO_CANONICAL.get(term.strip().lower())


def expand_term_variants(term: str) -> List[str]:
    """
    Return all equivalent terms for a given word.
    Used by Semantic Resolver to broaden column name matching.
    """
    canonical = resolve_business_term(term)
    if canonical:
        all_variants = [canonical] + BUSINESS_DICTIONARY.get(canonical, [])
        return list(dict.fromkeys(s.lower() for s in all_variants))  # preserve order, unique
    return [term.lower()]


def get_available_domains() -> List[str]:
    return _AVAILABLE_DOMAINS
