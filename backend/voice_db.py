"""
backend/voice_db.py
─────────────────────────────────────────────────────────────────────────────
Database helpers for the Voice infrastructure:
  • ensure_voice_tables()      – creates/migrates voice_transcripts + voice_cache
  • save_transcript()          – insert one transcription record
  • get_transcripts()          – paginated history for a user
  • delete_transcript()        – remove one record by id
  • get_voice_cache()          – look up an audio hash in the cache table
  • save_voice_cache()         – insert a new cache entry
  • hit_voice_cache()          – increment hit_count on a cache row
  • list_voice_cache()         – admin view of all cache entries
  • delete_voice_cache_entry() – evict one entry (deletes file too)
  • flush_voice_cache()        – delete all cache entries + their files
"""

import os
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import text

# ─── Folder for raw audio files ───────────────────────────────────────────────
_VOICE_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "voice_cache"
)


def ensure_voice_cache_dir():
    """Create the voice_cache/ folder if it doesn't exist."""
    os.makedirs(_VOICE_CACHE_DIR, exist_ok=True)


def audio_cache_path(audio_hash: str) -> str:
    """Return the full file path for a cached audio file."""
    return os.path.join(_VOICE_CACHE_DIR, f"{audio_hash}.webm")


def hash_audio(audio_bytes: bytes) -> str:
    """Return SHA-256 hex digest of raw audio bytes."""
    return hashlib.sha256(audio_bytes).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# TABLE CREATION + MIGRATION
# ─────────────────────────────────────────────────────────────────────────────

