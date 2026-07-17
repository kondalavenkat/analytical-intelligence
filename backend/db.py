"""
backend/db.py
─────────────────────────────────────────────────────────────────────────────
Centralised database layer — Schema v3  (8 tables)

Tables
  dbo.app_users          User auth + roles
  dbo.query_cache        Unified SQL + file analysis cache
  dbo.chat_log           Chat history + audit (sessions via UUID key)
  dbo.files              Base file metadata (parent of 3 child tables)
  dbo.structured_files   CSV / XLSX / XLS / JSON / TSV / XML
  dbo.document_files     PDF / DOCX / DOC / PPTX / PPT / TXT
  dbo.image_files        PNG / JPG / WEBP / BMP / TIFF / Scanned-PDF
  dbo.voice_log          Voice transcripts + audio cache (merged)

Views
  dbo.v_sessions         Session list (GROUP BY session_key)
  dbo.v_cache_stats      Cache dashboard with speedup_x column
  dbo.v_files            Unified file view (base + all 3 child tables)

Import this module instead of scattered functions in app_core.py / voice_db.py.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import text

# ─── Voice audio cache directory ─────────────────────────────────────────────
_VOICE_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_cache")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _hash(value: str) -> str:
    """SHA-256 hex of a string (passwords, prompts)."""
    return hashlib.sha256(value.encode()).hexdigest()


def hash_prompt(question: str) -> str:
    """Normalise and SHA-256 a user question for exact cache lookup."""
    return _hash(question.strip().lower())


def hash_file(data: bytes) -> str:
    """SHA-256 hex of raw file bytes."""
    return hashlib.sha256(data).hexdigest()


def hash_audio(audio_bytes: bytes) -> str:
    """SHA-256 hex of raw audio bytes."""
    return hashlib.sha256(audio_bytes).hexdigest()


def new_session_key() -> str:
    """Generate a new UUID-based session key (replaces chat_sessions INSERT)."""
    return str(uuid.uuid4())


def ensure_voice_cache_dir() -> None:
    os.makedirs(_VOICE_CACHE_DIR, exist_ok=True)


def audio_cache_path(audio_hash: str) -> str:
    return os.path.join(_VOICE_CACHE_DIR, f"{audio_hash}.webm")


def _file_category(file_type: str, parsed: dict = None) -> str:
    """Return broad category from exact extension. Upgrades to structured if a real table was extracted."""
    t = file_type.lower().lstrip(".")
    if parsed and parsed.get("row_count", 0) > 0:
        cols = parsed.get("columns", [])
        if len(cols) > 2 or (len(cols) == 2 and set(c.lower() for c in cols) != {"line_number", "content"}):
            return "structured"
    
    if t in {"csv", "xlsx", "xls", "json", "tsv", "xml"}:
        return "structured"
    if t in {"pdf", "docx", "doc", "pptx", "ppt", "txt"}:
        return "document"
    return "image_ocr"


# ══════════════════════════════════════════════════════════════════════════════
# STARTUP — create all 8 tables if they don't exist
# ══════════════════════════════════════════════════════════════════════════════

def ensure_all_tables(engine) -> None:
    """
    Idempotent startup: create all v3 tables + views if they don't exist.
    Run schema_v3.sql for a fresh install; this function handles day-2 startups.
    """
    ensure_voice_cache_dir()
    _ensure_app_users(engine)
    _ensure_query_cache(engine)
    _ensure_chat_log(engine)
    _ensure_files_tables(engine)
    _ensure_voice_log(engine)
    _ensure_views(engine)
    print("[db] ✅ All v3 tables verified.")


def _ensure_app_users(engine):
    with engine.begin() as c:
        c.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='app_users')
            CREATE TABLE dbo.app_users (
                id            INT           IDENTITY(1,1) PRIMARY KEY,
                username      NVARCHAR(200) NOT NULL UNIQUE,
                password_hash NVARCHAR(64)  NOT NULL,
                role          NVARCHAR(20)  NOT NULL DEFAULT 'Analyst',
                full_name     NVARCHAR(200) NULL,
                last_login    DATETIME      NULL,
                created_at    DATETIME      NOT NULL DEFAULT GETDATE()
            )
        """))


def _ensure_query_cache(engine):
    with engine.begin() as c:
        c.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='query_cache')
            CREATE TABLE dbo.query_cache (
                id              INT           IDENTITY(1,1) PRIMARY KEY,
                cache_type      NVARCHAR(10)  NOT NULL,
                prompt_hash     NVARCHAR(64)  NOT NULL,
                provider        NVARCHAR(100) NULL,
                model           NVARCHAR(100) NULL,
                user_question   NVARCHAR(MAX) NOT NULL,
                sql_query       NVARCHAR(MAX) NULL,
                raw_sql         NVARCHAR(MAX) NULL,
                embedding       NVARCHAR(MAX) NULL,
                file_id         BIGINT        NULL,
                chart_data      NVARCHAR(MAX) NULL,
                analysis        NVARCHAR(MAX) NULL,
                hit_count       INT           NOT NULL DEFAULT 0,
                run_count       INT           NOT NULL DEFAULT 1,
                first_exec_ms   FLOAT         NULL,
                cache_lookup_ms FLOAT         NULL,
                sql_rerun_ms    FLOAT         NULL,
                cached_exec_ms  FLOAT         NULL,
                created_at      DATETIME      NOT NULL DEFAULT GETDATE(),
                last_accessed   DATETIME      NULL
            )
        """))


def _ensure_chat_log(engine):
    with engine.begin() as c:
        c.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='chat_log')
            CREATE TABLE dbo.chat_log (
                id               BIGINT        IDENTITY(1,1) PRIMARY KEY,
                session_key      NVARCHAR(36)  NOT NULL,
                session_title    NVARCHAR(200) NULL,
                user_id          INT           NOT NULL,
                user_email       NVARCHAR(200) NOT NULL,
                question         NVARCHAR(MAX) NOT NULL,
                input_source     NVARCHAR(20)  NOT NULL DEFAULT 'keyboard',
                sql_query        NVARCHAR(MAX) NULL,
                analysis         NVARCHAR(MAX) NULL,
                row_count        INT           NULL,
                columns_json     NVARCHAR(MAX) NULL,
                cache_id         INT           NULL,
                source           NVARCHAR(10)  NULL,
                execution_status NVARCHAR(10)  NOT NULL DEFAULT 'SUCCESS',
                error            NVARCHAR(MAX) NULL,
                provider         NVARCHAR(100) NULL,
                model            NVARCHAR(100) NULL,
                exec_ms          FLOAT         NULL,
                created_at       DATETIME      NOT NULL DEFAULT GETDATE()
            )
        """))


