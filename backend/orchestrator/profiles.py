from typing import Dict, Any

# Pre-defined configurations for different LLM execution modes.
# This prevents hardcoding temperatures and timeouts inside nodes.

LLM_PROFILES: Dict[str, Dict[str, Any]] = {
    "SQL_PROFILE": {
        "temperature": 0.0,
        "timeout": 45,
        "top_p": 0.9,
        "repeat_penalty": 1.1
    },
    "SUMMARY_PROFILE": {
        "temperature": 0.25,
        "timeout": 90,
        "top_p": 0.95,
        "repeat_penalty": 1.05
    },
    "VISION_PROFILE": {
        "temperature": 0.15,
        "timeout": 180,
        "top_p": 0.9,
        "repeat_penalty": 1.1
    }
}

def get_profile(profile_name: str) -> Dict[str, Any]:
    """Retrieves an LLM profile by name, defaulting to SUMMARY_PROFILE if not found."""
    return LLM_PROFILES.get(profile_name.upper(), LLM_PROFILES["SUMMARY_PROFILE"])