def ensure_voice_tables(engine):
    """
    Idempotently create dbo.voice_transcripts and dbo.voice_cache.
    Also runs ALTER TABLE migrations to add any new columns to existing tables.
    Safe to call on every startup — all operations are guarded with IF NOT EXISTS.
    """
    ensure_voice_cache_dir()
    try:
        with engine.begin() as conn:

            # ── 1. voice_transcripts ────────────────────────────────────────
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_NAME = 'voice_transcripts'
                )
                CREATE TABLE dbo.voice_transcripts (
                    id             INT           IDENTITY(1,1) PRIMARY KEY,
                    user_id        INT           NULL,             -- FK to app_users.id
                    user_email     NVARCHAR(200) NOT NULL,         -- kept for fast display
                    raw_text       NVARCHAR(MAX) NOT NULL,
                    clean_text     NVARCHAR(MAX) NOT NULL,
                    latency_ms     FLOAT         NULL,
                    language       NVARCHAR(10)  NULL,
                    lang_prob      FLOAT         NULL,
                    hit_count      INT           NOT NULL DEFAULT 1,
                    created_at     DATETIME      NOT NULL DEFAULT GETDATE()
                )
            """))

            # ── Migration: add user_id if it doesn't exist ──────────────────
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns
                    WHERE object_id = OBJECT_ID('dbo.voice_transcripts')
                      AND name = 'user_id'
                )
                ALTER TABLE dbo.voice_transcripts ADD user_id INT NULL
            """))

            # ── Migration: drop whisper_model if it exists ──────────────────────
            conn.execute(text("""
                IF EXISTS (
                    SELECT 1 FROM sys.columns
                    WHERE object_id = OBJECT_ID('dbo.voice_transcripts')
                      AND name = 'whisper_model'
                )
                BEGIN
                    -- Remove default constraint if exists before dropping column
                    DECLARE @ConstraintName nvarchar(200)
                    SELECT @ConstraintName = Name 
                    FROM sys.default_constraints 
                    WHERE parent_object_id = OBJECT_ID('dbo.voice_transcripts') 
                      AND parent_column_id = (SELECT column_id FROM sys.columns WHERE object_id = OBJECT_ID('dbo.voice_transcripts') AND name = 'whisper_model')
                    IF @ConstraintName IS NOT NULL
                        EXEC('ALTER TABLE dbo.voice_transcripts DROP CONSTRAINT ' + @ConstraintName)
                    
                    ALTER TABLE dbo.voice_transcripts DROP COLUMN whisper_model
                END
            """))

            # ── Migration: add hit_count if it doesn't exist ────────────────
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns
                    WHERE object_id = OBJECT_ID('dbo.voice_transcripts')
                      AND name = 'hit_count'
                )
                ALTER TABLE dbo.voice_transcripts ADD hit_count INT NOT NULL DEFAULT 1
            """))

            # ── Migration: add index for user history queries ────────────────
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.indexes
                    WHERE object_id = OBJECT_ID('dbo.voice_transcripts')
                      AND name = 'IX_voice_transcripts_email_date'
                )
                CREATE NONCLUSTERED INDEX IX_voice_transcripts_email_date
                    ON dbo.voice_transcripts (user_email, created_at DESC)
            """))

            # ── 2. voice_cache ───────────────────────────────────────────────
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_NAME = 'voice_cache'
                )
                CREATE TABLE dbo.voice_cache (
                    id           INT           IDENTITY(1,1) PRIMARY KEY,
                    audio_hash   NVARCHAR(64)  NOT NULL UNIQUE,
                    file_path    NVARCHAR(512) NOT NULL,
                    raw_text     NVARCHAR(MAX) NOT NULL,
                    clean_text   NVARCHAR(MAX) NOT NULL,
                    hit_count    INT           NOT NULL DEFAULT 1,
                    expires_at   DATETIME      NOT NULL,
                    created_at   DATETIME      NOT NULL DEFAULT GETDATE(),
                    last_hit_at  DATETIME      NULL,
                    user_id      INT           NULL,     -- FK to app_users.id
                    user_email   NVARCHAR(200) NULL      -- who originally cached this
                )
            """))

            # ── Migration: rename created_by to user_email if needed ────────
            conn.execute(text("""
                IF EXISTS (
                    SELECT 1 FROM sys.columns
                    WHERE object_id = OBJECT_ID('dbo.voice_cache')
                      AND name = 'created_by'
                )
                EXEC sp_rename 'dbo.voice_cache.created_by', 'user_email', 'COLUMN'
            """))

            # ── Migration: add user_id if missing ─────────────────────────
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns
                    WHERE object_id = OBJECT_ID('dbo.voice_cache')
                      AND name = 'user_id'
                )
                ALTER TABLE dbo.voice_cache ADD user_id INT NULL
            """))

            # ── Migration: add user_email if missing ─────────────────────────
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns
                    WHERE object_id = OBJECT_ID('dbo.voice_cache')
                      AND name = 'user_email'
                )
                ALTER TABLE dbo.voice_cache ADD user_email NVARCHAR(200) NULL
            """))

            # ── Migration: add cache index for expiry cleanup ────────────────
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.indexes
                    WHERE object_id = OBJECT_ID('dbo.voice_cache')
                      AND name = 'IX_voice_cache_expires'
                )
                CREATE NONCLUSTERED INDEX IX_voice_cache_expires
                    ON dbo.voice_cache (expires_at)
            """))

        print("[voice_db] ✅ voice_transcripts and voice_cache tables ready.")
    except Exception as e:
        print(f"[voice_db] ❌ Table setup error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TRANSCRIPT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_transcript(engine, user_email: str, raw_text: str, clean_text: str,
                    latency_ms: float,
                    language: str = None, lang_prob: float = None,
                    user_id: int = None):
    """Insert one transcription record for a user, or update hit_count if similar match exists."""
    import difflib
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("""
                SELECT TOP 100 id, clean_text FROM dbo.voice_transcripts 
                WHERE user_email = :email
                ORDER BY created_at DESC
            """), {"email": user_email}).fetchall()

            best_match_id = None
            best_ratio = 0.0
            
            for row in rows:
                row_id, row_text = row
                ratio = difflib.SequenceMatcher(None, clean_text.lower(), row_text.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match_id = row_id

            if best_match_id and best_ratio >= 0.85:
                conn.execute(text("""
                    UPDATE dbo.voice_transcripts 
                    SET hit_count = hit_count + 1, created_at = GETDATE()
                    WHERE id = :id
                """), {"id": best_match_id})
            else:
                conn.execute(text("""
                    INSERT INTO dbo.voice_transcripts
                        (user_id, user_email, raw_text, clean_text, latency_ms,
                         language, lang_prob, hit_count)
                    VALUES
                        (:uid, :email, :raw, :clean, :ms, :lang, :prob, 1)
                """), {
                    "uid":   user_id,
                    "email": user_email,
                    "raw":   raw_text,
                    "clean": clean_text,
                    "ms":    latency_ms,
                    "lang":  language,
                    "prob":  lang_prob,
                })
    except Exception as e:
        print(f"[voice_db] save_transcript error: {e}")


def get_transcripts(engine, user_email: str,
                    page: int = 1, page_size: int = 20) -> dict:
    """Return paginated transcript history for one user, newest first."""
    try:
        offset = (page - 1) * page_size
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, raw_text, clean_text, latency_ms,
                       language, lang_prob, created_at, hit_count
                FROM dbo.voice_transcripts
                WHERE user_email = :email
                ORDER BY created_at DESC
                OFFSET :offset ROWS FETCH NEXT :size ROWS ONLY
            """), {
                "email":  user_email,
                "offset": offset,
                "size":   page_size,
            }).fetchall()

            total = conn.execute(text("""
                SELECT COUNT(*) FROM dbo.voice_transcripts
                WHERE user_email = :email
            """), {"email": user_email}).scalar()

        return {
            "transcripts": [
                {
                    "id":            r[0],
                    "raw_text":      r[1],
                    "clean_text":    r[2],
                    "latency_ms":    r[3],
                    "language":      r[4],
                    "lang_prob":     round(r[5], 3) if r[5] else None,
                    "created_at":    r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6]),
                    "hit_count":     r[7],
                }
                for r in rows
            ],
            "total":     total,
            "page":      page,
            "page_size": page_size,
        }
    except Exception as e:
        print(f"[voice_db] get_transcripts error: {e}")
        return {"transcripts": [], "total": 0, "page": page, "page_size": page_size}


def delete_transcript(engine, transcript_id: int, user_email: str):
    """Delete a transcript by id — scoped to the requesting user."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                DELETE FROM dbo.voice_transcripts
                WHERE id = :id AND user_email = :email
            """), {"id": transcript_id, "email": user_email})
    except Exception as e:
        print(f"[voice_db] delete_transcript error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# VOICE CACHE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_voice_cache(engine, audio_hash: str) -> dict | None:
    """
    Look up the audio hash in dbo.voice_cache.
    Returns the cached result dict or None if not found / expired.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, raw_text, clean_text, hit_count, expires_at, created_at
                FROM dbo.voice_cache
                WHERE audio_hash = :h
                  AND expires_at  > GETDATE()
            """), {"h": audio_hash}).fetchone()

        if row:
            return {
                "id":         row[0],
                "raw_text":   row[1],
                "clean_text": row[2],
                "hit_count":  row[3],
                "expires_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
                "created_at": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
            }
        return None
    except Exception as e:
        print(f"[voice_db] get_voice_cache error: {e}")
        return None


def save_voice_cache(engine, audio_bytes: bytes, audio_hash: str,
                     raw_text: str, clean_text: str,
                     ttl_hours: int = 24, user_email: str = None, user_id: int = None):
    """
    Persist audio file to disk and insert a cache row in dbo.voice_cache.
    ttl_hours controls how long before the entry expires (default 24 h).
    user_email is the user who originally created this cache entry.
    """
    ensure_voice_cache_dir()
    file_path = audio_cache_path(audio_hash)

    try:
        with open(file_path, "wb") as f:
            f.write(audio_bytes)
    except Exception as e:
        print(f"[voice_db] audio file write error: {e}")
        return

    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)

    try:
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM dbo.voice_cache WHERE audio_hash = :h
                )
                INSERT INTO dbo.voice_cache
                    (audio_hash, file_path, raw_text, clean_text,
                     hit_count, expires_at, user_id, user_email)
                VALUES
                    (:h, :path, :raw, :clean, 1, :exp, :uid, :uemail)
            """), {
                "h":      audio_hash,
                "path":   file_path,
                "raw":    raw_text,
                "clean":  clean_text,
                "exp":    expires_at,
                "uid":    user_id,
                "uemail": user_email,
            })
    except Exception as e:
        print(f"[voice_db] save_voice_cache error: {e}")