def _ensure_files_tables(engine):
    with engine.begin() as c:
        # base
        c.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='files')
            CREATE TABLE dbo.files (
                id          BIGINT        IDENTITY(1,1) PRIMARY KEY,
                user_id     INT           NOT NULL,
                file_hash   NVARCHAR(64)  NOT NULL,
                file_name   NVARCHAR(255) NOT NULL,
                file_size   BIGINT        NOT NULL,
                file_type   NVARCHAR(10)  NOT NULL,
                category    NVARCHAR(12)  NOT NULL,
                sheet_name  NVARCHAR(255) NULL,
                uploaded_at DATETIME      NOT NULL DEFAULT GETDATE(),
                last_used   DATETIME      NULL,
                CONSTRAINT UQ_user_file UNIQUE (user_id, file_hash)
            )
        """))
        # structured child
        c.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='structured_files')
            CREATE TABLE dbo.structured_files (
                file_id      BIGINT        PRIMARY KEY,
                row_count    INT           NULL,
                col_count    INT           NULL,
                columns_json NVARCHAR(MAX) NULL,
                data_json    NVARCHAR(MAX) NULL,
                CONSTRAINT FK_sf FOREIGN KEY (file_id)
                    REFERENCES dbo.files(id) ON DELETE CASCADE
            )
        """))
        # document child
        c.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='document_files')
            CREATE TABLE dbo.document_files (
                file_id        BIGINT        PRIMARY KEY,
                page_count     INT           NULL,
                word_count     INT           NULL,
                extracted_text NVARCHAR(MAX) NULL,
                CONSTRAINT FK_df FOREIGN KEY (file_id)
                    REFERENCES dbo.files(id) ON DELETE CASCADE
            )
        """))
        # image child
        c.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='image_files')
            CREATE TABLE dbo.image_files (
                file_id        BIGINT PRIMARY KEY,
                width_px       INT    NULL,
                height_px      INT    NULL,
                ocr_text       NVARCHAR(MAX) NULL,
                ocr_confidence FLOAT  NULL,
                is_scanned_pdf BIT    NOT NULL DEFAULT 0,
                CONSTRAINT FK_if FOREIGN KEY (file_id)
                    REFERENCES dbo.files(id) ON DELETE CASCADE
            )
        """))


