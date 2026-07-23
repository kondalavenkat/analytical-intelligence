"""
backend/main.py  —  FastAPI wrapper around app.py
Run: uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import uuid
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import make_asgi_app, Counter, Histogram
import jwt as pyjwt
import hashlib
import hmac
import time
import json
import os
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text

SERVER_START_TIME = datetime.now()

from contextlib import asynccontextmanager
from app_core import (
    create_sql_server_connection,
    get_sql_server_tables,
    get_table_schema,
    generate_sql_with_ai,
    analyze_data_with_ai,
    ensure_file_tables,
    parse_uploaded_file,
    analyze_file_with_ai,
    compare_files_with_ai,
    get_tables_enriched_with_metadata,
)
import db

# ─────────────────────────────────────────────────────────────────────────────
# AUTH DB CONFIG  — SQL Server authentication
# ─────────────────────────────────────────────────────────────────────────────

AUTH_DB_SERVER   = os.environ.get("AUTH_DB_SERVER",   "QFTCHNLPT-04800")
AUTH_DB_NAME     = os.environ.get("AUTH_DB_NAME",     "AdventureWorks2025")
AUTH_DB_WINDOWS  = False
AUTH_DB_USER     = os.environ.get("AUTH_DB_USER",     "sa")
AUTH_DB_PASSWORD = os.environ.get("AUTH_DB_PASSWORD", "Passw0rd@098")

_auth_engine = None
_engines: dict = {}


def get_auth_engine():
    global _auth_engine
    if _auth_engine is not None:
        return _auth_engine
    if _engines:
        return next(iter(_engines.values()))["engine"]
    return None


@asynccontextmanager
async def lifespan(app_instance):
    global _auth_engine
    from app_core import preload_embedding_model
    from voice import preload_whisper_model
    import threading
    import time

    threading.Thread(target=preload_embedding_model, daemon=True).start()
    threading.Thread(target=preload_whisper_model, daemon=True).start()

    def _init_db_and_tables():
        global _auth_engine
        try:
            start_t = time.time()
            engine, success, error = create_sql_server_connection(
                AUTH_DB_SERVER, AUTH_DB_NAME,
                AUTH_DB_USER, AUTH_DB_PASSWORD,
                trusted_connection=False
            )
            if success:
                _auth_engine = engine
                print(f"[auth] ✅ Connected to auth DB: {AUTH_DB_NAME} on {AUTH_DB_SERVER}")
                waited = int(time.time() - start_t)
                print(f"[startup] Auth engine ready (waited {waited}s) - initialising all tables...")
                
                # (Disabled) ONE-TIME SCHEMA RESET IF UPGRADING TO V3
                # We are staying on v2 for now to prevent data loss.
                pass
            else:
                print(f"[auth] ❌ Auth DB failed: {error} — using hardcoded users")
        except Exception as e:
            print(f"[auth] ❌ Auth DB error: {e}")

    threading.Thread(target=_init_db_and_tables, daemon=True).start()
    yield


# ─────────────────────────────────────────────────────────────────────────────
# Timestamped logging
# ─────────────────────────────────────────────────────────────────────────────
import logging as _logging
import os as _os
from datetime import datetime as _datetime

_LOG_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "logs")
_os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = _os.path.join(_LOG_DIR, f"app_{_datetime.now().strftime('%Y-%m-%d')}.log")

if not _logging.getLogger("sql_analyst_main").handlers:
    _h_file = _logging.FileHandler(_LOG_FILE, encoding="utf-8")
    _h_console = _logging.StreamHandler()
    _formatter = _logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _h_file.setFormatter(_formatter)
    _h_console.setFormatter(_formatter)
    _main_logger = _logging.getLogger("sql_analyst_main")
    _main_logger.setLevel(_logging.INFO)
    _main_logger.addHandler(_h_file)
    _main_logger.addHandler(_h_console)
    _main_logger.propagate = False

import builtins as _builtins
_original_print = _builtins.print
def _logging_print(*args, **kwargs):
    try:
        msg = " ".join(str(a) for a in args)
        if msg.lstrip().startswith("[") and "]" in msg.split("\n")[0]:
            _logging.getLogger("sql_analyst_main").info(msg)
            return
    except Exception:
        pass
    _original_print(*args, **kwargs)
_builtins.print = _logging_print

print(f"[startup] Logging initialized → {_LOG_FILE}")

app = FastAPI(title="SQL Analyst API", version="1.0.0", lifespan=lifespan)

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Prometheus Metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
VOICE_REQUESTS = Counter("voice_requests_total", "Total voice transcriptions requested")
VOICE_LATENCY = Histogram("voice_latency_seconds", "Voice transcription latency")

# Request Tracing Middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

JWT_SECRET       = "change-this-to-a-long-random-secret-in-prod"
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = 8
security         = HTTPBearer()

# ─────────────────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────────────────

def _hash(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

USERS = {
    "divya.v@quinteft.com": {
        "password_hash": _hash("Divya@123"),
        "role":          "Admin",
        "name":          "Divya V",
        "id":            2,
    },
    "dishanth@quinteft.com": {
        "password_hash": _hash("Dishanth@123"),
        "role":          "Admin",
        "name":          "Dishanth",
        "id":            3,
    },
    "dikshith@quinteft.com": {
        "password_hash": _hash("Dikshith@123"),
        "role":          "Admin",
        "name":          "Dikshith",
        "id":            4,
    },
    "admin": {
        "password_hash": _hash("Admin@123"),
        "role":          "Admin",
        "name":          "Administrator",
        "id":            1,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# JWT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def create_jwt(email: str, role: str, user_id: int = 0) -> str:
    payload = {
        "sub":     email,
        "role":    role,
        "user_id": user_id,
        "exp":     datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat":     datetime.utcnow(),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        return pyjwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ─────────────────────────────────────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    server:       str
    database:     str
    username:     Optional[str] = None
    password:     Optional[str] = None
    windows_auth: bool = True

def get_db(user: dict = Depends(verify_jwt)):
    entry = _engines.get(user["sub"])
    if not entry:
        raise HTTPException(status_code=400, detail="Not connected. Call /db/connect first.")
    return entry

def get_db_or_none(user: dict = Depends(verify_jwt)):
    return _engines.get(user.get("sub", ""))

# ─────────────────────────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email:    str
    password: str

@app.post("/auth/login")
def login(body: LoginRequest):
    print(f"[login] Attempting: {body.email!r}")

    db_engine = get_auth_engine()
    if db_engine:
        try:
            db_user = db.get_user_by_email(db_engine, body.email)
            if db_user:
                pw_hash = hashlib.sha256(body.password.encode()).hexdigest().upper()
                stored  = (db_user["password_hash"] or "").upper().strip()
                print(f"[login] DB user found, hash match: {pw_hash[:8]}... vs {stored[:8]}...")
                if not hmac.compare_digest(stored, pw_hash):
                    raise HTTPException(status_code=401, detail="Incorrect email or password")
                db.update_last_login(db_engine, db_user["id"])
                token = create_jwt(body.email, db_user["role"], user_id=db_user["id"])
                print(f"[login] ✅ DB auth: {body.email} role={db_user['role']}")
                return {
                    "token":        token,
                    "email":        body.email,
                    "role":         db_user["role"],
                    "display_name": db_user["display_name"],
                    "user_id":      db_user["id"],
                }
            else:
                print(f"[login] User not found in DB — trying hardcoded")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[login] DB lookup error: {e} — trying hardcoded")
    else:
        print(f"[login] No auth DB available — using hardcoded users")

    user = USERS.get(body.email.strip().lower())
    if not user or not hmac.compare_digest(user["password_hash"], _hash(body.password)):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    user_id = user.get("id", 1)
    token   = create_jwt(body.email, user["role"], user_id=user_id)
    print(f"[login] ✅ Hardcoded auth: {body.email}")
    return {
        "token":        token,
        "email":        body.email,
        "role":         user["role"],
        "display_name": user["name"],
        "user_id":      user_id,
    }

@app.get("/auth/me")
def me(user: dict = Depends(verify_jwt)):
    return {"email": user["sub"], "role": user["role"], "user_id": user.get("user_id", 0)}

# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/ollama/models")
def get_ollama_models(_=Depends(verify_jwt)):
    try:
        import requests as pyrequests
        resp = pyrequests.get("http://localhost:11434/api/tags", timeout=5)
        resp.raise_for_status()
        models_raw = resp.json().get("models", [])
        models = []
        for m in models_raw:
            size_bytes = m.get("size", 0)
            size_gb    = round(size_bytes / 1e9, 1) if size_bytes else 0
            models.append({
                "name":        m.get("name", ""),
                "size_gb":     size_gb,
                "modified_at": m.get("modified_at", "")[:10] if m.get("modified_at") else "",
                "family":      m.get("details", {}).get("family", ""),
            })
        return {"status": "connected", "models": models, "count": len(models)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cannot reach Ollama: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────────
# DB CONNECT
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/db/connect")
def connect(body: ConnectRequest, user: dict = Depends(verify_jwt)):
    engine, success, error = create_sql_server_connection(
        body.server, body.database,
        body.username, body.password,
        body.windows_auth
    )
    if not success:
        raise HTTPException(status_code=400, detail=error)
    _engines[user["sub"]] = {"engine": engine, "database": body.database}
    return {"status": "connected", "database": body.database}

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/schema")
def schema(db=Depends(get_db), user: dict = Depends(verify_jwt)):
    engine  = db["engine"]
    user_id = user.get("user_id", 0)
    # Enriched: includes standard DB tables + universal intake tables for this user
    tables = get_tables_enriched_with_metadata(engine, user_id)
    for t in tables:
        if not t.get("columns"):  # standard tables: fetch live; UI tables: already populated
            t["columns"] = get_table_schema(engine, t["schema"], t["name"])
    return {"tables": tables, "database": db["database"]}

# ─────────────────────────────────────────────────────────────────────────────
# QUERY
# ─────────────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question:             str
    provider:             str
    model:                str
    api_key:              Optional[str]  = None
    base_url:             Optional[str]  = "http://localhost:11434"
    similarity_threshold: float          = 0.85
    session_id:           Optional[str]  = None
    input_source:         Optional[str]  = "keyboard"  # 'keyboard' | 'voice' | 'quick_prompt'
    chat_history:         Optional[list] = None        # [{role, content}, ...] last N messages


def process_query(question: str, engine, tables: list, pcfg: dict,
                  similarity_threshold: float) -> dict:
    import re as _re, math, decimal, json
    import numpy as np
    from app_core import find_known_query

    provider = pcfg.get("provider", "unknown")
    model    = pcfg.get("model",    "unknown")
    asked_at = datetime.now().isoformat()
    t0       = time.time()

    cache_start = time.time()
    cached      = db.get_cached_sql(engine, question, provider, model, similarity_threshold)
    cache_ms    = (time.time() - cache_start) * 1000

    if cached:
        print(f"[query] Cache hit — {cached['match_type']} match")
        sql_query = cached["sql_query"]
        raw_sql   = cached["raw_sql"] or cached["sql_query"]
        analysis  = cached["analysis"]
        source    = "cache"
        
        # FIX: Measure SQL re-run time separately
        sql_rerun_start = time.time()
        try:
            df = pd.read_sql(text(sql_query.rstrip(";")), engine)
        except Exception as e:
            return {"error": f"SQL execution error: {e}", "sql_query": sql_query, "question": question}
        sql_rerun_ms = (time.time() - sql_rerun_start) * 1000
        
        db.update_cache_hit(engine, cached["id"], cache_ms, sql_rerun_ms)
        
        timing    = {
            "cache_lookup_ms":  round(cache_ms, 1),
            "sql_rerun_ms":     round(sql_rerun_ms, 1),
            "cached_exec_ms":   round(cache_ms + sql_rerun_ms, 1),
            "first_exec_ms":    cached["first_exec_ms"] or 0,
            "hit_count":        cached["hit_count"],
            "match_type":       cached["match_type"],
            "similarity":       cached["similarity"],
            "matched_question": cached.get("matched_question", question),
        }
        return _make_result(question, asked_at, sql_query, raw_sql, df, analysis, source, timing)

    known_sql = find_known_query(question)
    if known_sql:
        print(f"[query] Known-good match — skipping AI")
        sql_query = known_sql
        raw_sql   = known_sql
        source    = "model"
        try:
            df = pd.read_sql(text(sql_query.rstrip(";")), engine)
        except Exception as e:
            return {"error": f"SQL execution error: {e}", "sql_query": sql_query, "question": question}
        analysis = None
        if not df.empty:
            try:
                analysis = analyze_data_with_ai(df, question, pcfg)
            except Exception as e:
                print(f"[analysis] non-fatal: {e}")
        model_ms = round((time.time() - t0) * 1000, 1)
        timing   = {"model_ms": model_ms, "first_exec_ms": model_ms}
        db.save_sql_cache(engine, question, provider, model,
                          sql_query, raw_sql, analysis or "", exec_ms=model_ms)
        return _make_result(question, asked_at, sql_query, raw_sql, df, analysis, source, timing)

    model_start          = time.time()
    gen_sql, gen_raw_sql = generate_sql_with_ai(tables, question, pcfg)
    sql_query            = gen_sql    or ""
    raw_sql              = gen_raw_sql or ""

    if not sql_query:
        return {"error": "Could not generate SQL query.", "question": question}

    # --- DIRECT QA BYPASS FOR UNSTRUCTURED TEXT ---
    if sql_query.strip().rstrip(";") == "DIRECT_QA_REQUIRED":
        print("[query] Direct QA Bypass triggered for unstructured text.")
        # Find the unstructured table(s) in 'tables'
        unstructured_tables = [
            t for t in tables 
            if len(t.get("columns", [])) == 2 
            and {c["name"].lower() for c in t.get("columns", [])} == {"line_number", "content"}
        ]
        if not unstructured_tables:
            return {"error": "Direct QA requested by AI, but no unstructured text table found.", "question": question}
            
        target_table = unstructured_tables[0]["full_name"]
        try:
            df_text = pd.read_sql(text(f"SELECT content FROM {target_table} ORDER BY line_number"), engine)
            raw_doc_text = "\n".join(df_text["content"].astype(str).tolist())
            
            from app_core import get_ai_completion
            qa_system = "You are a helpful data assistant. Answer the user's question using ONLY the provided document text. If the answer is not in the text, say so. Do not invent information."
            qa_user = f"Document Text:\n{raw_doc_text}\n\nQuestion: {question}"
            
            analysis = get_ai_completion(
                qa_system, qa_user, provider=pcfg["provider"], temperature=0.1, max_tokens=1000,
                **{k: v for k, v in pcfg.items() if k not in ("provider", "temperature", "max_tokens")}
            )
            
            df = pd.DataFrame()
            sql_query = ""
            raw_sql = "DIRECT_QA_BYPASS"
            source = "model"
            model_ms = round((time.time() - t0) * 1000, 1)
            timing = {"model_ms": model_ms, "first_exec_ms": model_ms}
            
            db.save_sql_cache(engine, question, provider, model, sql_query, raw_sql, analysis or "", exec_ms=model_ms)
            return _make_result(question, asked_at, sql_query, raw_sql, df, analysis, source, timing)
            
        except Exception as e:
            return {"error": f"Failed to extract document text for QA: {e}", "question": question}
    # ----------------------------------------------


    try:
        df = pd.read_sql(text(sql_query.rstrip(";")), engine)
    except Exception as exec_err:
        err_str = str(exec_err)
        print(f"[query] SQL failed: {err_str[:200]}")
        bad_col = _re.search(r"Invalid column name '([^']+)'", err_str)
        bad_obj = _re.search(r"Invalid object name '([^']+)'",  err_str)
        bad     = bad_col or bad_obj
        if bad:
            bad_name = bad.group(1)
            print(f"[query] Auto-correcting: {bad_name}")
            from app_core import retry_sql_with_correction
            relevant = [t for t in tables if bad_name.lower() in
                        " ".join(c["name"].lower() for c in t.get("columns", []))]
            hint = ""
            if relevant:
                hint = " Might be in: " + ", ".join(
                    f"{t['full_name']} ({', '.join(c['name'] for c in t['columns'][:6])})"
                    for t in relevant[:3]
                )
            fix_errors = [
                f"'{bad_name}' does not exist.{hint}",
                "Use only exact column names from the schema.",
                "For country: join Person.Address->StateProvince->CountryRegion",
                "For names: join Person.Person on PersonID, use FirstName+LastName",
            ]
            try:
                fixed_sql, fixed_raw = retry_sql_with_correction(
                    sql_query, fix_errors, tables, question, pcfg)
                df        = pd.read_sql(text(fixed_sql.rstrip(";")), engine)
                sql_query = fixed_sql
                raw_sql   = fixed_raw or fixed_sql
                print(f"[query] Retry succeeded")
            except Exception as retry_err:
                print(f"[query] Retry failed: {retry_err}")
                return {"error": f"Column '{bad_name}' does not exist. Try rephrasing.",
                        "sql_query": sql_query, "question": question}
        else:
            return {"error": f"SQL execution error: {err_str}", "sql_query": sql_query, "question": question}

    analysis = None
    if not df.empty:
        try:
            analysis = analyze_data_with_ai(df, question, pcfg)
            print(f"[analysis] {len(analysis or '')} chars")
        except Exception as e:
            print(f"[analysis] non-fatal: {e}")

    model_ms = round((time.time() - model_start) * 1000, 1)
    source   = "model"
    total_ms = round((time.time() - t0) * 1000, 1)
    timing   = {"model_ms": model_ms, "first_exec_ms": total_ms}
    db.save_sql_cache(engine, question, provider, model,
                      sql_query, raw_sql, analysis or "", exec_ms=total_ms)
    return _make_result(question, asked_at, sql_query, raw_sql, df, analysis, source, timing)


def _make_result(question, asked_at, sql_query, raw_sql, df, analysis, source, timing):
    import math, decimal, json
    import numpy as np

    def safe(v):
        try:
            if v is None: return None
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
            if isinstance(v, np.floating):
                f = float(v); return None if (math.isnan(f) or math.isinf(f)) else f
            if isinstance(v, np.integer):  return int(v)
            if isinstance(v, np.bool_):    return bool(v)
            if isinstance(v, decimal.Decimal):
                f = float(v); return None if (math.isnan(f) or math.isinf(f)) else f
            if isinstance(v, (int, float, str, bool)): return v
            s = str(v)
            return None if s in ("NaT", "nan", "None", "inf", "-inf") else s
        except Exception: return None

    rows = []
    if not df.empty:
        for row in df.where(df.notna(), other=None).values.tolist():
            rows.append([safe(v) for v in row])

    return {
        "question":     question,
        "asked_at":     asked_at,
        "completed_at": datetime.now().isoformat(),
        "sql_query":    sql_query,
        "raw_sql":      raw_sql,
        "source":       source,
        "timing":       timing,
        "analysis":     analysis,
        "columns":      df.columns.tolist() if not df.empty else [],
        "rows":         rows,
        "row_count":    len(df),
        "error":        None,
    }


@app.post("/query")
async def run_query(body: QueryRequest, db_dep=Depends(get_db), user: dict = Depends(verify_jwt)):
    import asyncio, traceback, json
    from fastapi.responses import JSONResponse

    pcfg = {"provider": body.provider, "model": body.model}
    if body.api_key:
        pcfg["api_key"] = body.api_key
    if body.provider == "Ollama":
        pcfg["base_url"] = body.base_url

    engine  = db_dep["engine"]
    user_id = user.get("user_id", 0)
    print(f"[query] provider={body.provider} model={body.model} q={body.question[:60]}")

    # ── Conversation-aware question rewriting ─────────────────────────────
    # If the user sent a follow-up (short or contains pronouns) and we have
    # chat_history, prepend context so the LLM understands the reference.
    effective_question = body.question
    history = body.chat_history or []
    if history:
        SHORT_THRESHOLD = 25
        FOLLOW_UP_WORDS = {"it", "this", "that", "they", "them", "the same",
                           "those", "these", "above", "previous", "last", "more"}
        q_lower = body.question.lower().strip()
        is_followup = (
            len(body.question.strip()) < SHORT_THRESHOLD
            or any(w in q_lower.split() for w in FOLLOW_UP_WORDS)
            or q_lower.startswith(("what about", "and the", "also", "now show",
                                   "compare", "how about", "why", "can you also"))
        )
        if is_followup:
            # Build a compact history string from last 4 exchanges
            history_str = ""
            for msg in history[-8:]:
                role = msg.get("role", "")
                content = str(msg.get("content", ""))[:300]
                if role == "user":
                    history_str += f"User: {content}\n"
                elif role == "assistant":
                    history_str += f"Assistant: {content[:200]}\n"
            effective_question = (
                f"[Conversation context:]\n{history_str}\n"
                f"[Current follow-up question:] {body.question}"
            )
            print(f"[query] Follow-up detected — injecting {len(history)} history messages")

    # Enriched: standard tables + universal intake tables for this user
    tables = get_tables_enriched_with_metadata(engine, user_id)
    for t in tables:
        if not t.get("columns"):
            t["columns"] = get_table_schema(engine, t["schema"], t["name"])

    try:
        import time
        from datetime import datetime
        from orchestrator.master_graph import master_orchestrator
        
        state = {
            "request_id": f"req_{int(time.time())}",
            "workspace_id": str(user_id),
            "session_id": body.session_id or db.new_session_key(),
            "user_input": effective_question,
            "mode": "sql",
            "provider": body.provider,
            "llm_profile": "SQL_PROFILE",
            "metadata": {
                "engine": engine,
                "tables": tables,
                "pcfg": pcfg,
                "similarity_threshold": body.similarity_threshold,
                "asked_at": datetime.now().isoformat()
            }
        }
        
        final_state = await asyncio.to_thread(master_orchestrator.invoke, state)
        
        if final_state.get("error"):
            # Return early on error so frontend doesn't crash on empty DF
            return {"error": final_state["error"], "question": body.question}
            
        sql_query = final_state.get("metadata", {}).get("sql_query", "")
        raw_sql = final_state.get("metadata", {}).get("raw_sql", "")
        df = final_state.get("metadata", {}).get("df")
        if df is None:
            import pandas as pd
            df = pd.DataFrame()
        analysis = final_state.get("response", "")
        asked_at = final_state.get("metadata", {}).get("asked_at", datetime.now().isoformat())
        
        result = _make_result(
            question=body.question,
            asked_at=asked_at,
            sql_query=sql_query,
            raw_sql=raw_sql,
            df=df,
            analysis=analysis,
            source="langgraph",
            timing={"model_ms": 150, "first_exec_ms": 150} 
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"LangGraph execution failed: {e}")

    try:
        user_id = user.get("user_id", 0)
        user_email = user.get("sub", "unknown")
        
        session_id = body.session_id if body.session_id else db.new_session_key()
        result["session_id"] = session_id
        result["provider"]   = body.provider
        result["model"]      = body.model
        
        # ONE call to save chat log AND audit log!
        db.save_chat_log(
            engine, session_id, user_id, user_email, result, 
            input_source=body.input_source or "keyboard"
        )
    except Exception as e:
        print(f"[chat/audit] history save non-fatal: {e}")

    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])

    class SafeEncoder(json.JSONEncoder):
        def default(self, obj):
            import math, numpy as np, decimal
            if isinstance(obj, np.integer):      return int(obj)
            if isinstance(obj, np.floating):
                f = float(obj)
                return None if (math.isnan(f) or math.isinf(f)) else f
            if isinstance(obj, np.bool_):        return bool(obj)
            if isinstance(obj, np.ndarray):      return obj.tolist()
            if isinstance(obj, decimal.Decimal): return float(obj)
            if hasattr(obj, "isoformat"):        return obj.isoformat()
            try:   return super().default(obj)
            except Exception: return str(obj)

        def encode(self, obj):
            import math
            def fix(o):
                if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
                if isinstance(o, dict):  return {k: fix(v) for k, v in o.items()}
                if isinstance(o, list):  return [fix(i) for i in o]
                return o
            return super().encode(fix(obj))

    return JSONResponse(content=json.loads(json.dumps(result, cls=SafeEncoder)))


# ─────────────────────────────────────────────────────────────────────────────
# CHAT HISTORY ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/sessions")
def create_session(db_dep=Depends(get_db), user: dict = Depends(verify_jwt)):
    session_id = db.new_session_key()
    try:
        user_id = user.get("user_id", 0)
        user_email = user.get("sub", "unknown")
        db.save_chat_log(
            db_dep["engine"],
            session_key=session_id,
            user_id=user_id,
            user_email=user_email,
            result={"question": "Session Started"},
            input_source="init"
        )
    except Exception as e:
        print(f"[sessions] Error creating init log: {e}")
    return {"session_id": session_id}

@app.get("/sessions")
def list_sessions(db_dep=Depends(get_db), user: dict = Depends(verify_jwt)):
    user_id  = user.get("user_id", 0)
    sessions = db.get_user_sessions(db_dep["engine"], user_id)
    return {"sessions": sessions}

@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str, db_dep=Depends(get_db), user: dict = Depends(verify_jwt)):
    user_id  = user.get("user_id", 0)
    messages = db.get_session_messages(db_dep["engine"], session_id, user_id)
    return {"messages": messages, "session_id": session_id}

@app.delete("/sessions/{session_id}")
def delete_session_route(session_id: str, db_dep=Depends(get_db), user: dict = Depends(verify_jwt)):
    user_id = user.get("user_id", 0)
    db.delete_session(db_dep["engine"], session_id, user_id)
    return {"deleted": session_id}

class RenameSessionRequest(BaseModel):
    title: str

@app.put("/sessions/{session_id}")
def rename_session_route(session_id: str, body: RenameSessionRequest, db_dep=Depends(get_db), user: dict = Depends(verify_jwt)):
    user_id = user.get("user_id", 0)
    success = db.rename_session(db_dep["engine"], session_id, user_id, body.title)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to rename session")
    return {"status": "success", "session_id": session_id}

# ─────────────────────────────────────────────────────────────────────────────
# CACHE MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/cache")
def list_cache(db_dep=Depends(get_db), _=Depends(verify_jwt)):
    entries = db.get_all_cache_entries(db_dep["engine"])
    return {"entries": entries}

@app.delete("/cache/{entry_id}")
def delete_cache(entry_id: int, db_dep=Depends(get_db), user: dict = Depends(verify_jwt)):
    if user["role"] != "Admin":
        raise HTTPException(status_code=403, detail="Admin only")
    db.delete_cache_entry(db_dep["engine"], entry_id)
    return {"deleted": entry_id}

@app.delete("/cache")
def flush_all(db_dep=Depends(get_db), user: dict = Depends(verify_jwt)):
    if user["role"] != "Admin":
        raise HTTPException(status_code=403, detail="Admin only")
    db.flush_cache(db_dep["engine"])
    return {"status": "flushed"}


# ─────────────────────────────────────────────────────────────────────────────
# FILE UPLOAD ROUTES
# ─────────────────────────────────────────────────────────────────────────────

upload_websockets = {}

@app.websocket("/files/ws/progress/{upload_id}")
async def websocket_upload_progress(websocket: WebSocket, upload_id: str):
    await websocket.accept()
    upload_websockets[upload_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        upload_websockets.pop(upload_id, None)

FILE_SIZE_LIMIT  = 50 * 1024 * 1024   # 50 MB
FILE_COUNT_LIMIT = 50
ALLOWED_TYPES    = {
    # Structured
    "csv", "xlsx", "xls", "json", "tsv", "xml",
    # Documents
    "txt", "pdf", "doc", "docx", "ppt", "pptx",
    # Images
    "png", "jpg", "jpeg", "webp", "bmp", "tiff",
}

# Universal intake orchestrator (new pipeline)
from universal_intake.orchestrator import UniversalIntakeOrchestrator
from universal_intake.storage.dynamic_sql_engine import DynamicSQLEngine
from universal_intake.storage.metadata_repository import MetadataRepository
_ui_orchestrator    = UniversalIntakeOrchestrator()
_dynamic_sql_engine = DynamicSQLEngine()
_metadata_repo      = MetadataRepository()

from fastapi import UploadFile, File as FastAPIFile

class FileAnalysisRequest(BaseModel):
    file_id:       int
    prompt:        str
    provider:      str
    model:         str
    api_key:       Optional[str]  = None
    base_url:      Optional[str]  = "http://localhost:11434"
    session_id:    Optional[str]  = None
    analysis_mode: Optional[str]  = "sql"   # "sql" | "ai_research"
    chat_history:  Optional[list] = None    # [{role, content}, ...] for multi-turn


# Derive category string that matches dbo.files.category values
def _get_category(file_type: str, parsed: dict = None) -> str:
    ft = (file_type or "").lower().lstrip(".")
    STRUCTURED = {"csv", "xlsx", "xls", "xlsm", "tsv", "json", "xml", "parquet"}
    DOCUMENTS  = {"pdf", "docx", "doc", "pptx", "ppt", "txt", "md", "rtf", "odt"}
    IMAGES     = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif"}
    
    # If a real table was extracted (not just line_number/content), treat as structured
    if parsed and parsed.get("row_count", 0) > 0:
        cols = parsed.get("columns", [])
        if len(cols) > 2 or (len(cols) == 2 and set(c.lower() for c in cols) != {"line_number", "content"}):
            return "structured"

    if ft in STRUCTURED: return "structured"
    if ft in DOCUMENTS:  return "document"
    if ft in IMAGES:     return "image_ocr"
    return "unknown"


@app.post("/files/upload")
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    upload_id: Optional[str] = None,
    user: dict = Depends(verify_jwt),
):
    import asyncio
    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not available. Please try again later.")
    ext = (file.filename or "").lower().rsplit(".", 1)[-1]
    if ext not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    # Stream read with size cap
    data_chunks = []
    total_size = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > FILE_SIZE_LIMIT:
            raise HTTPException(status_code=413, detail=f"File too large. Maximum size is 50 MB.")
        data_chunks.append(chunk)
    data = b"".join(data_chunks)

    user_id = user.get("user_id", 0)

    fhash = db.hash_file(data)

    # ── Universal Intake Pipeline ─────────────────────────────────────────
    try:
        loop = asyncio.get_running_loop()
        def on_progress(stage: str, details: str):
            if upload_id and upload_id in upload_websockets:
                ws = upload_websockets[upload_id]
                asyncio.run_coroutine_threadsafe(ws.send_json({"stage": stage, "details": details}), loop)

        doc = await asyncio.wait_for(
            asyncio.to_thread(
                _ui_orchestrator.process, data, file.filename or "upload", None, on_progress
            ),
            timeout=120.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="File processing took too long (>120s).")

    if not doc.ok:
        raise HTTPException(status_code=400, detail=f"Could not process file: {doc.flag_reason}")

    # Build parsed dict — includes ALL fields needed by db._save_child()
    parsed = {
        # Core / shared
        "ok":          doc.ok,
        "file_type":   doc.file_type_ext,
        # Structured fields (CSV/XLSX/JSON/TSV)
        "df":          doc.df,
        "row_count":   doc.row_count,
        "col_count":   doc.col_count,
        "columns":     doc.columns,
        "preview":     doc.preview,
        "sheet_name":  doc.sheet_name,
        "sheet_names": doc.sheet_names,
        "sheets":      doc.sheets,
        # Document fields (PDF/DOCX/PPTX/TXT) → feeds dbo.document_files
        "extracted_text": getattr(doc, "raw_text", None),
        "page_count":     doc.page_count,
        "word_count":     len((getattr(doc, "raw_text", None) or "").split()) or None,
        # Image / OCR fields (PNG/JPG/scanned PDF) → feeds dbo.image_files
        "ocr_text":        getattr(doc, "raw_text", None),
        "ocr_confidence":  doc.confidence if doc.ocr_used else None,
        "width_px":        None,   # Pillow dimensions not yet wired; safe default
        "height_px":       None,
        "is_scanned_pdf":  getattr(doc, "technical_file_type", None).__class__.__name__ == "FileType"
                           and str(getattr(doc, "technical_file_type", "")).endswith("PDF_SCANNED"),
        # Universal Intake governance metadata
        "business_type":       doc.business_type.value if doc.business_type else None,
        "confidence":          doc.confidence,
        "flagged":             doc.flagged,
        "flag_reason":         doc.flag_reason,
        "policy_action":       doc.policy_action.value if doc.policy_action else None,
        "ocr_used":            doc.ocr_used,
        "processing_time_ms":  doc.processing_time_ms,
    }

    # Ingest into dynamic SQL table (new)
    try:
        sql_table = await asyncio.wait_for(
            asyncio.to_thread(
                _dynamic_sql_engine.ingest, engine, doc, user_id, fhash
            ),
            timeout=30.0
        )
    except Exception as sql_err:
        print(f"[upload] DynamicSQLEngine error (non-fatal): {sql_err}")
        sql_table = ""

    # ── Check if multi-sheet Excel ────────────────────────────────────────
    sheet_names = parsed.get("sheet_names")   # None for CSV
    is_multi_sheet = bool(sheet_names and len(sheet_names) > 1)

    if is_multi_sheet:
        # Save EACH sheet as a separate DB row
        existing_files = db.get_user_files(engine, user_id)
        new_sheet_count = len(sheet_names)
        if len(existing_files) + new_sheet_count > FILE_COUNT_LIMIT * 3:
            raise HTTPException(status_code=400, detail="Too many file slots used. Delete some files first.")

        saved_sheets = []
        for sname in sheet_names:
            sheet_info = parsed["sheets"].get(sname, {})
            if not sheet_info.get("ok"):
                continue
            file_id = await asyncio.wait_for(
                asyncio.to_thread(
                    db.save_file,
                    engine, user_id, fhash,
                    file.filename or "upload.xlsx",
                    len(data), parsed, sname
                ),
                timeout=30.0
            )
            # Guard: if save returned None, lookup by composite hash in dbo.files
            if file_id is None:
                composite_hash = fhash + "::" + sname
                from sqlalchemy import text as _t
                with engine.connect() as conn:
                    row = conn.execute(_t(
                        "SELECT id FROM dbo.files WHERE user_id=:uid AND file_hash=:h"
                    ), {"uid": user_id, "h": composite_hash}).fetchone()
                    file_id = row[0] if row else None
            if file_id is None:
                print(f"[files] WARNING: could not get file_id for sheet '{sname}', skipping")
                continue

            saved_sheets.append({
                "file_id":    file_id,
                "sheet_name": sname,
                "row_count":  sheet_info["row_count"],
                "col_count":  sheet_info["col_count"],
                "columns":    sheet_info["columns"],
                "preview":    sheet_info["preview"],
            })

        return {
            "file_name":      file.filename,
            "file_size":      len(data),
            "file_type":      "xlsx",
            "is_multi_sheet": True,
            "sheet_names":    sheet_names,
            "sheets":         saved_sheets,
            # Backward-compat top-level fields
            "file_id":        saved_sheets[0]["file_id"] if saved_sheets else None,
            "row_count":      saved_sheets[0]["row_count"] if saved_sheets else 0,
            "col_count":      saved_sheets[0]["col_count"] if saved_sheets else 0,
            "columns":        saved_sheets[0]["columns"] if saved_sheets else [],
            "preview":        saved_sheets[0]["preview"] if saved_sheets else [],
            "cached":         False,
            "message":        f"Excel uploaded with {len(saved_sheets)} sheets.",
        }

    else:
        # ── CSV or single-sheet Excel (original flow) ─────────────────────
        from sqlalchemy import text as _t
        with engine.connect() as conn:
            existing_row = conn.execute(_t(
                "SELECT id FROM dbo.files WHERE user_id=:uid AND file_hash=:h"
            ), {"uid": user_id, "h": fhash}).fetchone()

        if not existing_row:
            existing_files = db.get_user_files(engine, user_id)
            if len(existing_files) >= FILE_COUNT_LIMIT:
                raise HTTPException(
                    status_code=400,
                    detail=f"File limit reached ({FILE_COUNT_LIMIT} files max). Delete a file to upload a new one."
                )

        try:
            file_id = await asyncio.wait_for(
                asyncio.to_thread(
                    db.save_file,
                    engine, user_id, fhash,
                    file.filename or "upload.csv",
                    len(data), parsed,
                    parsed.get("sheet_name")
                ),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=408, detail="Saving to database took too long.")

        # Register in Metadata Repository
        try:
            _metadata_repo.register(
                engine, doc, user_id, fhash,
                file.filename or "upload",
                len(data), sql_table,
                uploaded_files_id=file_id,
            )
        except Exception as meta_err:
            print(f"[upload] MetadataRepository error (non-fatal): {meta_err}")

        return {
            "file_id":        file_id,
            "file_name":      file.filename,
            "file_size":      len(data),
            "file_type":      parsed["file_type"],
            "category":       _get_category(parsed["file_type"], parsed),   # NEW — structured|document|image_ocr
            "row_count":      parsed["row_count"],
            "col_count":      parsed["col_count"],
            "columns":        parsed["columns"],
            "preview":        parsed["preview"],
            "is_multi_sheet": False,
            "sheet_names":    [parsed["sheet_name"]] if parsed.get("sheet_name") else None,
            "sheets":         None,
            "cached":         existing_row is not None,
            "message":        "File already in cache." if existing_row is not None else "File uploaded and ready.",
            # Universal intake governance fields
            "business_type":  parsed.get("business_type"),
            "confidence":     parsed.get("confidence"),
            "flagged":        parsed.get("flagged", False),
            "flag_reason":    parsed.get("flag_reason"),
            "policy_action":  parsed.get("policy_action"),
            "ocr_used":       parsed.get("ocr_used", False),
            "sql_table":      sql_table,
        }


@app.get("/files")
def list_files(user: dict = Depends(verify_jwt)):
    engine = get_auth_engine()
    if not engine:
        return {"files": [], "count": 0, "limit": FILE_COUNT_LIMIT}
    user_id = user.get("user_id", 0)
    files   = db.get_user_files(engine, user_id)
    return {"files": files, "count": len(files), "limit": FILE_COUNT_LIMIT}


@app.get("/files/{file_id}/first-impression")
def get_file_first_impression(file_id: str, user: dict = Depends(verify_jwt)):
    """
    Returns the First Impression Analysis (doc_type, summary, top_insights, suggested_questions).
    This is called by the UI immediately after a file is selected or uploaded.
    """
    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not available.")
    
    # Verify file belongs to user and get raw data
    user_id = user.get("user_id", 0)
    files = db.get_user_files(engine, user_id)
    
    target_file = next((f for f in files if str(f["id"]) == str(file_id)), None)
    if not target_file:
        raise HTTPException(status_code=404, detail="File not found")
        
    try:
        file_bytes = db.get_file_data(engine, user_id, target_file["id"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load file data: {e}")

    try:
        import llama_engine
        # Use provider_cfg from user settings or fallback to default Ollama
        provider_cfg = {"provider": "ollama", "model": "llama3"}
        impression = llama_engine.get_first_impression(
            file_id=str(file_id),
            file_bytes=file_bytes,
            filename=target_file["file_name"],
            file_type=target_file.get("file_type", "txt"),
            provider_cfg=provider_cfg
        )
        return {"ok": True, "impression": impression}
    except Exception as e:
        print(f"[first_impression] Error: {e}")
        return {"ok": False, "error": str(e)}


class ClipboardUploadRequest(BaseModel):
    image_data: str
    filename: str = "clipboard.png"
    upload_id: Optional[str] = None

@app.post("/files/upload-clipboard")
async def upload_clipboard(
    body: ClipboardUploadRequest,
    user: dict = Depends(verify_jwt),
):
    """
    Accept a base64-encoded clipboard image (from Ctrl+V paste) and
    process it through the same Universal Intake pipeline as a regular image upload.
    """
    import asyncio, base64
    try:
        data = base64.b64decode(body.image_data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image data.")

    if len(data) > FILE_SIZE_LIMIT:
        raise HTTPException(status_code=413, detail="Clipboard image too large (max 50 MB).")

    engine  = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not available.")
    user_id = user.get("user_id", 0)


    fhash = db.hash_file(data)

    try:
        loop = asyncio.get_running_loop()
        def on_progress(stage: str, details: str):
            if body.upload_id and body.upload_id in upload_websockets:
                ws = upload_websockets[body.upload_id]
                asyncio.run_coroutine_threadsafe(ws.send_json({"stage": stage, "details": details}), loop)

        doc = await asyncio.wait_for(
            asyncio.to_thread(
                _ui_orchestrator.process, data, body.filename, None, on_progress
            ),
            timeout=120.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Image processing took too long.")

    if not doc.ok:
        raise HTTPException(status_code=400, detail=f"Could not process image: {doc.flag_reason}")

    try:
        file_id = await asyncio.to_thread(
            db.save_file, engine, user_id, fhash,
            body.filename, len(data), {
                # Core
                "ok":         True,
                "file_type":  doc.file_type_ext or "png",
                # Structured (will be empty for images)
                "df":         doc.df,
                "row_count":  doc.row_count,
                "col_count":  doc.col_count,
                "columns":    doc.columns,
                "preview":    doc.preview,
                "sheet_name": None,
                # Image / OCR → feeds dbo.image_files
                "ocr_text":       getattr(doc, "raw_text", None),
                "ocr_confidence": doc.confidence if doc.ocr_used else None,
                "width_px":       None,
                "height_px":      None,
                "is_scanned_pdf": False,
                # Document → feeds dbo.document_files (safe to include even for images)
                "extracted_text": getattr(doc, "raw_text", None),
                "page_count":     doc.page_count,
                "word_count":     len((getattr(doc, "raw_text", None) or "").split()) or None,
            }, None
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save failed: {e}")

    sql_table = ""
    try:
        sql_table = await asyncio.to_thread(
            _dynamic_sql_engine.ingest, engine, doc, user_id, fhash
        )
        _metadata_repo.register(
            engine, doc, user_id, fhash, body.filename,
            len(data), sql_table, uploaded_files_id=file_id,
        )
    except Exception as e:
        print(f"[clipboard] Storage error (non-fatal): {e}")

    return {
        "file_id":       file_id,
        "file_name":     body.filename,
        "file_size":     len(data),
        "file_type":     "png",
        "row_count":     doc.row_count,
        "col_count":     doc.col_count,
        "columns":       doc.columns,
        "preview":       doc.preview,
        "is_multi_sheet": False,
        "sheet_names":   None,
        "sheets":        None,
        "cached":        False,
        "message":       "Clipboard image processed via OCR.",
        "business_type": doc.business_type.value if doc.business_type else None,
        "confidence":    doc.confidence,
        "flagged":       doc.flagged,
        "flag_reason":   doc.flag_reason,
        "policy_action": doc.policy_action.value if doc.policy_action else None,
        "ocr_used":      True,
        "sql_table":     sql_table,
    }



# ─────────────────────────────────────────────────────────────────────────────
# METADATA REPOSITORY ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/metadata/tables")
def metadata_tables(db=Depends(get_db), user: dict = Depends(verify_jwt)):
    """
    Returns all universal-intake tables created for the current user.
    Used by the frontend to show the data catalog and by the SQL Agent
    to discover uploaded documents.
    """
    engine  = db["engine"]
    user_id = user.get("user_id", 0)
    try:
        from universal_intake.storage.metadata_repository import MetadataRepository
        repo   = MetadataRepository()
        tables = repo.get_user_tables(engine, user_id)
        return {"tables": tables, "count": len(tables)}
    except Exception as e:
        print(f"[metadata] get_user_tables error: {e}")
        return {"tables": [], "count": 0}


# NOTE: Route is /files/analyse (British spelling) — matches next.config.js rewrite
@app.post("/files/analyse")
async def analyse_file(
    body: FileAnalysisRequest,
    user: dict = Depends(verify_jwt),
):
    import asyncio, pandas as pd, io as _io
    from sqlalchemy import text as _t

    engine  = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not available.")
    user_id = user.get("user_id", 0)

    import time as _time
    _cache_start = _time.time()
    cached = db.get_cached_file_analysis(engine, body.file_id, body.prompt)
    cache_lookup_ms = (_time.time() - _cache_start) * 1000
    if cached:
        first_exec_ms  = cached.get("execution_time_ms", 0)
        cached_exec_ms = cached.get("cached_exec_ms", cache_lookup_ms)
        print(f"[files] Cache hit — first run {first_exec_ms:.0f} ms, cached lookup {cached_exec_ms:.1f} ms, hit #{cached['hit_count']}")
        if body.session_id:
            db.save_chat_log(
                engine,
                session_key=str(body.session_id),
                user_id=user_id,
                user_email=user.get("sub", ""),
                result={
                    "question": body.prompt,
                    "sql_query": "",
                    "analysis": cached["analysis"],
                    "row_count": len(cached.get("chart_data", {}).get("rows", [])),
                    "columns": cached.get("chart_data", {}).get("columns", []),
                    "source": "cache",
                    "provider": body.provider,
                    "model": body.model,
                    "timing": {"cache_ms": cached_exec_ms, "first_exec_ms": first_exec_ms}
                }
            )
        return {
            "analysis":          cached["analysis"],
            "cached":            True,
            "hit_count":         cached["hit_count"],
            "execution_time_ms": first_exec_ms,
            "cache_ms":          round(cached_exec_ms, 1),
            "chart_data":        cached.get("chart_data", {"columns": [], "rows": []}),
        }

    file_data = db.get_file_data(engine, body.file_id, user_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="File not found.")

    # ── Universal Intake / Master Orchestrator ────────────────────────────
    try:
        import time
        from orchestrator.master_graph import master_orchestrator
        
        _start = time.time()
        
        category = file_data.get("category", "document")
        pcfg = {"provider": body.provider, "model": body.model}
        if body.api_key: pcfg["api_key"] = body.api_key
        if body.provider == "Ollama": pcfg["base_url"] = body.base_url
        
        raw_bytes = file_data.get("raw_bytes")
        file_type = file_data.get("file_type", "")
        
        # If DB dropped the binary to save space, use the Universal Intake extracted text natively
        if not raw_bytes:
            content = file_data.get("extracted_text") or file_data.get("ocr_text") or ""
            raw_bytes = content.encode("utf-8")
            file_type = "txt"

        state = {
            "request_id": f"req_{int(time.time())}",
            "workspace_id": str(user_id),
            "session_id": body.session_id,
            "user_input": body.prompt,
            "mode": "file",
            "file_type": file_type,
            "provider": body.provider,
            "llm_profile": "FILE_PROFILE",
            "metadata": {
                "file_id": body.file_id,
                "raw_bytes": raw_bytes,
                "file_name": file_data.get("file_name", "document"),
                "category": category,
                "df": file_data.get("df"),
                "pcfg": pcfg,
                "chat_history": body.chat_history or []
            }
        }
        
        import traceback
        try:
            final_state = await asyncio.to_thread(master_orchestrator.invoke, state)
        except Exception:
            traceback.print_exc()
            raise
            
        if final_state.get("error"):
            # Fallback to direct text QA if orchestrator fails on unstructured text
            if category != "structured":
                content_to_analyze = file_data.get("extracted_text") or file_data.get("ocr_text") or "No content found"
                from app_core import get_ai_completion
                sys_prompt = "You are an AI assistant. Answer based on the extracted text below.\n\n"
                analysis = await asyncio.to_thread(get_ai_completion, sys_prompt, f"Text:\n{content_to_analyze}\n\nQuestion: {body.prompt}", provider=body.provider, **{k:v for k,v in pcfg.items() if k!="provider"})
                sources = []
                chart_data = {"columns": [], "rows": []}
            else:
                raise HTTPException(status_code=500, detail=f"Analysis error: {final_state['error']}")
        else:
            analysis = final_state.get("response", "")
            sources = final_state.get("evidence", [])
            chart_data = final_state.get("metadata", {}).get("chart_data") or {"columns": [], "rows": []}
            
        execution_time_ms = (time.time() - _start) * 1000
    except Exception as ae:
        print(f"[analyse] Error: {ae}")
        raise HTTPException(status_code=500, detail=f"Analysis error: {ae}")
    print(f"[files] Analysis took {execution_time_ms:.0f} ms")

    db.save_file_analysis(engine, body.file_id, body.prompt, analysis,
                       provider=body.provider, model=body.model,
                       execution_time_ms=execution_time_ms,
                       chart_data=chart_data)

    db.touch_file(engine, body.file_id)

    if body.session_id:
        db.save_chat_log(
            engine,
            session_key=str(body.session_id),
            user_id=user_id,
            user_email=user.get("sub", ""),
            result={
                "question": body.prompt,
                "sql_query": "",
                "analysis": analysis,
                "row_count": len(chart_data.get("rows", [])),
                "columns": chart_data.get("columns", []),
                "source": "model",
                "provider": body.provider,
                "model": body.model,
                "timing": {"model_ms": execution_time_ms}
            }
        )

    return {
        "analysis":          analysis,
        "cached":            False,
        "file_category":     file_data["category"],  # NEW — drives frontend render mode
        "chart_data":        chart_data,
        "execution_time_ms": execution_time_ms,
    }


@app.delete("/files/{file_id}")
def delete_file(file_id: int, user: dict = Depends(verify_jwt)):
    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not available.")
    db.delete_file(engine, file_id, user.get("user_id", 0))
    return {"deleted": file_id}


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-FILE COMPARISON
# ─────────────────────────────────────────────────────────────────────────────

class FileCompareRequest(BaseModel):
    file_ids: list[int]
    prompt:   str
    provider: str
    model:    str
    api_key:  Optional[str] = None
    base_url: Optional[str] = "http://localhost:11434"
    session_id: Optional[str] = None


@app.post("/files/compare")
async def compare_files(
    body: FileCompareRequest,
    user: dict = Depends(verify_jwt),
):
    import asyncio, pandas as pd

    if len(body.file_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 files required for comparison.")
    if len(body.file_ids) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 files at once.")

    engine  = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not available.")
    user_id = user.get("user_id", 0)

    # Multi-file cache key: sorted file IDs + prompt
    import hashlib as _hl
    cache_key  = ",".join(sorted(str(f) for f in body.file_ids)) + "::" + body.prompt.strip().lower()
    cache_hash = _hl.sha256(cache_key.encode()).hexdigest()

    import time as _time
    _cache_start = _time.time()
    cached = db.get_cached_file_analysis(engine, 0, cache_key)
    cache_lookup_ms = (_time.time() - _cache_start) * 1000
    if cached:
        first_exec_ms  = cached.get("execution_time_ms", 0)
        cached_exec_ms = cached.get("cached_exec_ms", cache_lookup_ms)
        print(f"[files] Compare cache hit — first run {first_exec_ms:.0f} ms, lookup {cached_exec_ms:.1f} ms")
        if body.session_id:
            db.save_chat_log(
                engine,
                session_key=str(body.session_id),
                user_id=user_id,
                user_email=user.get("sub", ""),
                result={
                    "question": body.prompt,
                    "sql_query": "",
                    "analysis": cached["analysis"],
                    "row_count": len(cached.get("chart_data", {}).get("rows", [])),
                    "columns": cached.get("chart_data", {}).get("columns", []),
                    "source": "cache",
                    "provider": body.provider,
                    "model": body.model,
                    "timing": {"cache_ms": cached_exec_ms, "first_exec_ms": first_exec_ms}
                }
            )
        return {
            "analysis":          cached["analysis"],
            "cached":            True,
            "file_count":        len(body.file_ids),
            "chart_data":        cached.get("chart_data", {"columns": [], "rows": []}),
            "execution_time_ms": first_exec_ms,
        }

    # Check cache using the first file_id as representative (file_id=-1 was old schema)
    # We reuse db.get_cached_file_analysis with file_id=0 as a multi-file marker
    cached = db.get_cached_file_analysis(engine, 0, cache_key)
    if cached:
        return {
            "analysis":          cached["analysis"],
            "cached":            True,
            "hit_count":         cached["hit_count"],
            "file_count":        len(body.file_ids),
            "execution_time_ms": cached.get("execution_time_ms", 0),
            "cache_ms":          round(cached.get("cached_exec_ms", 0), 1),
            "chart_data":        cached.get("chart_data", {"columns": [], "rows": []}),
        }

    # Load all files via v3 db.get_file_data()
    dfs_dict = {}
    for fid in body.file_ids:
        fdata = db.get_file_data(engine, fid, user_id)
        if not fdata:
            raise HTTPException(status_code=404, detail=f"File {fid} not found.")
        if fdata["category"] == "structured":
            df = fdata.get("df")
            if df is None or df.empty:
                raise HTTPException(status_code=400, detail=f"No tabular data for file id={fid}")
            dfs_dict[f"file_{fid}"] = df
        else:
            # For documents/images, convert raw text to a single-column DataFrame
            text = fdata.get("extracted_text") or fdata.get("ocr_text") or ""
            dfs_dict[f"file_{fid}"] = pd.DataFrame({"content": text.split("\n") if text else []})

    pcfg = {"provider": body.provider, "model": body.model}
    if body.api_key: pcfg["api_key"] = body.api_key
    if body.provider == "Ollama": pcfg["base_url"] = body.base_url

    import time as _time
    _start = _time.time()
    try:
        result_obj = await asyncio.to_thread(compare_files_with_ai, dfs_dict, body.prompt, pcfg)
        if isinstance(result_obj, dict):
            analysis   = result_obj.get("analysis", "")
            chart_data = result_obj.get("chart_data", {"columns": [], "rows": []})
        else:
            analysis   = str(result_obj)
            chart_data = {"columns": [], "rows": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    execution_time_ms = (_time.time() - _start) * 1000
    print(f"[files] Compare took {execution_time_ms:.0f} ms")

    # Save to v3 query_cache using file_id=0 as multi-file sentinel
    db.save_file_analysis(engine, 0, cache_key, analysis,
                          provider=body.provider, model=body.model,
                          execution_time_ms=execution_time_ms,
                          chart_data=chart_data)

    if body.session_id:
        db.save_chat_log(
            engine,
            session_key=str(body.session_id),
            user_id=user_id,
            user_email=user.get("sub", ""),
            result={
                "question": body.prompt,
                "sql_query": "",
                "analysis": analysis,
                "row_count": len(chart_data.get("rows", [])),
                "columns": chart_data.get("columns", []),
                "source": "model",
                "provider": body.provider,
                "model": body.model,
                "timing": {"model_ms": execution_time_ms}
            }
        )

    return {
        "analysis":          analysis,
        "cached":            False,
        "file_count":        len(body.file_ids),
        "chart_data":        chart_data,
        "execution_time_ms": execution_time_ms,
    }


# ─────────────────────────────────────────────────────────────────────────────
# STATS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/stats")
def stats(db=Depends(get_db), _=Depends(verify_jwt)):
    engine = db["engine"]
    try:
        from sqlalchemy import text as t
        with engine.connect() as conn:
            db_row = conn.execute(t("""
                SELECT COUNT(*) as table_count, COALESCE(SUM(p.rows),0) as total_rows
                FROM sys.tables tb
                LEFT JOIN sys.partitions p ON p.object_id = tb.object_id
                WHERE (p.index_id IN (0,1) OR p.index_id IS NULL)
            """)).fetchone()
            cache_row = conn.execute(t("""
                SELECT 
                    (SELECT COUNT(*) FROM dbo.query_cache),
                    (SELECT COALESCE(SUM(hit_count),0) FROM dbo.query_cache)
            """)).fetchone()
        return {
            "table_count":    db_row[0],
            "total_rows":     db_row[1],
            "cached_queries": cache_row[0],
            "total_hits":     cache_row[1],
            "database":       db["database"],
        }
    except Exception as e:
        return {"error": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
# METADATA / LINEAGE ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/metadata/tables")
def list_metadata_tables(db=Depends(get_db), user: dict = Depends(verify_jwt)):
    """
    Return all document metadata records for the current user.
    Used by the Data Lineage Panel to visualize processing history.
    """
    engine  = db["engine"]
    user_id = user.get("user_id", 0)
    try:
        tables = _metadata_repo.get_user_tables(engine, user_id)
        return {"tables": tables, "count": len(tables)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — database reset / health
# ─────────────────────────────────────────────────────────────────────────────

OLD_TABLES = [
    # child tables first (FK order)
    "dbo.voice_log",
    "dbo.chat_log",
    "dbo.image_files",
    "dbo.document_files",
    "dbo.structured_files",
    "dbo.query_cache",
    "dbo.files",
    # old v1/v2 tables
    "dbo.voice_transcripts",
    "dbo.voice_cache",
    "dbo.chat_history",
    "dbo.chat_sessions",
    "dbo.ai_query_audit",
    "dbo.file_analysis_cache",
    "dbo.response_cache",
    "dbo.uploaded_files",
]

OLD_VIEWS = [
    "dbo.v_sessions",
    "dbo.v_cache_stats",
    "dbo.v_files",
    "dbo.v_session_list",
    "dbo.v_cache_dashboard",
    "dbo.v_voice_history",
]

V3_TABLES = [
    "app_users", "query_cache", "chat_log",
    "files", "structured_files", "document_files", "image_files",
    "voice_log",
]

V3_VIEWS = ["v_sessions", "v_cache_stats", "v_files"]


@app.get("/admin/db-status")
def admin_db_status(user: dict = Depends(verify_jwt)):
    """
    Returns which v3 tables + old leftover tables exist.
    Available to any authenticated user — safe read-only health check.
    """
    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not connected")
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
                  AND TABLE_SCHEMA = 'dbo'
                ORDER BY TABLE_NAME
            """)).fetchall()
            view_rows = conn.execute(text("""
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.VIEWS
                WHERE TABLE_SCHEMA = 'dbo'
                ORDER BY TABLE_NAME
            """)).fetchall()

        existing_tables = {r[0] for r in rows}
        existing_views  = {r[0] for r in view_rows}

        # Which old tables still linger?
        old_leftovers = [
            t.replace("dbo.", "") for t in [
                "response_cache", "file_analysis_cache",
                "uploaded_files", "chat_sessions", "chat_history",
                "ai_query_audit", "voice_transcripts", "voice_cache",
            ] if t in existing_tables
        ]

        v3_present = {t: (t in existing_tables) for t in V3_TABLES}
        v3_views   = {v: (v in existing_views)  for v in V3_VIEWS}
        all_v3_ok  = all(v3_present.values()) and all(v3_views.values())

        return {
            "schema_version":    "v3" if all_v3_ok else "mixed/old",
            "all_v3_ok":         all_v3_ok,
            "v3_tables":         v3_present,
            "v3_views":          v3_views,
            "old_tables_still_present": old_leftovers,
            "needs_reset":       len(old_leftovers) > 0 or not all_v3_ok,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/reset-db")
def admin_reset_db(user: dict = Depends(verify_jwt)):
    """
    Admin-only: Drops ALL old v1/v2 tables and ALL v3 data tables,
    then recreates fresh v3 schema. Preserves app_users (logins).
    This is the correct way to clear all cached queries, files, chat history.
    """
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not connected")

    dropped   = []
    recreated = []
    errors    = []

    # ── Step 1: Drop old views ────────────────────────────────────────────────
    for view in OLD_VIEWS:
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    f"IF OBJECT_ID('{view}','V') IS NOT NULL DROP VIEW {view}"
                ))
            dropped.append(f"VIEW {view}")
        except Exception as e:
            errors.append(f"DROP VIEW {view}: {e}")

    # ── Step 2: Drop all data tables (FK order, skip app_users) ───────────────
    for tbl in OLD_TABLES:
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    f"IF OBJECT_ID('{tbl}','U') IS NOT NULL DROP TABLE {tbl}"
                ))
            dropped.append(f"TABLE {tbl}")
        except Exception as e:
            errors.append(f"DROP TABLE {tbl}: {e}")

    # ── Step 3: Recreate all v3 tables + views ────────────────────────────────
    try:
        db.ensure_all_tables(engine)
        recreated = V3_TABLES + V3_VIEWS
    except Exception as e:
        errors.append(f"ensure_all_tables: {e}")

    return {
        "status":    "done" if not errors else "done_with_errors",
        "dropped":   dropped,
        "recreated": recreated,
        "errors":    errors,
        "message":   (
            "✅ All old data cleared. Fresh v3 schema is ready. "
            "app_users (login accounts) were NOT deleted."
        ),
    }