def hit_voice_cache(engine, cache_id: int):
    """Increment hit_count and update last_hit_at for a cache entry."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE dbo.voice_cache
                SET hit_count   = hit_count + 1,
                    last_hit_at = GETDATE()
                WHERE id = :id
            """), {"id": cache_id})
    except Exception as e:
        print(f"[voice_db] hit_voice_cache error: {e}")


def list_voice_cache(engine) -> list:
    """Return all cache entries (Admin view), newest first."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, audio_hash, clean_text, hit_count,
                       expires_at, created_at, last_hit_at, user_id, user_email
                FROM dbo.voice_cache
                ORDER BY created_at DESC
            """)).fetchall()
        return [
            {
                "id":          r[0],
                "audio_hash":  r[1][:12] + "…",
                "clean_text":  r[2],
                "hit_count":   r[3],
                "expires_at":  r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
                "created_at":  r[5].isoformat() if hasattr(r[5], "isoformat") else str(r[5]),
                "last_hit_at": r[6].isoformat() if r[6] and hasattr(r[6], "isoformat") else None,
                "user_id":     r[7],
                "user_email":  r[8],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[voice_db] list_voice_cache error: {e}")
        return []


def delete_voice_cache_entry(engine, entry_id: int):
    """Evict one cache entry — removes DB row AND the audio file from disk."""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT file_path FROM dbo.voice_cache WHERE id = :id
            """), {"id": entry_id}).fetchone()

        if row and row[0] and os.path.exists(row[0]):
            try:
                os.remove(row[0])
            except Exception as fe:
                print(f"[voice_db] file delete error: {fe}")

        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM dbo.voice_cache WHERE id = :id"
            ), {"id": entry_id})
    except Exception as e:
        print(f"[voice_db] delete_voice_cache_entry error: {e}")


def flush_voice_cache(engine):
    """Delete ALL cache entries and all audio files from disk."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT file_path FROM dbo.voice_cache"
            )).fetchall()

        for r in rows:
            if r[0] and os.path.exists(r[0]):
                try:
                    os.remove(r[0])
                except Exception:
                    pass

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM dbo.voice_cache"))

        print("[voice_db] 🗑️ Voice cache flushed.")
    except Exception as e:
        print(f"[voice_db] flush_voice_cache error: {e}")