def _ensure_voice_log(engine):
    with engine.begin() as c:
        c.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='voice_log')
            CREATE TABLE dbo.voice_log (
                id          INT           IDENTITY(1,1) PRIMARY KEY,
                user_id     INT           NULL,
                user_email  NVARCHAR(200) NOT NULL,
                audio_hash  NVARCHAR(64)  NULL,
                file_path   NVARCHAR(512) NULL,
                raw_text    NVARCHAR(MAX) NOT NULL,
                clean_text  NVARCHAR(MAX) NOT NULL,
                language    NVARCHAR(10)  NULL,
                lang_prob   FLOAT         NULL,
                hit_count   INT           NOT NULL DEFAULT 1,
                latency_ms  FLOAT         NULL,
                expires_at  DATETIME      NULL,
                created_at  DATETIME      NOT NULL DEFAULT GETDATE(),
                last_hit_at DATETIME      NULL
            )
        """))


def _ensure_views(engine):
    """Create or refresh all three views."""
    with engine.begin() as c:
        c.execute(text("""
            CREATE OR ALTER VIEW dbo.v_sessions AS
            SELECT
                user_id, user_email, session_key,
                MIN(session_title) AS title,
                MIN(created_at)    AS created_at,
                MAX(created_at)    AS updated_at,
                SUM(CASE WHEN input_source != 'init' THEN 1 ELSE 0 END) AS message_count,
                SUM(CASE WHEN execution_status='FAILURE' THEN 1 ELSE 0 END) AS error_count
            FROM dbo.chat_log
            GROUP BY user_id, user_email, session_key
        """))
        c.execute(text("""
            CREATE OR ALTER VIEW dbo.v_cache_stats AS
            SELECT
                id, cache_type, user_question, provider, model,
                hit_count, run_count,
                ROUND(first_exec_ms,  0) AS first_exec_ms,
                ROUND(cached_exec_ms, 1) AS cached_exec_ms,
                ROUND(cache_lookup_ms,1) AS cache_lookup_ms,
                ROUND(sql_rerun_ms,   1) AS sql_rerun_ms,
                CASE WHEN cached_exec_ms > 0 AND first_exec_ms > 0
                     THEN ROUND(first_exec_ms / cached_exec_ms, 1)
                     ELSE NULL END        AS speedup_x,
                created_at, last_accessed
            FROM dbo.query_cache
        """))
        c.execute(text("""
            CREATE OR ALTER VIEW dbo.v_files AS
            SELECT
                f.id, f.user_id, f.file_name, f.file_type, f.category,
                f.file_size, f.sheet_name, f.uploaded_at, f.last_used,
                sf.row_count, sf.col_count, sf.columns_json,
                df.page_count, df.word_count,
                img.width_px, img.height_px, img.ocr_confidence, img.is_scanned_pdf
            FROM dbo.files f
            LEFT JOIN dbo.structured_files sf  ON sf.file_id = f.id
            LEFT JOIN dbo.document_files   df  ON df.file_id = f.id
            LEFT JOIN dbo.image_files      img ON img.file_id = f.id
        """))


# ══════════════════════════════════════════════════════════════════════════════
# app_users
# ══════════════════════════════════════════════════════════════════════════════

def get_user_by_email(engine, email: str) -> Optional[dict]:
    """Look up a user by email/username. Returns dict or None."""
    try:
        with engine.connect() as c:
            row = c.execute(text("""
                SELECT id, username, password_hash, role, full_name
                FROM dbo.app_users
                WHERE username = :email
            """), {"email": email.strip().lower()}).fetchone()
        if row:
            return {
                "id":            row[0],
                "email":         row[1],
                "password_hash": row[2],
                "role":          row[3],
                "display_name":  row[4],
            }
        return None
    except Exception as e:
        print(f"[db:users] get error: {e}")
        return None


def update_last_login(engine, user_id: int) -> None:
    try:
        with engine.begin() as c:
            c.execute(text(
                "UPDATE dbo.app_users SET last_login = GETDATE() WHERE id = :id"
            ), {"id": user_id})
    except Exception as e:
        print(f"[db:users] last_login update error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# query_cache  —  SQL queries
# ══════════════════════════════════════════════════════════════════════════════

def get_cached_sql(engine, question: str, provider: str, model: str,
                   similarity_threshold: float = 0.85) -> Optional[dict]:
    """
    Exact match first (prompt_hash), then semantic (cosine similarity on embedding).
    Returns cache row dict or None.
    """
    from app_core import get_embedding, cosine_similarity  # keep AI logic in app_core

    ph = hash_prompt(question)
    try:
        with engine.connect() as c:
            # 1. Exact match
            row = c.execute(text("""
                SELECT id, sql_query, raw_sql, analysis,
                       hit_count, run_count, first_exec_ms, cached_exec_ms, embedding
                FROM dbo.query_cache
                WHERE prompt_hash = :ph
                  AND provider    = :pv
                  AND model       = :mo
                  AND cache_type  = 'sql'
            """), {"ph": ph, "pv": provider, "mo": model}).fetchone()

            if row:
                return _cache_row_to_dict(row, "exact", 1.0, question)

            # 2. Semantic match
            q_emb = get_embedding(question)
            if q_emb is None:
                return None

            rows = c.execute(text("""
                SELECT id, sql_query, raw_sql, analysis,
                       hit_count, run_count, first_exec_ms, cached_exec_ms,
                       embedding, user_question
                FROM dbo.query_cache
                WHERE provider   = :pv
                  AND model      = :mo
                  AND cache_type = 'sql'
                  AND embedding IS NOT NULL
            """), {"pv": provider, "mo": model}).fetchall()

        best_score, best_row = 0.0, None
        for r in rows:
            try:
                score = cosine_similarity(q_emb, json.loads(r[8]))
                if score > best_score:
                    best_score, best_row = score, r
            except Exception:
                continue

        if best_score >= similarity_threshold and best_row:
            return _cache_row_to_dict(best_row, "semantic", best_score, best_row[9])

        return None
    except Exception as e:
        print(f"[db:cache] get_cached_sql error: {e}")
        return None


def _cache_row_to_dict(row, match_type: str, similarity: float,
                       matched_question: str) -> dict:
    return {
        "id":               row[0],
        "sql_query":        row[1],
        "raw_sql":          row[2],
        "analysis":         row[3],
        "hit_count":        row[4],
        "run_count":        row[5],
        "first_exec_ms":    row[6],
        "cached_exec_ms":   row[7],
        "match_type":       match_type,
        "similarity":       round(similarity, 4),
        "matched_question": matched_question,
    }


def save_sql_cache(engine, question: str, provider: str, model: str,
                   sql_query: str, raw_sql: str, analysis: str,
                   exec_ms: float) -> None:
    """Save a new SQL cache entry. No-op if the exact prompt_hash already exists."""
    from app_core import get_embedding
    ph  = hash_prompt(question)
    emb = get_embedding(question)
    emb_json = json.dumps(emb) if emb else None
    try:
        with engine.begin() as c:
            c.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM dbo.query_cache
                    WHERE prompt_hash = :ph AND provider = :pv
                      AND model = :mo AND cache_type = 'sql'
                )
                INSERT INTO dbo.query_cache
                    (cache_type, prompt_hash, provider, model, user_question,
                     sql_query, raw_sql, embedding, analysis,
                     first_exec_ms, hit_count, run_count)
                VALUES
                    ('sql', :ph, :pv, :mo, :q,
                     :sql, :raw, :emb, :an,
                     :ms, 0, 1)
            """), {
                "ph": ph, "pv": provider, "mo": model,
                "q":  question.strip(),
                "sql": sql_query, "raw": raw_sql,
                "emb": emb_json,  "an":  analysis,
                "ms":  exec_ms,
            })
    except Exception as e:
        print(f"[db:cache] save_sql_cache error: {e}")