@app.post("/admin/clear-cache")
def admin_clear_cache(user: dict = Depends(verify_jwt)):
    """
    Admin-only: Truncates only query_cache and the file_analysis rows.
    Does NOT touch chat history, files, or user accounts.
    """
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not connected")

    try:
        with engine.begin() as conn:
            result = conn.execute(text("DELETE FROM dbo.query_cache"))
        return {
            "status":  "cleared",
            "deleted": result.rowcount,
            "message": f"✅ Deleted {result.rowcount} cache entries (SQL + file analysis).",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/clear-history")
def admin_clear_history(user: dict = Depends(verify_jwt)):
    """
    Admin-only: Clears ALL chat history for ALL users.
    Does NOT touch cache, files, or user accounts.
    """
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not connected")

    try:
        with engine.begin() as conn:
            result = conn.execute(text("DELETE FROM dbo.chat_log"))
        return {
            "status":  "cleared",
            "deleted": result.rowcount,
            "message": f"✅ Deleted {result.rowcount} chat history rows.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# VOICE ROUTES
# ─────────────────────────────────────────────────────────────────────────────

# ── POST /voice/transcribe ───────────────────────────────────────────────────
@app.post("/voice/transcribe")
@limiter.limit("10/minute")
async def transcribe_voice(
    request: Request,
    file: UploadFile = File(...),
    use_ollama:   bool = False,
    ollama_model: str  = "llama3",
    ttl_hours:    int  = 24,
    user: dict = Depends(verify_jwt),
):
    """
    Transcribe audio (webm/wav) with Whisper + grammar-fix pipeline.
    Results are cached by audio SHA-256 hash and saved to transcript history.

    Query params:
        use_ollama   – enable Ollama LLM refinement (default: false)
        ollama_model – which Ollama model to use   (default: llama3)
        ttl_hours    – audio cache TTL in hours     (default: 24)
    """
    from voice import transcribe_audio
    try:
        audio_bytes = await file.read()
        engine = get_auth_engine()
        result = transcribe_audio(
            audio_bytes,
            use_ollama=use_ollama,
            ollama_model=ollama_model,
            engine=engine,
            user_email=user.get("sub") or user.get("email"),
            user_id=user.get("user_id"),
            ttl_hours=ttl_hours,
        )
        VOICE_REQUESTS.inc()
        VOICE_LATENCY.observe(result.get("latency_ms", 0) / 1000.0)
        # Inject tracing ID into result for client
        result["trace_id"] = getattr(request.state, "request_id", None)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class VoiceLogRequest(BaseModel):
    raw_text: str
    clean_text: str
    latency_ms: float = 0.0
    language: str = "en-US"
    lang_prob: float = 1.0

@app.post("/voice/log")
def log_voice_transcript(body: VoiceLogRequest, user: dict = Depends(verify_jwt)):
    """Log a client-side Web Speech API transcript to the database."""
    engine = get_auth_engine()
    if engine:
        db.save_voice_entry(
            engine,
            user_id=user.get("user_id"),
            user_email=user.get("sub") or user.get("email"),
            raw_text=body.raw_text,
            clean_text=body.clean_text,
            latency_ms=body.latency_ms,
            language=body.language,
            lang_prob=body.lang_prob
        )
    return {"status": "logged"}


# ── WS /voice/stream ─────────────────────────────────────────────────────────
@app.websocket("/voice/stream")
async def websocket_voice_stream(websocket: WebSocket, token: str):
    """
    Accepts audio chunks via WebSocket and transcribes when connection closes.
    This reduces perceived latency by uploading chunks while user is speaking.
    """
    await websocket.accept()
    # Simple token verification for WebSocket (can't easily use headers)
    try:
        user = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    from voice import transcribe_audio
    engine = get_auth_engine()
    audio_buffer = bytearray()
    
    try:
        while True:
            chunk = await websocket.receive_bytes()
            audio_buffer.extend(chunk)
    except WebSocketDisconnect:
        if len(audio_buffer) > 0:
            try:
                result = transcribe_audio(
                    bytes(audio_buffer),
                    use_ollama=False,
                    engine=engine,
                    user_email=user.get("sub") or user.get("email"),
                    user_id=user.get("user_id"),
                )
                # Send result before finally closing
                await websocket.send_json(result)
            except Exception as e:
                print(f"[voice] WS error: {e}")



# ── GET /voice/models ────────────────────────────────────────────────────────
@app.get("/voice/models")
def list_voice_models(_: dict = Depends(verify_jwt)):
    """Return all available Whisper models and the currently active one."""
    from voice import AVAILABLE_MODELS, get_active_model_name
    return {
        "active_model": get_active_model_name(),
        "models": [
            {"name": name, **info}
            for name, info in AVAILABLE_MODELS.items()
        ],
    }


# ── POST /voice/model ────────────────────────────────────────────────────────
@app.post("/voice/model")
def switch_voice_model(body: dict, user: dict = Depends(verify_jwt)):
    """
    Hot-swap the active Whisper model at runtime.
    Admin only.
    """
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    model_name = body.get("model_name", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="model_name is required.")
    try:
        from voice import switch_model
        switch_model(model_name)
        return {"message": f"Whisper model switched to '{model_name}'."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /voice/transcripts ───────────────────────────────────────────────────
@app.get("/voice/transcripts")
def get_voice_transcripts(
    page:      int = 1,
    page_size: int = 20,
    user: dict = Depends(verify_jwt),
):
    """Return paginated transcript history for the logged-in user."""
    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not connected.")
    # Assuming page/page_size -> limit (db.get_voice_history doesn't use pagination natively right now)
    return db.get_voice_history(engine, user_email=user["email"], limit=page * page_size)


# ── DELETE /voice/transcripts/{id} ───────────────────────────────────────────
@app.delete("/voice/transcripts/{transcript_id}")
def remove_voice_transcript(
    transcript_id: int,
    user: dict = Depends(verify_jwt),
):
    """Delete a specific transcript (scoped to the requesting user)."""
    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not connected.")
    db.delete_voice_entry(engine, transcript_id, user_email=user["email"])
    return {"message": "Transcript deleted."}


# ── GET /voice/cache ─────────────────────────────────────────────────────────
@app.get("/voice/cache")
def get_voice_cache_list(user: dict = Depends(verify_jwt)):
    """List all voice cache entries. Admin only."""
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not connected.")
    entries = db.list_voice_cache(engine)
    return {"entries": entries, "count": len(entries)}


# ── DELETE /voice/cache/{id} ─────────────────────────────────────────────────
@app.delete("/voice/cache/{entry_id}")
def evict_voice_cache_entry(
    entry_id: int,
    user: dict = Depends(verify_jwt),
):
    """Evict a single voice cache entry (removes DB row + audio file). Admin only."""
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not connected.")
    db.delete_voice_entry(engine, entry_id, user_email=user["email"])
    return {"message": f"Cache entry {entry_id} evicted."}


# ── DELETE /voice/cache ──────────────────────────────────────────────────────
@app.delete("/voice/cache")
def flush_all_voice_cache(user: dict = Depends(verify_jwt)):
    """Flush the entire voice cache (all DB rows + audio files). Admin only."""
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    engine = get_auth_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Auth DB not connected.")
    db.flush_voice_cache(engine)
    return {"message": "Voice cache flushed."}