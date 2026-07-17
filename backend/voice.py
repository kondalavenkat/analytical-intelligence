"""
backend/voice.py
─────────────────────────────────────────────────────────────────────────────
Whisper transcription service with:
  • Hot-swappable model management
  • Audio cache (SHA-256 hash → DB + disk)
  • Transcript saving to dbo.voice_transcripts
  • Full grammar-fix pipeline via voice_grammar.py
"""

import io
import time
from faster_whisper import WhisperModel
from voice_grammar import fix_transcription

# ─────────────────────────────────────────────────────────────────────────────
# AVAILABLE MODELS
# ─────────────────────────────────────────────────────────────────────────────

AVAILABLE_MODELS = {
    "tiny.en":   {"size": "75 MB",   "speed": "fastest", "accuracy": "basic",    "language": "English only"},
    "base.en":   {"size": "145 MB",  "speed": "fast",    "accuracy": "good",     "language": "English only"},
    "small.en":  {"size": "465 MB",  "speed": "medium",  "accuracy": "better",   "language": "English only"},
    "medium.en": {"size": "1.5 GB",  "speed": "slow",    "accuracy": "best EN",  "language": "English only"},
    "large-v3":  {"size": "3 GB",    "speed": "slowest", "accuracy": "best",     "language": "Multilingual"},
}

# ─────────────────────────────────────────────────────────────────────────────
# MODEL STATE
# ─────────────────────────────────────────────────────────────────────────────

_model: WhisperModel | None = None
_active_model_name: str = "tiny.en"


def get_active_model_name() -> str:
    return _active_model_name


def preload_whisper_model(model_name: str = "tiny.en"):
    """Load (or hot-swap) the Whisper model into memory."""
    global _model, _active_model_name
    if _model is not None and _active_model_name == model_name:
        return  # already loaded
    print(f"[voice] Loading Whisper model: {model_name} ...")
    _model = WhisperModel(model_name, device="cpu", compute_type="int8")
    _active_model_name = model_name
    print(f"[voice] ✅ Whisper model '{model_name}' ready.")


def switch_model(model_name: str):
    """Hot-swap the active Whisper model at runtime (Admin only)."""
    if model_name not in AVAILABLE_MODELS:
        raise ValueError(f"Unknown model '{model_name}'. Choose from: {list(AVAILABLE_MODELS)}")
    preload_whisper_model(model_name)


# ─────────────────────────────────────────────────────────────────────────────
# TRANSCRIPTION
# ─────────────────────────────────────────────────────────────────────────────

def transcribe_audio(
    audio_bytes: bytes,
    use_ollama:    bool = False,
    ollama_model:  str  = "llama3",
    engine=None,
    user_email:    str  = None,
    user_id:       int  = None,   # ← NEW: int ID from app_users
    ttl_hours:     int  = 24,
) -> dict:
    """
    Transcribe audio bytes with Whisper, apply the grammar-fix pipeline,
    optionally cache the result, and save the transcript to the DB.

    Args:
        audio_bytes:  Raw audio bytes (webm / wav).
        use_ollama:   Enable optional Ollama LLM refinement.
        ollama_model: Ollama model name.
        engine:       SQLAlchemy engine for DB operations.
        user_email:   Logged-in user's email (for transcript history).
        ttl_hours:    How many hours to keep audio cache entry alive.

    Returns:
        dict with keys: text, raw_text, latency_ms, language,
                        language_probability, cached (bool), cache_id (int|None)
    """
    global _model, _active_model_name

    if _model is None:
        preload_whisper_model()

    # ── 1. Check audio cache ─────────────────────────────────────────────────
    cached_result = None
    audio_hash    = None

    if engine:
        from voice_db import hash_audio, get_voice_cache, hit_voice_cache
        audio_hash    = hash_audio(audio_bytes)
        cached_result = get_voice_cache(engine, audio_hash)

    if cached_result:
        # Cache HIT — no Whisper inference needed
        hit_voice_cache(engine, cached_result["id"])
        return {
            "text":                 cached_result["clean_text"],
            "raw_text":             cached_result["raw_text"],
            "latency_ms":           0.0,
            "language":             None,
            "language_probability": None,
            "cached":               True,
            "cache_id":             cached_result["id"],
        }

    # ── 2. Whisper inference ─────────────────────────────────────────────────
    start_time = time.time()
    audio_file = io.BytesIO(audio_bytes)
    segments, info = _model.transcribe(
        audio_file, 
        beam_size=5, 
        vad_filter=True, 
        vad_parameters=dict(min_silence_duration_ms=500)
    )
    raw_text = "".join([s.text for s in segments]).strip()

    # ── 3. Grammar-fix pipeline ──────────────────────────────────────────────
    clean_text = fix_transcription(
        raw_text,
        use_ollama=use_ollama,
        ollama_model=ollama_model,
    )

    latency_ms = round((time.time() - start_time) * 1000, 2)

    # ── 4. Save to audio cache (disk + DB) ───────────────────────────────────
    if engine and audio_hash:
        from voice_db import save_voice_cache
        save_voice_cache(
            engine,
            audio_bytes=audio_bytes,
            audio_hash=audio_hash,
            raw_text=raw_text,
            clean_text=clean_text,
            ttl_hours=ttl_hours,
            user_email=user_email,
            user_id=user_id,
        )

    # ── 5. Save transcript record to DB ──────────────────────────────────────────
    if engine and user_email:
        from voice_db import save_transcript
        save_transcript(
            engine,
            user_email=user_email,
            raw_text=raw_text,
            clean_text=clean_text,
            latency_ms=latency_ms,
            language=info.language,
            lang_prob=info.language_probability,
            user_id=user_id,         # ← NEW: populated for proper FK linkage
        )

    return {
        "text":                 clean_text,
        "raw_text":             raw_text,
        "latency_ms":           latency_ms,
        "language":             info.language,
        "language_probability": info.language_probability,
        "cached":               False,
        "cache_id":             None,
    }