def update_cache_hit(engine, cache_id: int,
                     cache_lookup_ms: float, sql_rerun_ms: float) -> None:
    """
    Increment hit_count and record the full cache serve timing.
    cache_lookup_ms  = time to find the row in query_cache
    sql_rerun_ms     = time to re-execute the SQL after cache hit
    cached_exec_ms   = total user-perceived latency on cache serve
    """
    total = round(cache_lookup_ms + sql_rerun_ms, 1)
    try:
        with engine.begin() as c:
            c.execute(text("""
                UPDATE dbo.query_cache
                SET hit_count       = hit_count + 1,
                    cache_lookup_ms = CASE WHEN cache_lookup_ms IS NULL THEN :lk ELSE cache_lookup_ms END,
                    sql_rerun_ms    = CASE WHEN sql_rerun_ms    IS NULL THEN :rr ELSE sql_rerun_ms    END,
                    cached_exec_ms  = CASE WHEN cached_exec_ms  IS NULL THEN :tot ELSE cached_exec_ms END,
                    last_accessed   = GETDATE()
                WHERE id = :id
            """), {"lk": cache_lookup_ms, "rr": sql_rerun_ms,
                   "tot": total, "id": cache_id})
    except Exception as e:
        print(f"[db:cache] update_cache_hit error: {e}")


def get_all_cache_entries(engine) -> list:
    """Admin dashboard: all cache entries ordered by last accessed."""
    try:
        with engine.connect() as c:
            rows = c.execute(text("""
                SELECT id, cache_type, user_question, provider, model,
                       hit_count, run_count,
                       ROUND(first_exec_ms,  0) AS first_exec_ms,
                       ROUND(cached_exec_ms, 1) AS cached_exec_ms,
                       CASE WHEN cached_exec_ms > 0 AND first_exec_ms > 0
                            THEN ROUND(first_exec_ms / cached_exec_ms, 1)
                            ELSE NULL END        AS speedup_x,
                       created_at, last_accessed
                FROM dbo.query_cache
                ORDER BY last_accessed DESC
            """)).fetchall()
        return [
            {
                "id":            r[0],
                "type":          r[1],
                "user_question": r[2],
                "provider":      r[3],
                "model":         r[4],
                "hit_count":     r[5],
                "run_count":     r[6],
                "first_exec_ms": r[7],
                "cached_exec_ms":r[8],
                "speedup_x":     r[9],
                "created_at":    r[10].isoformat() if r[10] else None,
                "last_accessed": r[11].isoformat() if r[11] else None,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db:cache] get_all_cache_entries error: {e}")
        return []


def delete_cache_entry(engine, cache_id: int) -> None:
    try:
        with engine.begin() as c:
            c.execute(text("DELETE FROM dbo.query_cache WHERE id = :id"),
                      {"id": abs(cache_id)})
    except Exception as e:
        print(f"[db:cache] delete error: {e}")


def flush_cache(engine) -> None:
    """Delete all cache entries (SQL + file)."""
    try:
        with engine.begin() as c:
            c.execute(text("DELETE FROM dbo.query_cache"))
        print("[db:cache] ✅ Cache flushed.")
    except Exception as e:
        print(f"[db:cache] flush error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# query_cache  —  file analysis
# ══════════════════════════════════════════════════════════════════════════════

def get_cached_file_analysis(engine, file_id: int, prompt: str) -> Optional[dict]:
    """Return cached analysis for a file+prompt pair."""
    ph = hash_prompt(prompt)
    try:
        with engine.connect() as c:
            row = c.execute(text("""
                SELECT id, analysis, hit_count, first_exec_ms, cached_exec_ms, chart_data
                FROM dbo.query_cache
                WHERE file_id    = :fid
                  AND prompt_hash = :ph
                  AND cache_type  = 'file'
            """), {"fid": file_id, "ph": ph}).fetchone()
        if row:
            # Increment hit on a separate transaction
            with engine.begin() as c:
                c.execute(text("""
                    UPDATE dbo.query_cache
                    SET hit_count     = hit_count + 1,
                        last_accessed = GETDATE()
                    WHERE id = :id
                """), {"id": row[0]})
            chart = {}
            if row[5]:
                try:
                    chart = json.loads(row[5])
                except Exception:
                    pass
            return {
                "analysis":         row[1],
                "hit_count":        row[2],
                "execution_time_ms":float(row[3]) if row[3] else 0.0,
                "cached_exec_ms":   float(row[4]) if row[4] else 0.0,
                "chart_data":       chart,
                "cached":           True,
            }
        return None
    except Exception as e:
        print(f"[db:cache] get_cached_file_analysis error: {e}")
        return None


def save_file_analysis(engine, file_id: int, prompt: str, analysis: str,
                       provider: str = "", model: str = "",
                       execution_time_ms: float = None,
                       chart_data: dict = None) -> None:
    ph         = hash_prompt(prompt)
    chart_json = json.dumps(chart_data) if chart_data else None
    try:
        with engine.begin() as c:
            c.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM dbo.query_cache
                    WHERE file_id = :fid AND prompt_hash = :ph AND cache_type = 'file'
                )
                INSERT INTO dbo.query_cache
                    (cache_type, prompt_hash, provider, model, user_question,
                     file_id, analysis, chart_data, first_exec_ms, hit_count, run_count)
                VALUES
                    ('file', :ph, :pv, :mo, :prompt,
                     :fid, :an, :ch, :ms, 0, 1)
            """), {
                "ph": ph, "pv": provider, "mo": model,
                "prompt": prompt, "fid": file_id,
                "an": analysis, "ch": chart_json, "ms": execution_time_ms,
            })
    except Exception as e:
        print(f"[db:cache] save_file_analysis error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# chat_log  —  sessions + history + audit
# ══════════════════════════════════════════════════════════════════════════════

def save_chat_log(engine, session_key: str, user_id: int, user_email: str,
                  result: dict, input_source: str = "keyboard",
                  cache_id: int = None) -> None:
    """
    Write one message to chat_log.
    Replaces: save_chat_message() + save_audit_log() — one call does both.
    """
    error            = result.get("error")
    execution_status = "FAILURE" if error else "SUCCESS"
    timing           = result.get("timing") or {}
    exec_ms          = (timing.get("model_ms") or timing.get("cache_ms") or
                        timing.get("first_exec_ms") or 0)

    # Auto-generate session title from first question (≤60 chars)
    question      = result.get("question", "")
    session_title = question.strip()[:60] if question else None

    try:
        with engine.begin() as c:
            c.execute(text("""
                INSERT INTO dbo.chat_log
                    (session_key, session_title, user_id, user_email,
                     question, input_source,
                     sql_query, analysis, row_count, columns_json,
                     cache_id, source,
                     execution_status, error,
                     provider, model, exec_ms)
                VALUES
                    (:sk, :st, :uid, :email,
                     :q, :src,
                     :sql, :an, :rc, :cols,
                     :cid, :source,
                     :status, :err,
                     :pv, :mo, :ms)
            """), {
                "sk":    session_key,
                "st":    session_title,
                "uid":   user_id,
                "email": user_email,
                "q":     question,
                "src":   input_source,
                "sql":   result.get("sql_query", ""),
                "an":    result.get("analysis", ""),
                "rc":    result.get("row_count"),
                "cols":  json.dumps(result.get("columns", [])),
                "cid":   cache_id,
                "source":result.get("source"),
                "status":execution_status,
                "err":   str(error) if error else None,
                "pv":    result.get("provider", ""),
                "mo":    result.get("model", ""),
                "ms":    exec_ms,
            })
    except Exception as e:
        print(f"[db:chat] save_chat_log error: {e}")


def get_user_sessions(engine, user_id: int) -> list:
    """
    Session list from v_sessions view — no JOIN needed.
    Replaces: get_user_sessions() querying chat_sessions.
    """
    try:
        with engine.connect() as c:
            rows = c.execute(text("""
                SELECT session_key, title, created_at, updated_at,
                       message_count, error_count
                FROM dbo.v_sessions
                WHERE user_id = :uid
                ORDER BY updated_at DESC
            """), {"uid": user_id}).fetchall()
        return [
            {
                "id":            r[0],          # session_key acts as session ID
                "title":         r[1] or "New Chat",
                "created_at":    r[2].isoformat() if r[2] else None,
                "updated_at":    r[3].isoformat() if r[3] else None,
                "message_count": r[4],
                "error_count":   r[5],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db:chat] get_user_sessions error: {e}")
        return []


def get_session_messages(engine, session_key: str, user_id: int) -> list:
    """Return all messages in a session ordered by time."""
    try:
        with engine.connect() as c:
            rows = c.execute(text("""
                SELECT id, question, sql_query, analysis, row_count,
                       columns_json, source, input_source,
                       provider, model, exec_ms, error,
                       execution_status, created_at
                FROM dbo.chat_log
                WHERE session_key = :sk AND user_id = :uid AND input_source != 'init'
                ORDER BY created_at ASC
            """), {"sk": session_key, "uid": user_id}).fetchall()
        msgs = []
        for r in rows:
            try:
                cols = json.loads(r[5]) if r[5] else []
            except Exception:
                cols = []
            msgs.append({
                "id":               r[0],
                "question":         r[1],
                "sql_query":        r[2],
                "analysis":         r[3],
                "row_count":        r[4],
                "columns":          cols,
                "source":           r[6],
                "input_source":     r[7],
                "provider":         r[8],
                "model":            r[9],
                "exec_ms":          r[10],
                "error":            r[11],
                "execution_status": r[12],
                "created_at":       r[13].isoformat() if r[13] else None,
            })
        return msgs
    except Exception as e:
        print(f"[db:chat] get_session_messages error: {e}")
        return []


def delete_session(engine, session_key: str, user_id: int) -> None:
    """Delete all messages in a session (no foreign-key dependency needed now)."""
    try:
        with engine.begin() as c:
            result = c.execute(text("""
                DELETE FROM dbo.chat_log
                WHERE session_key = :sk AND user_id = :uid
            """), {"sk": session_key, "uid": user_id})
        print(f"[db:chat] deleted {result.rowcount} messages for session {session_key[:8]}…")
    except Exception as e:
        print(f"[db:chat] delete_session error: {e}")


def rename_session(engine, session_key: str, user_id: int, new_title: str) -> bool:
    """Update session_title on ALL rows in that session (denormalised design)."""
    try:
        with engine.begin() as c:
            result = c.execute(text("""
                UPDATE dbo.chat_log
                SET session_title = :title
                WHERE session_key = :sk AND user_id = :uid
            """), {"title": new_title[:60], "sk": session_key, "uid": user_id})
        return result.rowcount > 0
    except Exception as e:
        print(f"[db:chat] rename_session error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# files  —  base + 3 child tables
# ══════════════════════════════════════════════════════════════════════════════

def save_file(engine, user_id: int, file_hash: str, filename: str,
              file_size: int, parsed: dict,
              sheet_name: str = None) -> Optional[int]:
    """
    Insert into dbo.files (base) then the appropriate child table.
    Returns the file id.
    """
    raw_type  = parsed.get("file_type", "").lower().lstrip(".")
    if not raw_type:
        # derive from filename
        raw_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"

    category  = _file_category(raw_type, parsed)

    # Composite hash for Excel sheets
    composite_hash = (file_hash + "::" + sheet_name) if sheet_name else file_hash

    # ── Base insert / update ──────────────────────────────────────────────────
    try:
        with engine.begin() as c:
            existing = c.execute(text("""
                SELECT id FROM dbo.files
                WHERE user_id = :uid AND file_hash = :h
            """), {"uid": user_id, "h": composite_hash}).fetchone()

            if existing:
                c.execute(text("""
                    UPDATE dbo.files
                    SET last_used = GETDATE(), file_name = :name
                    WHERE id = :id
                """), {"name": filename, "id": existing[0]})
                return existing[0]

            result = c.execute(text("""
                INSERT INTO dbo.files
                    (user_id, file_hash, file_name, file_size,
                     file_type, category, sheet_name)
                OUTPUT INSERTED.id
                VALUES (:uid, :h, :name, :sz, :ft, :cat, :sh)
            """), {
                "uid":  user_id,
                "h":    composite_hash,
                "name": filename,
                "sz":   file_size,
                "ft":   raw_type,
                "cat":  category,
                "sh":   sheet_name,
            })
            file_id = result.fetchone()[0]

        # ── Child insert ──────────────────────────────────────────────────────
        _save_child(engine, file_id, category, parsed, sheet_name)
        return file_id

    except Exception as e:
        print(f"[db:files] save_file error: {e}")
        return None


def _save_child(engine, file_id: int, category: str, parsed: dict,
                sheet_name: str = None) -> None:
    """Insert category-specific data into the child table."""
    try:
        with engine.begin() as c:
            # 1. Save structured data if df or preview exists
            has_df = False
            if sheet_name and parsed.get("sheets") and sheet_name in parsed["sheets"]:
                sd = parsed["sheets"][sheet_name]
                if sd.get("df") is not None and not sd["df"].empty: has_df = True
            elif parsed.get("df") is not None and not parsed["df"].empty:
                has_df = True

            if has_df or category == "structured":
                if sheet_name and parsed.get("sheets") and sheet_name in parsed["sheets"]:
                    sd       = parsed["sheets"][sheet_name]
                    df       = sd.get("df")
                    row_cnt  = sd.get("row_count", 0)
                    col_cnt  = sd.get("col_count", 0)
                    cols     = sd.get("columns", [])
                else:
                    df       = parsed.get("df")
                    row_cnt  = parsed.get("row_count", 0)
                    col_cnt  = parsed.get("col_count", 0)
                    cols     = parsed.get("columns", [])

                # Cap data JSON at 8 MB
                import pandas as _pd
                MAX_BYTES = 8 * 1024 * 1024
                if df is not None:
                    data_json = json.dumps(df.fillna("").astype(str).values.tolist())
                    while len(data_json.encode()) > MAX_BYTES and len(df) > 1000:
                        df = df.sample(n=len(df) // 2, random_state=42).reset_index(drop=True)
                        data_json = json.dumps(df.fillna("").astype(str).values.tolist())
                else:
                    data_json = json.dumps(parsed.get("preview", []))

                c.execute(text("""
                    INSERT INTO dbo.structured_files
                        (file_id, row_count, col_count, columns_json, data_json)
                    VALUES (:fid, :rc, :cc, :cols, :data)
                """), {
                    "fid":  file_id,
                    "rc":   row_cnt,
                    "cc":   col_cnt,
                    "cols": json.dumps(cols),
                    "data": data_json,
                })

            # 2. Save document data if text exists
            extracted_text = parsed.get("extracted_text") or parsed.get("text")
            if extracted_text or category == "document":
                c.execute(text("""
                    INSERT INTO dbo.document_files
                        (file_id, page_count, word_count, extracted_text)
                    VALUES (:fid, :pg, :wc, :txt)
                """), {
                    "fid": file_id,
                    "pg":  parsed.get("page_count"),
                    "wc":  parsed.get("word_count"),
                    "txt": extracted_text,
                })

            # 3. Save image data if OCR text/confidence exists
            ocr_text = parsed.get("ocr_text")
            ocr_conf = parsed.get("ocr_confidence")
            if ocr_text or ocr_conf:
                c.execute(text("""
                    INSERT INTO dbo.image_files
                        (file_id, width_px, height_px,
                         ocr_text, ocr_confidence, is_scanned_pdf)
                    VALUES (:fid, :w, :h, :txt, :conf, :sp)
                """), {
                    "fid":  file_id,
                    "w":    parsed.get("width_px"),
                    "h":    parsed.get("height_px"),
                    "txt":  ocr_text or extracted_text,
                    "conf": ocr_conf,
                    "sp":   1 if parsed.get("is_scanned_pdf") else 0,
                })
    except Exception as e:
        print(f"[db:files] _save_child error ({category}): {e}")


def get_user_files(engine, user_id: int) -> list:
    """Return all files for a user from the unified v_files view."""
    try:
        with engine.connect() as c:
            rows = c.execute(text("""
                SELECT id, file_name, file_size, file_type, category,
                       row_count, col_count, columns_json,
                       page_count, width_px, height_px,
                       sheet_name, uploaded_at, last_used
                FROM dbo.v_files
                WHERE user_id = :uid
                ORDER BY COALESCE(last_used, uploaded_at) DESC
            """), {"uid": user_id}).fetchall()
        result = []
        for r in rows:
            try:
                cols = json.loads(r[7]) if r[7] else []
            except Exception:
                cols = []
            result.append({
                "id":          r[0],
                "file_name":   r[1],
                "file_size":   r[2],
                "file_type":   r[3],
                "category":    r[4],
                "row_count":   r[5],
                "col_count":   r[6],
                "columns":     cols,
                "page_count":  r[8],
                "width_px":    r[9],
                "height_px":   r[10],
                "sheet_name":  r[11],
                "uploaded_at": r[12].isoformat() if r[12] else None,
                "last_used":   r[13].isoformat() if r[13] else None,
            })
        return result
    except Exception as e:
        print(f"[db:files] get_user_files error: {e}")
        return []


def get_file_data(engine, file_id: int, user_id: int) -> Optional[dict]:
    """
    Return file data for AI analysis.
    structured → data_json parsed as list-of-lists
    document   → extracted_text string
    image_ocr  → ocr_text string
    """
    try:
        with engine.connect() as c:
            # base
            base = c.execute(text("""
                SELECT category, file_type, file_name
                FROM dbo.files WHERE id = :fid AND user_id = :uid
            """), {"fid": file_id, "uid": user_id}).fetchone()
            if not base:
                return None
            cat = base[0]

            res = {"category": cat}

            # Fetch ALL available child records dynamically
            
            # 1. Structured data
            row_str = c.execute(text("""
                SELECT data_json, columns_json, row_count, col_count
                FROM dbo.structured_files WHERE file_id = :fid
            """), {"fid": file_id}).fetchone()
            if row_str:
                import pandas as _pd
                data   = json.loads(row_str[0]) if row_str[0] else []
                cols   = json.loads(row_str[1]) if row_str[1] else []
                res["df"] = _pd.DataFrame(data, columns=cols) if data and cols else _pd.DataFrame()
                res["columns"] = cols
                res["row_count"] = row_str[2]
                res["col_count"] = row_str[3]

            # 2. Document data
            row_doc = c.execute(text("""
                SELECT extracted_text, page_count, word_count
                FROM dbo.document_files WHERE file_id = :fid
            """), {"fid": file_id}).fetchone()
            if row_doc:
                res["extracted_text"] = row_doc[0] or ""
                res["page_count"] = row_doc[1]
                res["word_count"] = row_doc[2]

            # 3. Image OCR data
            row_img = c.execute(text("""
                SELECT ocr_text, ocr_confidence, width_px, height_px
                FROM dbo.image_files WHERE file_id = :fid
            """), {"fid": file_id}).fetchone()
            if row_img:
                res["ocr_text"] = row_img[0] or ""
                res["ocr_confidence"] = row_img[1]
                res["width_px"] = row_img[2]
                res["height_px"] = row_img[3]

            return res
    except Exception as e:
        print(f"[db:files] get_file_data error: {e}")
        return None


def touch_file(engine, file_id: int) -> None:
    """Update last_used timestamp when a file is used for analysis."""
    try:
        with engine.begin() as c:
            c.execute(text(
                "UPDATE dbo.files SET last_used = GETDATE() WHERE id = :id"
            ), {"id": file_id})
    except Exception as e:
        print(f"[db:files] touch_file error: {e}")


def delete_file(engine, file_id: int, user_id: int) -> bool:
    """Delete a file + its child records (CASCADE handles children) + metadata + dynamic tables."""
    try:
        # 1. Find any dynamic tables linked to this file
        with engine.connect() as c:
            rows = c.execute(text("""
                SELECT sql_table_name FROM dbo.document_metadata
                WHERE uploaded_files_id = :fid AND user_id = :uid
            """), {"fid": file_id, "uid": user_id}).fetchall()
            
        with engine.begin() as c:
            # 2. Drop the dynamic tables
            for row in rows:
                if row[0]:
                    try:
                        c.execute(text(f"DROP TABLE IF EXISTS dbo.{row[0]}"))
                    except Exception as e:
                        print(f"[db:files] Failed to drop dynamic table {row[0]}: {e}")

            # 3. Delete the metadata row
            c.execute(text("""
                DELETE FROM dbo.document_metadata
                WHERE uploaded_files_id = :fid AND user_id = :uid
            """), {"fid": file_id, "uid": user_id})

            # 4. Delete the cache entries for this file
            c.execute(text("""
                DELETE FROM dbo.query_cache
                WHERE file_id = :fid
            """), {"fid": file_id})

            # 5. Delete the main file row (CASCADE will handle structured_files, etc.)
            result = c.execute(text(
                "DELETE FROM dbo.files WHERE id = :fid AND user_id = :uid"
            ), {"fid": file_id, "uid": user_id})
            
        return result.rowcount > 0 or len(rows) > 0
    except Exception as e:
        print(f"[db:files] delete_file error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# voice_log
# ══════════════════════════════════════════════════════════════════════════════

def get_voice_by_hash(engine, audio_hash: str) -> Optional[dict]:
    """
    Look up a cached Whisper result by audio hash.
    Returns row dict or None (None also if entry is expired).
    """
    try:
        with engine.connect() as c:
            row = c.execute(text("""
                SELECT id, raw_text, clean_text, language, lang_prob,
                       hit_count, latency_ms, expires_at
                FROM dbo.voice_log
                WHERE audio_hash = :h
            """), {"h": audio_hash}).fetchone()
        if not row:
            return None
        # Expired?
        if row[7] and datetime.now() > row[7]:
            return None
        return {
            "id":         row[0],
            "raw_text":   row[1],
            "clean_text": row[2],
            "language":   row[3],
            "lang_prob":  row[4],
            "hit_count":  row[5],
            "latency_ms": row[6],
        }
    except Exception as e:
        print(f"[db:voice] get_voice_by_hash error: {e}")
        return None


def save_voice_entry(engine, user_id: Optional[int], user_email: str,
                     raw_text: str, clean_text: str,
                     latency_ms: float = None,
                     language: str = None, lang_prob: float = None,
                     audio_hash: str = None, file_path: str = None,
                     cache_ttl_hours: int = 24,
                     fuzzy_threshold: float = 0.85) -> int:
    """
    Save a voice transcript to voice_log.

    Fuzzy dedup logic (preserved from voice_db.py):
      If a similar clean_text entry (≥ fuzzy_threshold) exists for this user,
      increment its hit_count instead of inserting a new row.

    audio_hash set  → Whisper cache entry (expires after cache_ttl_hours)
    audio_hash None → browser transcript (permanent history row)
    """
    # ── Fuzzy dedup: check existing transcripts for this user ────────────────
    try:
        with engine.connect() as c:
            existing = c.execute(text("""
                SELECT id, clean_text FROM dbo.voice_log
                WHERE user_email = :email
                  AND created_at >= DATEADD(day, -7, GETDATE())
                ORDER BY created_at DESC
            """), {"email": user_email}).fetchall()

        for row in existing:
            ratio = SequenceMatcher(None, clean_text.lower(),
                                    row[1].lower()).ratio()
            if ratio >= fuzzy_threshold:
                # Same phrase — increment hit_count
                with engine.begin() as c:
                    c.execute(text("""
                        UPDATE dbo.voice_log
                        SET hit_count   = hit_count + 1,
                            last_hit_at = GETDATE()
                        WHERE id = :id
                    """), {"id": row[0]})
                print(f"[db:voice] Fuzzy match ({ratio:.0%}) — hit_count incremented on id={row[0]}")
                return row[0]
    except Exception as e:
        print(f"[db:voice] fuzzy check error: {e}")

    # ── New entry ─────────────────────────────────────────────────────────────
    expires_at = (datetime.now() + timedelta(hours=cache_ttl_hours)
                  ) if audio_hash else None
    try:
        with engine.begin() as c:
            result = c.execute(text("""
                INSERT INTO dbo.voice_log
                    (user_id, user_email, audio_hash, file_path,
                     raw_text, clean_text, language, lang_prob,
                     latency_ms, expires_at, hit_count)
                OUTPUT INSERTED.id
                VALUES
                    (:uid, :email, :ah, :fp,
                     :raw, :clean, :lang, :lp,
                     :ms, :exp, 1)
            """), {
                "uid":   user_id,
                "email": user_email,
                "ah":    audio_hash,
                "fp":    file_path,
                "raw":   raw_text,
                "clean": clean_text,
                "lang":  language,
                "lp":    lang_prob,
                "ms":    latency_ms,
                "exp":   expires_at,
            })
            return result.fetchone()[0]
    except Exception as e:
        print(f"[db:voice] save_voice_entry error: {e}")
        return -1


def hit_voice_entry(engine, voice_id: int) -> None:
    """Increment hit_count for a cached voice entry (called on audio hash hit)."""
    try:
        with engine.begin() as c:
            c.execute(text("""
                UPDATE dbo.voice_log
                SET hit_count   = hit_count + 1,
                    last_hit_at = GETDATE()
                WHERE id = :id
            """), {"id": voice_id})
    except Exception as e:
        print(f"[db:voice] hit_voice_entry error: {e}")


def get_voice_history(engine, user_email: str, limit: int = 50) -> list:
    """Return paginated voice transcript history for a user."""
    try:
        with engine.connect() as c:
            rows = c.execute(text("""
                SELECT TOP (:lim)
                    id, clean_text, raw_text, language,
                    ROUND(lang_prob * 100, 1) AS confidence_pct,
                    hit_count, ROUND(latency_ms, 0) AS latency_ms,
                    CASE WHEN audio_hash IS NOT NULL THEN 'whisper' ELSE 'browser' END AS source,
                    created_at
                FROM dbo.voice_log
                WHERE user_email = :email
                ORDER BY created_at DESC
            """), {"email": user_email, "lim": limit}).fetchall()
        return [
            {
                "id":             r[0],
                "clean_text":     r[1],
                "raw_text":       r[2],
                "language":       r[3],
                "confidence_pct": r[4],
                "hit_count":      r[5],
                "latency_ms":     r[6],
                "source":         r[7],
                "created_at":     r[8].isoformat() if r[8] else None,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db:voice] get_voice_history error: {e}")
        return []


def delete_voice_entry(engine, voice_id: int, user_email: str) -> bool:
    """Delete a single voice entry (also removes audio file from disk if present)."""
    try:
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT file_path FROM dbo.voice_log WHERE id = :id AND user_email = :e"
            ), {"id": voice_id, "e": user_email}).fetchone()
        if row and row[0] and os.path.exists(row[0]):
            try:
                os.remove(row[0])
            except OSError:
                pass
        with engine.begin() as c:
            result = c.execute(text(
                "DELETE FROM dbo.voice_log WHERE id = :id AND user_email = :e"
            ), {"id": voice_id, "e": user_email})
        return result.rowcount > 0
    except Exception as e:
        print(f"[db:voice] delete_voice_entry error: {e}")
        return False


def list_voice_cache(engine) -> list:
    """Admin: list all Whisper audio cache entries."""
    try:
        with engine.connect() as c:
            rows = c.execute(text("""
                SELECT id, user_email, audio_hash, clean_text,
                       hit_count, latency_ms, expires_at, created_at
                FROM dbo.voice_log
                WHERE audio_hash IS NOT NULL
                ORDER BY hit_count DESC, created_at DESC
            """)).fetchall()
        return [
            {
                "id":         r[0],
                "user_email": r[1],
                "audio_hash": r[2],
                "clean_text": r[3],
                "hit_count":  r[4],
                "latency_ms": r[5],
                "expires_at": r[6].isoformat() if r[6] else None,
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db:voice] list_voice_cache error: {e}")
        return []


def flush_voice_cache(engine) -> None:
    """Delete all Whisper audio cache entries + their files from disk."""
    try:
        with engine.connect() as c:
            paths = c.execute(text(
                "SELECT file_path FROM dbo.voice_log WHERE audio_hash IS NOT NULL"
            )).fetchall()
        for (fp,) in paths:
            if fp and os.path.exists(fp):
                try:
                    os.remove(fp)
                except OSError:
                    pass
        with engine.begin() as c:
            c.execute(text("DELETE FROM dbo.voice_log WHERE audio_hash IS NOT NULL"))
        print("[db:voice] ✅ Voice cache flushed.")
    except Exception as e:
        print(f"[db:voice] flush_voice_cache error: {e}")


def flush_expired_voice_cache(engine) -> int:
    """Delete voice cache entries past their expires_at. Returns number removed."""
    try:
        with engine.begin() as c:
            result = c.execute(text("""
                DELETE FROM dbo.voice_log
                WHERE expires_at IS NOT NULL AND expires_at < GETDATE()
            """))
        removed = result.rowcount
        if removed:
            print(f"[db:voice] Expired {removed} voice cache entries.")
        return removed
    except Exception as e:
        print(f"[db:voice] flush_expired error: {e}")
        return 0
