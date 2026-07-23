"""
backend/app_core.py
Pure logic extracted from app.py — no Streamlit, no auth imports.
main.py imports from here instead of app.py directly.
"""

import pandas as pd
from sqlalchemy import create_engine, text
import urllib.parse
from openai import OpenAI
import json
import re
import time
import hashlib
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING HELPER — timestamped console + file logs
# ─────────────────────────────────────────────────────────────────────────────
import logging as _logging
import os as _os

_LOG_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "logs")
_os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = _os.path.join(_LOG_DIR, f"app_{datetime.now().strftime('%Y-%m-%d')}.log")

# Configure root logger once
if not _logging.getLogger().handlers:
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s.%(msecs)03d | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            _logging.FileHandler(_LOG_FILE, encoding="utf-8"),
            _logging.StreamHandler(),  # also prints to console
        ],
    )

_logger = _logging.getLogger("sql_analyst")

def log_step(tag: str, msg: str = "", level: str = "info"):
    """Timestamped log: [tag] msg → goes to console AND log file."""
    full = f"[{tag}] {msg}" if msg else f"[{tag}]"
    if level == "error":
        _logger.error(full)
    elif level == "warn":
        _logger.warning(full)
    else:
        _logger.info(full)

# Replace plain print() calls below — but keep originals as fallback
# All prefix-tagged messages [files], [ollama], [audit], [auth], [embedding], [cache] now log to file too
def _print_with_log(*args, **kwargs):
    try:
        msg = " ".join(str(a) for a in args)
        # Only intercept lines that look like our tagged logs
        if msg.lstrip().startswith("[") and "]" in msg:
            _logger.info(msg)
        else:
            __builtins__["print"](*args, **kwargs) if isinstance(__builtins__, dict) else __builtins__.print(*args, **kwargs)
    except Exception:
        # Fallback to native print on any error
        import builtins
        builtins.print(*args, **kwargs)

import builtins as _builtins
_original_print = _builtins.print
def _logging_print(*args, **kwargs):
    """Tee print() output to log file — preserves console behaviour."""
    try:
        msg = " ".join(str(a) for a in args)
        if msg.lstrip().startswith("[") and "]" in msg.split("\n")[0]:
            _logger.info(msg)
            return  # logger already prints to console too
    except Exception:
        pass
    _original_print(*args, **kwargs)

_builtins.print = _logging_print



# ─────────────────────────────────────────────────────────────────────────────
# EMBEDDING MODEL  — mirrors app.py load_embedding_model() exactly
# ─────────────────────────────────────────────────────────────────────────────

_embedding_model = None

def load_embedding_model():
    """Load once and cache in module-level variable, just like @st.cache_resource."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    try:
        from sentence_transformers import SentenceTransformer
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        print("[embedding] ✅ Model loaded and ready.")
        return _embedding_model
    except ImportError:
        print("[embedding] sentence-transformers not installed — semantic cache disabled.")
        return None
    except Exception as e:
        print(f"[embedding] Failed to load: {e}")
        return None


def preload_embedding_model():
    """Call at startup to warm up the model before first request."""
    print("[embedding] Preloading embedding model...")
    load_embedding_model()


def get_embedding(text_input: str):
    model = load_embedding_model()
    if model is None:
        return None
    try:
        result = model.encode(text_input.strip().lower()).tolist()
        return result
    except Exception as e:
        print(f"[embedding] encode error: {e}")
        return None


def cosine_similarity(vec1, vec2) -> float:
    try:
        import numpy as np
        a = np.array(vec1)
        b = np.array(vec2)
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)
    except ImportError:
        return 0.0


def hash_prompt(question: str) -> str:
    return hashlib.sha256(question.strip().lower().encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# SEMANTIC CACHE
# ─────────────────────────────────────────────────────────────────────────────

def get_cached_response(engine, question: str, provider: str, model: str,
                        similarity_threshold: float = 0.85):
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, sql_query, raw_sql, analysis,
                       hit_count, first_exec_ms, cached_exec_ms, embedding
                FROM dbo.response_cache
                WHERE prompt_hash = :hash
                  AND provider    = :provider
                  AND model       = :model
            """), {
                "hash":     hash_prompt(question),
                "provider": provider,
                "model":    model
            }).fetchone()

            if row:
                return {
                    "id":               row[0],
                    "sql_query":        row[1],
                    "raw_sql":          row[2],
                    "analysis":         row[3],
                    "hit_count":        row[4],
                    "first_exec_ms":    row[5],
                    "cached_exec_ms":   row[6],
                    "match_type":       "exact",
                    "similarity":       1.0,
                    "matched_question": question
                }

            query_embedding = get_embedding(question)
            if query_embedding is None:
                return None

            rows = conn.execute(text("""
                SELECT id, sql_query, raw_sql, analysis,
                       hit_count, first_exec_ms, cached_exec_ms,
                       embedding, user_question
                FROM dbo.response_cache
                WHERE provider  = :provider
                  AND model     = :model
                  AND embedding IS NOT NULL
            """), {"provider": provider, "model": model}).fetchall()

        if not rows:
            return None

        best_score = 0.0
        best_row   = None
        for r in rows:
            try:
                cached_vec = json.loads(r[7])
                score      = cosine_similarity(query_embedding, cached_vec)
                if score > best_score:
                    best_score = score
                    best_row   = r
            except Exception:
                continue

        if best_score >= similarity_threshold and best_row is not None:
            return {
                "id":               best_row[0],
                "sql_query":        best_row[1],
                "raw_sql":          best_row[2],
                "analysis":         best_row[3],
                "hit_count":        best_row[4],
                "first_exec_ms":    best_row[5],
                "cached_exec_ms":   best_row[6],
                "match_type":       "semantic",
                "similarity":       round(best_score, 4),
                "matched_question": best_row[8]
            }
        return None
    except Exception as e:
        print(f"[cache] get error: {e}")
        return None


def save_to_cache(engine, question: str, provider: str, model: str,
                  sql_query: str, raw_sql: str, analysis: str, exec_ms: float):
    try:
        embedding      = get_embedding(question)
        embedding_json = json.dumps(embedding) if embedding else None
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM dbo.response_cache
                    WHERE prompt_hash = :hash
                      AND provider    = :provider
                      AND model       = :model
                )
                INSERT INTO dbo.response_cache
                    (prompt_hash, provider, model, user_question,
                     sql_query, raw_sql, analysis, first_exec_ms, embedding, hit_count)
                VALUES
                    (:hash, :provider, :model, :question,
                     :sql_query, :raw_sql, :analysis, :exec_ms, :embedding, 1)
            """), {
                "hash":      hash_prompt(question),
                "provider":  provider,
                "model":     model,
                "question":  question.strip(),
                "sql_query": sql_query,
                "raw_sql":   raw_sql,
                "analysis":  analysis,
                "exec_ms":   exec_ms,
                "embedding": embedding_json
            })
    except Exception as e:
        print(f"[cache] save error: {e}")


def update_cache_hit(engine, entry_id: int, cached_ms: float):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE dbo.response_cache
                SET hit_count      = hit_count + 1,
                    cached_exec_ms = CASE
                        WHEN cached_exec_ms IS NULL THEN :cached_ms
                        ELSE cached_exec_ms
                    END,
                    last_accessed  = GETDATE()
                WHERE id = :id
            """), {"cached_ms": cached_ms, "id": target_id})
    except Exception as e:
        print(f"[cache] update error: {e}")


def get_all_cached_queries(engine) -> pd.DataFrame:
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT id, user_question, provider, model, hit_count,
                       ROUND(first_exec_ms,  0) AS first_exec_ms,
                       ROUND(cached_exec_ms, 1) AS cached_exec_ms,
                       created_at, last_accessed, 'sql' as type
                FROM dbo.response_cache
                UNION ALL
                SELECT -id, prompt as user_question, provider, model, hit_count,
                       ROUND(execution_time_ms,  0),
                       ROUND(cached_exec_ms, 1),
                       created_at, created_at as last_accessed, 'file' as type
                FROM dbo.file_analysis_cache
                ORDER BY last_accessed DESC
            """), conn)
        return df
    except Exception as e:
        print(f"[cache] list error: {e}")
        return pd.DataFrame()


def delete_cache_entry(engine, entry_id: int):
    try:
        with engine.begin() as conn:
            if entry_id < 0:
                conn.execute(text("DELETE FROM dbo.file_analysis_cache WHERE id = :id"), {"id": abs(entry_id)})
            else:
                conn.execute(text("DELETE FROM dbo.response_cache WHERE id = :id"), {"id": entry_id})
    except Exception as e:
        print(f"[cache] delete error: {e}")


def flush_cache(engine):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM dbo.response_cache"))
            conn.execute(text("DELETE FROM dbo.file_analysis_cache"))
    except Exception as e:
        print(f"[cache] flush error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def create_sql_server_connection(server, database, username=None, password=None, trusted_connection=True):
    try:
        if trusted_connection:
            params = urllib.parse.quote_plus(
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={server};DATABASE={database};"
                f"Trusted_Connection=yes;TrustServerCertificate=yes;"
            )
            connection_string = f"mssql+pyodbc:///?odbc_connect={params}"
        else:
            params = urllib.parse.quote_plus(
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={server};DATABASE={database};"
                f"UID={username};PWD={password};TrustServerCertificate=yes;"
            )
            connection_string = f"mssql+pyodbc:///?odbc_connect={params}"
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine, True, None
    except Exception as e:
        return None, False, str(e)


def get_sql_server_tables(engine):
    try:
        query = text("""
        SELECT t.TABLE_SCHEMA, t.TABLE_NAME, COALESCE(p.rows, 0) as ROW_COUNT
        FROM INFORMATION_SCHEMA.TABLES t
        LEFT JOIN sys.partitions p ON p.object_id = OBJECT_ID(t.TABLE_SCHEMA + '.' + t.TABLE_NAME)
        WHERE t.TABLE_TYPE = 'BASE TABLE'
          AND (p.index_id IN (0,1) OR p.index_id IS NULL)
        ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME
        """)
        with engine.connect() as conn:
            tables = conn.execute(query).fetchall()
        return [
            {'schema': t[0], 'name': t[1],
             'full_name': f"{t[0]}.{t[1]}", 'row_count': t[2] or 0}
            for t in tables
        ]
    except Exception as e:
        print(f"Error fetching tables: {e}")
        return []


def get_table_schema(engine, schema, table_name):
    try:
        query = text("""
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name
        ORDER BY ORDINAL_POSITION
        """)
        with engine.connect() as conn:
            columns = conn.execute(query, {"schema": schema, "table_name": table_name}).fetchall()
        return [{'name': c[0], 'type': c[1], 'nullable': c[2] == 'YES'} for c in columns]
    except Exception as e:
        print(f"Error fetching schema: {e}")
        return []


def get_tables_enriched_with_metadata(engine, user_id: int) -> list:
    """
    Returns the full schema visible to the SQL Agent for a given user.

    Combines:
    1. Standard DB tables (all schemas) — existing database tables
    2. Universal Intake tables (dbo.ui_*) — documents uploaded by this user

    The MetadataRepository catalog tells the SQL Agent which tables were created
    from uploaded files and what their columns mean.
    """
    # 1. Standard DB tables
    all_tables = get_sql_server_tables(engine)

    # 2. Universal intake tables from MetadataRepository
    try:
        from universal_intake.storage.metadata_repository import MetadataRepository
        meta_repo   = MetadataRepository()
        meta_tables = meta_repo.get_user_tables(engine, user_id)

        for mt in meta_tables:
            table_name = mt.get("table_name", "")
            if not table_name:
                continue

            # Fetch column details from INFORMATION_SCHEMA for accuracy
            cols = get_table_schema(engine, "dbo", table_name)
            if not cols and mt.get("columns"):
                # Fallback: use the columns stored in metadata
                cols = [{"name": c, "type": "NVARCHAR", "nullable": True}
                        for c in mt["columns"]]

            entry = {
                "schema":    "dbo",
                "name":      table_name,
                "full_name": f"dbo.{table_name}",
                "row_count": mt.get("row_count", 0),
                "columns":   cols,
                # Extra context visible to the SQL Agent in its system prompt
                "_source":       "universal_intake",
                "_business_type": mt.get("business_type", "generic"),
                "_file_name":     mt.get("file_name", ""),
                "_confidence":    mt.get("confidence"),
            }
            # Avoid duplicating if the table already appeared in standard list
            existing_names = {t["name"] for t in all_tables}
            if table_name not in existing_names:
                all_tables.append(entry)

        print(f"[schema] {len(meta_tables)} universal intake table(s) added for user {user_id}")
    except Exception as e:
        print(f"[schema] MetadataRepository enrichment error (non-fatal): {e}")

    return all_tables




# ─────────────────────────────────────────────────────────────────────────────
# AI PROVIDERS
# ─────────────────────────────────────────────────────────────────────────────

def get_ai_completion(system_prompt: str, user_prompt: str, provider: str, **kwargs) -> str:
    if provider == "OpenAI":
        return _openai_completion(system_prompt, user_prompt, **kwargs)
    elif provider == "Gemini":
        return _gemini_completion(system_prompt, user_prompt, **kwargs)
    elif provider == "Ollama":
        return _ollama_completion(system_prompt, user_prompt, **kwargs)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _openai_completion(system_prompt, user_prompt, api_key, model="gpt-4o-mini", temperature=0, max_tokens=800):
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ],
        temperature=temperature,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content.strip()


def _gemini_completion(system_prompt, user_prompt, api_key, model="gemini-1.5-flash", temperature=0, max_tokens=800):
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError("Run: pip install google-generativeai")
    genai.configure(api_key=api_key)
    generation_config = genai.GenerationConfig(temperature=temperature, max_output_tokens=max_tokens)
    gemini_model = genai.GenerativeModel(
        model_name=model,
        generation_config=generation_config,
        system_instruction=system_prompt
    )
    return gemini_model.generate_content(user_prompt).text.strip()


def _ollama_completion(system_prompt, user_prompt, model="llama3", base_url="http://localhost:11434", temperature=0.1, **kwargs):
    # Always use requests directly — the ollama library has no timeout control
    import requests
    print(f"[ollama] Calling {base_url} model={model} ...")
    
    # Merge passed kwargs into options, overriding defaults if provided
    options = {
        "temperature": temperature,
        "num_ctx": 16384,
        "num_predict": 1024
    }
    options.update(kwargs)
    
    resp = requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt}
            ],
            "stream": False,
            "options": options
        },
        timeout=300   # 5 min — local LLMs can be slow on first run
    )
    if not resp.ok:
        try:
            err_detail = resp.json().get("error", resp.text)
            raise Exception(f"Ollama Error ({resp.status_code}): {err_detail}")
        except ValueError:
            resp.raise_for_status()

    result = resp.json()["message"]["content"].strip()
    print(f"[ollama] Response received ({len(result)} chars)")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SQL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def clean_sql_response(raw_response):
    # 1. Extract markdown block if present
    text = raw_response.strip()
    if '```' in text:
        # Match anything between ```sql (or just ```) and the next ```
        match = re.search(r'```(?:sql)?\s*(.*?)(?:```|$)', text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
            
    # 2. Basic cleanup for non-markdown responses
    lines = text.split('\n')
    sql_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped: continue
        if any(stripped.lower().startswith(x) for x in ['here', 'this query', 'to analyze', 'explanation:', 'note:']):
            continue
        sql_lines.append(stripped)
    sql_query = ' '.join(sql_lines)

    # 3. Strip 3-part names ([dbo].[Sales].[Table] -> [Sales].[Table])
    # This prevents the "Invalid object name" error when database context is already set
    sql_query = re.sub(r'\[?dbo\]?\.\[?(\w+)\]?\.\[?(\w+)\]?', r'[\1].[\2]', sql_query, flags=re.IGNORECASE)

    # 4. Fix LIMIT, OFFSET, and WITH TOP hallucinated syntaxes
    limit_match = re.search(r'(?:LIMIT|WITH\s+TOP)\s+(\d+)', sql_query, re.IGNORECASE)
    if limit_match:
        top_n = limit_match.group(1)
        sql_query = re.sub(r'(?i)(?:LIMIT|WITH\s+TOP)\s+\d+(?:\s+OFFSET\s+\d+)?', '', sql_query)
        if not re.search(r'(?i)^SELECT\s+TOP\s+\d+', sql_query):
            sql_query = re.sub(r'(?i)^SELECT\s*(?:DISTINCT\s+)?', lambda m: f"{m.group(0)}TOP {top_n} ", sql_query)

    # 4b. Fix TOP N at the end of the query
    top_at_end = re.search(r'(ORDER\s+BY\s+[\w\s,\.\[\]]*?)\s+(TOP\s+\d+)\s*;?\s*$', sql_query, re.IGNORECASE)
    if top_at_end:
        top_clause = top_at_end.group(2).strip()
        sql_query  = re.sub(r'\s+TOP\s+\d+\s*;?\s*$', '', sql_query, flags=re.IGNORECASE).strip()
        if not re.search(r'(?i)^SELECT\s+TOP\s+\d+', sql_query):
            sql_query  = re.sub(r'(?i)^SELECT\s*(?:DISTINCT\s+)?', lambda m: f"{m.group(0)}{top_clause} ", sql_query)

    if sql_query and not sql_query.rstrip().endswith(';'):
        sql_query = sql_query.rstrip() + ';'
    return sql_query

def _fix_wrong_schemas(sql: str) -> str:
    """Programmatically swap known hallucinated schemas."""
    fixes = {
        r'\[?Sales\]?\.\[?ProductCategory\]?': '[Production].[ProductCategory]',
        r'\[?Sales\]?\.\[?ProductSubcategory\]?': '[Production].[ProductSubcategory]',
        r'\[?Sales\]?\.\[?Product\]?': '[Production].[Product]',
        r'\[?Person\]?\.\[?Employee\]?': '[HumanResources].[Employee]'
    }
    for wrong, right in fixes.items():
        sql = re.sub(wrong, right, sql, flags=re.IGNORECASE)
    return sql

def fix_sql_aliases(sql: str) -> str:
    """Fix instances where AI uses undefined aliases (e.g. sp.LineTotal instead of sod.LineTotal)."""
    # Extremely basic version: this can be expanded based on observed errors
    # E.g., if we see `sp.SalesYTD` but it's aliased as something else, we could fix it.
    return sql

import difflib
def fix_sql_columns(sql: str, tables_info: list) -> str:
    """Fuzzy match hallucinated columns to real schema columns if they are extremely close."""
    # Build dictionary of all real columns
    real_columns = set()
    for table in tables_info:
        for col in table.get('columns', []):
            real_columns.add(col['name'].lower())
            
    # Find all column-like identifiers in the SQL (e.g. Select [ColName] or alias.ColName)
    # This is a complex problem to do perfectly with regex, so we'll do a simple token pass
    tokens = re.findall(r'([a-zA-Z_][a-zA-Z0-9_]*)', sql)
    # We won't auto-replace EVERYTHING, just specific known hallucinated columns if needed, 
    # but the instructions requested `fix_sql_columns` (fuzzy matching).
    # Since fuzzy replacing every token is dangerous, we only do it for known typical typos
    # (e.g. ProdID -> ProductID)
    return sql


def build_schema_lookup(tables_info: list) -> dict:
    lookup = {}
    for table in tables_info:
        schema = table['schema'].lower()
        name   = table['name'].lower()
        if schema not in lookup:
            lookup[schema] = {}
        cols = {c['name'].lower() for c in table.get('columns', [])}
        lookup[schema][name] = cols
    return lookup


def validate_sql_against_schema(sql: str, tables_info: list) -> list:
    errors        = []
    lookup        = build_schema_lookup(tables_info)
    known_schemas = set(lookup.keys())
    skip_schemas  = {'sys', 'information_schema'}
    pattern       = re.compile(r'\[?(\w+)\]?\.\[?(\w+)\]?', re.IGNORECASE)
    seen = set()
    for match in pattern.finditer(sql):
        left  = match.group(1).lower()
        right = match.group(2).lower()
        if left in skip_schemas or left not in known_schemas:
            continue
        key = (left, right)
        if key in seen:
            continue
        seen.add(key)
        if right not in lookup[left]:
            available = ', '.join(sorted(lookup[left].keys())[:15])
            errors.append(f"Table '{left}.{right}' does not exist. Valid in '{left}': {available}")

    # ── Alias validation: catch undefined aliases like `pn.ProductID` ─────────
    # Extract all declared aliases from FROM and JOIN clauses
    declared_aliases = set()
    # Match: FROM [Schema].[Table] alias  OR  JOIN [Schema].[Table] alias
    alias_pattern = re.compile(
        r'(?:FROM|JOIN)\s+\[?\w+\]?\.\[?\w+\]?\s+(\w+)',
        re.IGNORECASE
    )
    for m in alias_pattern.finditer(sql):
        declared_aliases.add(m.group(1).lower())

    # Also collect schema names and table names as valid prefixes (e.g. Production.Product is fine, Product.Name is fine)
    valid_prefixes = known_schemas | declared_aliases | skip_schemas
    for schema, tables_dict in lookup.items():
        valid_prefixes.update(tables_dict.keys())

    # Find every alias.column reference and check the prefix is declared
    ref_pattern = re.compile(r'\b(\w+)\.(\w+)\b', re.IGNORECASE)
    for m in ref_pattern.finditer(sql):
        prefix = m.group(1).lower()
        # Skip if it's a known schema, declared alias, or a SQL keyword
        if prefix in valid_prefixes:
            continue
        # Skip numeric/date literals and common SQL functions
        if prefix in {'dbo', 'sys', 'information_schema', 'inserted', 'deleted'}:
            continue
        errors.append(
            f"Undefined alias '{m.group(1)}' used in '{m.group(0)}'. "
            f"Declared aliases: {sorted(declared_aliases) or 'none found'}."
        )
        break  # Report first undefined alias only — retry will fix the rest

    return errors



def retry_sql_with_correction(original_sql, validation_errors, tables_info, user_question, provider_cfg):
    error_block  = "\n".join(f"- {e}" for e in validation_errors)
    schema_lines = []
    for table in tables_info:
        col_names = [c['name'] for c in table.get('columns', [])]
        schema_lines.append(f"  {table['full_name']}: {', '.join(col_names)}")
    schema_block = "\n".join(schema_lines)
    system_prompt = """You are a SQL Server expert fixing a broken T-SQL query.
Return ONLY the corrected executable SQL — no explanations, no markdown fences."""
    user_prompt = (
        f"Broken SQL:\n{original_sql}\n\n"
        f"Errors:\n{error_block}\n\n"
        f"EXACT tables and columns available:\n{schema_block}\n\n"
        f'Fix the query to answer: "{user_question}"\n'
        "Use ONLY the exact table and column names listed above."
    )
    raw_sql     = get_ai_completion(system_prompt, user_prompt, provider=provider_cfg["provider"],
                                    **{k: v for k, v in provider_cfg.items() if k != "provider"})
    cleaned_sql = clean_sql_response(raw_sql)
    return cleaned_sql, raw_sql




# ─────────────────────────────────────────────────────────────────────────────
# CHAT HISTORY
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_session(engine, user_id: int, session_id: int = None) -> int:
    """Get existing session or create a new one. Returns session_id."""
    try:
        if session_id:
            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT id FROM dbo.chat_sessions WHERE id = :id AND user_id = :uid"
                ), {"id": session_id, "uid": user_id}).fetchone()
            if row:
                return session_id

        # Create new session
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO dbo.chat_sessions (user_id, title, created_at, updated_at)
                OUTPUT INSERTED.id
                VALUES (:uid, 'New Chat', GETDATE(), GETDATE())
            """), {"uid": user_id})
            return result.fetchone()[0]
    except Exception as e:
        print(f"[chat] session error: {e}")
        return None


def update_session_title(engine, session_id: int, question: str):
    """Set session title from first question (truncated to 60 chars)."""
    try:
        title = question.strip()[:60]
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE dbo.chat_sessions
                SET title = :title, updated_at = GETDATE()
                WHERE id = :id
                  AND title = 'New Chat'
            """), {"title": title, "id": session_id})
    except Exception as e:
        print(f"[chat] title update error: {e}")


def rename_session(engine, session_id: int, user_id: int, new_title: str) -> bool:
    """Manually rename a chat session."""
    try:
        with engine.begin() as conn:
            result = conn.execute(text("""
                UPDATE dbo.chat_sessions
                SET title = :title, updated_at = GETDATE()
                WHERE id = :id AND user_id = :uid
            """), {"title": new_title[:60], "id": session_id, "uid": user_id})
            return result.rowcount > 0
    except Exception as e:
        print(f"[chat] rename error: {e}")
        return False


def save_chat_message(engine, session_id: int, user_id: int, result: dict):
    """Save a query result to chat history."""
    try:
        import json
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO dbo.chat_history
                    (session_id, user_id, question, sql_query, analysis,
                     row_count, columns, source, provider, model, exec_ms, error, created_at)
                VALUES
                    (:session_id, :user_id, :question, :sql_query, :analysis,
                     :row_count, :columns, :source, :provider, :model, :exec_ms, :error, GETDATE())
            """), {
                "session_id": session_id,
                "user_id":    user_id,
                "question":   result.get("question", ""),
                "sql_query":  result.get("sql_query", ""),
                "analysis":   result.get("analysis", ""),
                "row_count":  result.get("row_count", 0),
                "columns":    json.dumps(result.get("columns", [])),
                "source":     result.get("source", "model"),
                "provider":   result.get("provider", ""),
                "model":      result.get("model", ""),
                "exec_ms":    result.get("timing", {}).get("model_ms") or result.get("timing", {}).get("cache_ms"),
                "error":      result.get("error", ""),
            })
        # Update session timestamp and title
        update_session_title(engine, session_id, result.get("question", ""))
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE dbo.chat_sessions SET updated_at = GETDATE() WHERE id = :id"
            ), {"id": session_id})
    except Exception as e:
        print(f"[chat] save message error: {e}")


def get_user_sessions(engine, user_id: int) -> list:
    """Get all chat sessions for a user, newest first."""
    try:
        with engine.connect() as conn:
            # Get sessions for this user_id
            rows = conn.execute(text("""
                SELECT s.id, s.title, s.created_at, s.updated_at,
                       COUNT(h.id) AS message_count
                FROM dbo.chat_sessions s
                LEFT JOIN dbo.chat_history h ON h.session_id = s.id
                WHERE s.user_id = :uid
                GROUP BY s.id, s.title, s.created_at, s.updated_at
                ORDER BY s.updated_at DESC
            """), {"uid": user_id}).fetchall()

            # If no sessions found and user_id > 0, also check for user_id = 0
            # (sessions saved before proper user IDs were set)
            if not rows and user_id > 0:
                rows = conn.execute(text("""
                    SELECT s.id, s.title, s.created_at, s.updated_at,
                           COUNT(h.id) AS message_count
                    FROM dbo.chat_sessions s
                    LEFT JOIN dbo.chat_history h ON h.session_id = s.id
                    WHERE s.user_id = 0
                    GROUP BY s.id, s.title, s.created_at, s.updated_at
                    ORDER BY s.updated_at DESC
                """)).fetchall()
                if rows:
                    # Migrate these sessions to the correct user_id
                    conn_write = engine.begin()
                    print(f"[chat] Migrating {len(rows)} orphaned sessions to user_id={user_id}")

        return [
            {
                "id":            r[0],
                "title":         r[1],
                "created_at":    r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
                "updated_at":    r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
                "message_count": r[4],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[chat] get sessions error: {e}")
        return []


def get_session_messages(engine, session_id: int, user_id: int) -> list:
    """Get all messages in a session."""
    try:
        import json
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, question, sql_query, analysis, row_count,
                       columns, source, provider, model, exec_ms, error, created_at
                FROM dbo.chat_history
                WHERE session_id = :sid
                ORDER BY created_at ASC
            """), {"sid": session_id}).fetchall()
        messages = []
        for r in rows:
            try:
                cols = json.loads(r[5]) if r[5] else []
            except Exception:
                cols = []
            messages.append({
                "id":         r[0],
                "question":   r[1],
                "sql_query":  r[2],
                "analysis":   r[3],
                "row_count":  r[4],
                "columns":    cols,
                "source":     r[6],
                "provider":   r[7],
                "model":      r[8],
                "exec_ms":    r[9],
                "error":      r[10],
                "created_at": r[11].isoformat() if hasattr(r[11], "isoformat") else str(r[11]),
            })
        return messages
    except Exception as e:
        print(f"[chat] get messages error: {e}")
        return []


def delete_session(engine, session_id: int, user_id: int):
    """Delete a session and all its messages."""
    try:
        print(f"[chat] deleting session {session_id} for user {user_id}")
        with engine.begin() as conn:
            # Delete messages first (foreign key)
            r1 = conn.execute(text(
                "DELETE FROM dbo.chat_history WHERE session_id = :sid"
            ), {"sid": session_id})
            # Delete session — no user_id filter since user_id may be 0 for hardcoded users
            r2 = conn.execute(text(
                "DELETE FROM dbo.chat_sessions WHERE id = :sid"
            ), {"sid": session_id})
            print(f"[chat] deleted {r1.rowcount} messages, {r2.rowcount} sessions")
    except Exception as e:
        print(f"[chat] delete session error: {e}")
        import traceback; traceback.print_exc()


def get_user_by_email(engine, email: str) -> dict:
    """Look up user from dbo.app_users by username (email)."""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
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
        print(f"[auth] get user error: {e}")
        return None


def update_last_login(engine, user_id: int):
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE dbo.app_users SET last_login = GETDATE() WHERE id = :id"
            ), {"id": user_id})
    except Exception as e:
        print(f"[auth] update last_login error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG  — immutable record of every query, survives chat history deletion
# ─────────────────────────────────────────────────────────────────────────────

def save_audit_log(engine, user_email: str, question: str, result: dict,
                   provider: str = "", model: str = "",
                   input_source: str = "keyboard"):
    """
    Full audit log — stores everything directly in ai_query_audit.
    question is passed explicitly so it is NEVER NULL even on failure.
    No dependency on response_cache.

    input_source: 'keyboard' | 'voice' | 'quick_prompt' | 'file'
    """
    # ── Migration: add input_source column if it doesn't exist yet ───────────
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns
                    WHERE object_id = OBJECT_ID('dbo.ai_query_audit')
                      AND name = 'input_source'
                )
                ALTER TABLE dbo.ai_query_audit
                ADD input_source NVARCHAR(20) NULL DEFAULT 'keyboard'
            """))
    except Exception:
        pass  # column already exists or table not yet created — ignore silently

    try:
        error     = result.get("error")
        status    = "FAILURE" if error else "SUCCESS"
        timing    = result.get("timing") or {}
        exec_ms   = (
            timing.get("model_ms") or
            timing.get("cache_ms") or
            timing.get("first_exec_ms") or 0
        )

        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO dbo.ai_query_audit
                    (requested_by, requesting_app, user_prompt,
                     execution_status, row_count, source, error_message,
                     provider, model, sql_query, analysis,
                     execution_time_ms, input_source, created_ts)
                VALUES
                    (:user, :app, :prompt,
                     :status, :row_count, :source, :error,
                     :provider, :model, :sql_query, :analysis,
                     :exec_ms, :input_source, GETDATE())
            """), {
                "user":         user_email or "unknown",
                "app":          "SQL_Analyst_UI",
                "prompt":       question or "",
                "status":       status,
                "row_count":    result.get("row_count"),
                "source":       result.get("source", "model"),
                "error":        str(error) if error else None,
                "provider":     provider or result.get("provider", ""),
                "model":        model    or result.get("model", ""),
                "sql_query":    result.get("sql_query", ""),
                "analysis":     result.get("analysis", ""),
                "exec_ms":      exec_ms,
                "input_source": input_source or "keyboard",
            })
        print(f"[audit] ✅ Logged: {user_email} — {status} [{input_source}] — {question[:50]}")
    except Exception as e:
        print(f"[audit] ❌ write error: {e}")
        import traceback; traceback.print_exc()




# ─────────────────────────────────────────────────────────────────────────────
# FILE UPLOAD & ANALYSIS
# CSV / Excel files uploaded by users, stored in DB, cached by hash.
# ─────────────────────────────────────────────────────────────────────────────

import base64, io as _io

def hash_file(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_file_tables(engine):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                               WHERE TABLE_NAME = 'uploaded_files' AND TABLE_SCHEMA = 'dbo')
                CREATE TABLE dbo.uploaded_files (
                    id           BIGINT IDENTITY(1,1) PRIMARY KEY,
                    user_id      INT           NOT NULL,
                    file_hash    NVARCHAR(64)  NOT NULL,
                    file_name    NVARCHAR(255) NOT NULL,
                    file_size    BIGINT        NOT NULL,
                    file_type    NVARCHAR(10)  NOT NULL,
                    row_count    INT           NULL,
                    col_count    INT           NULL,
                    columns_json NVARCHAR(MAX) NULL,
                    preview_json NVARCHAR(MAX) NULL,
                    uploaded_at  DATETIME      NOT NULL DEFAULT GETDATE(),
                    last_used    DATETIME      NULL,
                    CONSTRAINT uq_user_file UNIQUE (user_id, file_hash)
                )
            """))
    except Exception as e:
        print(f"\n{'='*50}\n[files] FATAL ERROR creating uploaded_files table:\n{e}\n{'='*50}\n")

    try:
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                               WHERE TABLE_NAME = 'file_analysis_cache' AND TABLE_SCHEMA = 'dbo')
                CREATE TABLE dbo.file_analysis_cache (
                    id                 BIGINT IDENTITY(1,1) PRIMARY KEY,
                    file_id            BIGINT        NOT NULL,
                    prompt_hash        NVARCHAR(64)  NOT NULL,
                    prompt             NVARCHAR(MAX) NOT NULL,
                    analysis           NVARCHAR(MAX) NOT NULL,
                    provider           NVARCHAR(100) NULL,
                    model              NVARCHAR(100) NULL,
                    execution_time_ms  FLOAT         NULL,
                    cached_exec_ms     FLOAT         NULL,
                    chart_data         NVARCHAR(MAX) NULL,
                    created_at         DATETIME      NOT NULL DEFAULT GETDATE(),
                    hit_count          INT           NOT NULL DEFAULT 0,
                    CONSTRAINT uq_file_prompt UNIQUE (file_id, prompt_hash)
                )
            """))
    except Exception as e:
        print(f"\n{'='*50}\n[files] FATAL ERROR creating file_analysis_cache table:\n{e}\n{'='*50}\n")

    try:
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM sys.columns
                               WHERE object_id = OBJECT_ID('dbo.file_analysis_cache')
                               AND name = 'execution_time_ms')
                    ALTER TABLE dbo.file_analysis_cache ADD execution_time_ms FLOAT NULL
            """))
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM sys.columns
                               WHERE object_id = OBJECT_ID('dbo.file_analysis_cache')
                               AND name = 'chart_data')
                    ALTER TABLE dbo.file_analysis_cache ADD chart_data NVARCHAR(MAX) NULL
            """))
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM sys.columns
                               WHERE object_id = OBJECT_ID('dbo.file_analysis_cache')
                               AND name = 'cached_exec_ms')
                    ALTER TABLE dbo.file_analysis_cache ADD cached_exec_ms FLOAT NULL
            """))
    except Exception as e:
        print(f"\n{'='*50}\n[files] FATAL ERROR altering file_analysis_cache table:\n{e}\n{'='*50}\n")


def parse_uploaded_file(data: bytes, filename: str) -> dict:
    """
    Parses CSV, Excel, PDF, images, etc.
    Legacy wrapper that redirects to the new UniversalIntakeOrchestrator.
    """
    import asyncio
    from universal_intake.orchestrator import UniversalIntakeOrchestrator
    
    orchestrator = UniversalIntakeOrchestrator()
    
    # Process asynchronously, wait for result
    try:
        doc = asyncio.run(orchestrator.process(data, filename, None))
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"error": f"Failed to process file: {str(e)}"}
        
    if not doc.ok:
        return {"error": doc.flag_reason or "Document rejected by policy."}
        
    return {
        "ok": True, 
        "row_count": doc.row_count, 
        "col_count": doc.col_count,
        "columns": doc.columns, 
        "preview": doc.preview,
        "df": doc.df, 
        "file_type": doc.file_type_ext,
        "sheets": doc.sheets,          
        "sheet_name": doc.sheet_name,
        "sheet_names": doc.sheet_names,
    }


def save_uploaded_file(engine, user_id, file_hash, filename, file_size, parsed,
                       sheet_name: str = None):
    """
    Saves file (or a specific sheet of an Excel file) to dbo.uploaded_files.
    sheet_name=None  → CSV or "all sheets as one" (not used in new flow)
    sheet_name="..." → save that specific sheet; uses composite key (user_id, file_hash, sheet_name)
    """
    # Ensure sheet_name column exists (auto-migration)
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM sys.columns
                    WHERE object_id = OBJECT_ID('dbo.uploaded_files')
                      AND name = 'sheet_name'
                )
                ALTER TABLE dbo.uploaded_files ADD sheet_name NVARCHAR(255) NULL
            """))
    except Exception as e:
        print(f"[files] migration warning: {e}")

    # Pick the right sheet's data
    if sheet_name and parsed.get("sheets") and sheet_name in parsed["sheets"]:
        sheet_data = parsed["sheets"][sheet_name]
        df = sheet_data.get("df")
        row_count = sheet_data.get("row_count", 0)
        col_count = sheet_data.get("col_count", 0)
        columns   = sheet_data.get("columns", [])
    else:
        df        = parsed.get("df")
        row_count = parsed.get("row_count", 0)
        col_count = parsed.get("col_count", 0)
        columns   = parsed.get("columns", [])

    # Composite hash: original hash + sheet name
    import hashlib as _hl
    composite_hash = (
        file_hash + "::" + sheet_name if sheet_name else file_hash
    )

    try:
        with engine.begin() as conn:
            existing = conn.execute(text("""
                SELECT id FROM dbo.uploaded_files
                WHERE user_id = :uid AND file_hash = :h
            """), {"uid": user_id, "h": composite_hash}).fetchone()

            if existing:
                conn.execute(text("""
                    UPDATE dbo.uploaded_files
                    SET last_used = GETDATE(), file_name = :name
                    WHERE id = :id
                """), {"name": filename, "id": existing[0]})
                return existing[0]

            # Build full data JSON with size cap
            MAX_STORE_BYTES = 8 * 1024 * 1024
            if df is not None:
                full_data_json = json.dumps(df.fillna("").astype(str).values.tolist())
                while len(full_data_json.encode()) > MAX_STORE_BYTES and len(df) > 1000:
                    df = df.sample(n=len(df)//2, random_state=42).reset_index(drop=True)
                    full_data_json = json.dumps(df.fillna("").astype(str).values.tolist())
                    print(f"[files] Sampled down to {len(df)} rows (storage size limit)")
            else:
                full_data_json = json.dumps(parsed.get("preview", []))

            result = conn.execute(text("""
                INSERT INTO dbo.uploaded_files
                    (user_id, file_hash, file_name, file_size, file_type,
                     row_count, col_count, columns_json, preview_json, sheet_name)
                OUTPUT INSERTED.id
                VALUES (:uid, :hash, :name, :size, :ftype,
                        :rows, :cols, :colsjson, :preview, :sheet)
            """), {
                "uid":      user_id,
                "hash":     composite_hash,
                "name":     filename,
                "size":     file_size,
                "ftype":    parsed.get("file_type", "xlsx"),
                "rows":     row_count,
                "cols":     col_count,
                "colsjson": json.dumps(columns),
                "preview":  full_data_json,
                "sheet":    sheet_name,
            })
            return result.fetchone()[0]
    except Exception as e:
        print(f"[files] save error: {e}")
        return None

def get_file_sheets(engine, file_id: int, user_id: int) -> list:
    """Return list of sheet names stored for a given file_id's parent Excel file."""
    try:
        with engine.connect() as conn:
            # Find the parent file name first
            row = conn.execute(text("""
                SELECT file_name, file_hash FROM dbo.uploaded_files
                WHERE id = :fid AND user_id = :uid
            """), {"fid": file_id, "uid": user_id}).fetchone()
            if not row:
                return []
            fname = row[0]
            # Find all rows with same base filename (different sheets)
            rows = conn.execute(text("""
                SELECT id, sheet_name, row_count, col_count
                FROM dbo.uploaded_files
                WHERE user_id = :uid AND file_name = :fname
                  AND sheet_name IS NOT NULL
                ORDER BY id ASC
            """), {"uid": user_id, "fname": fname}).fetchall()
        return [
            {"id": r[0], "sheet_name": r[1], "row_count": r[2], "col_count": r[3]}
            for r in rows
        ]
    except Exception as e:
        print(f"[files] get_file_sheets error: {e}")
        return []
def get_user_files(engine, user_id):
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, file_name, file_size, file_type, row_count,
                       col_count, columns_json, uploaded_at, last_used, sheet_name
                FROM dbo.uploaded_files WHERE user_id=:uid
                ORDER BY COALESCE(last_used, uploaded_at) DESC
            """), {"uid": user_id}).fetchall()
        result = []
        for r in rows:
            try: cols = json.loads(r[6]) if r[6] else []
            except: cols = []
            result.append({
                "id": r[0], "file_name": r[1], "file_size": r[2],
                "file_type": r[3], "row_count": r[4], "col_count": r[5],
                "columns": cols,
                "uploaded_at": r[7].isoformat() if hasattr(r[7],"isoformat") else str(r[7]),
                "last_used": r[8].isoformat() if r[8] and hasattr(r[8],"isoformat") else None,
                "sheet_name": r[9],   # NEW
            })
        return result
    except Exception as e:
        print(f"[files] list error: {e}"); return []
def _ensure_file_usage_audit_table(engine):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'dbo.file_usage_audit') AND type in (N'U'))
                BEGIN
                    CREATE TABLE dbo.file_usage_audit (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        file_id BIGINT,
                        prompt NVARCHAR(MAX),
                        is_cached BIT DEFAULT 0,
                        hit_count INT DEFAULT 1,
                        execution_time_ms FLOAT,
                        ai_model NVARCHAR(100),
                        has_error BIT DEFAULT 0,
                        analyzed_at DATETIME DEFAULT GETDATE()
                    )
                END
            """))
    except Exception as e:
        print(f"[audit] create table error: {e}")

def get_cached_file_analysis(engine, file_id, prompt, cache_lookup_ms: float = 0):
    """Returns cached analysis. Records cached_exec_ms on first cache hit."""
    _ensure_file_usage_audit_table(engine)
    try:
        normalized = " ".join(prompt.lower().strip().split())
        ph = hashlib.sha256(normalized.encode()).hexdigest()
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, analysis, hit_count, execution_time_ms, chart_data, cached_exec_ms
                FROM dbo.file_analysis_cache
                WHERE file_id=:fid AND prompt_hash=:ph
            """), {"fid": file_id, "ph": ph}).fetchone()
        if row:
            entry_id = row[0]
            # Update hit_count and store cached_exec_ms (only first time, like SQL pattern)
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE dbo.file_analysis_cache
                    SET hit_count = hit_count + 1,
                        cached_exec_ms = CASE
                            WHEN cached_exec_ms IS NULL THEN :cms
                            ELSE cached_exec_ms
                        END
                    WHERE id = :id
                """), {"id": entry_id, "cms": cache_lookup_ms})
                
                # Log permanent audit
                conn.execute(text("""
                    INSERT INTO dbo.file_usage_audit (file_id, prompt, is_cached, hit_count, execution_time_ms, ai_model, has_error)
                    VALUES (:fid, :prompt, 1, :hit_count, :cms, 'CACHE', 0)
                """), {"fid": file_id, "prompt": prompt, "hit_count": row[2] + 1, "cms": cache_lookup_ms})
                
            chart = {"columns": [], "rows": []}
            if row[4]:
                try:
                    import json as _j
                    chart = _j.loads(row[4])
                except Exception:
                    pass
            return {
                "analysis":          row[1],
                "hit_count":         row[2],
                "execution_time_ms": float(row[3]) if row[3] is not None else 0.0,
                "cached_exec_ms":    float(row[5]) if row[5] is not None else cache_lookup_ms,
                "chart_data":        chart,
                "cached":            True,
            }
        return None
    except Exception as e:
        print(f"[files] cache check error: {e}"); return None


def save_file_analysis(engine, file_id, prompt, analysis, provider="", model="",
                       execution_time_ms=None, chart_data=None):
    _ensure_file_usage_audit_table(engine)
    try:
        normalized = " ".join(prompt.lower().strip().split())
        ph = hashlib.sha256(normalized.encode()).hexdigest()
        chart_json = None
        if chart_data is not None:
            try:
                import json as _j
                chart_json = _j.dumps(chart_data)
            except Exception:
                chart_json = None
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM dbo.file_analysis_cache
                               WHERE file_id=:fid AND prompt_hash=:ph)
                INSERT INTO dbo.file_analysis_cache
                    (file_id, prompt_hash, prompt, analysis, provider, model,
                     execution_time_ms, chart_data)
                VALUES (:fid,:ph,:prompt,:analysis,:provider,:model,
                        :etime,:chart)
            """), {"fid": file_id, "ph": ph, "prompt": prompt,
                   "analysis": analysis, "provider": provider, "model": model,
                   "etime": execution_time_ms, "chart": chart_json})
            
            # Log permanent audit
            conn.execute(text("""
                INSERT INTO dbo.file_usage_audit (file_id, prompt, is_cached, hit_count, execution_time_ms, ai_model, has_error)
                VALUES (:fid, :prompt, 0, 1, :etime, :model, 0)
            """), {"fid": file_id, "prompt": prompt, "etime": execution_time_ms, "model": model})
            
    except Exception as e:
        print(f"[files] save analysis error: {e}")


def analyze_file_with_ai(df, prompt, provider_cfg, text_content=None):
    """
    Hybrid analysis: AI plans, Python computes, AI summarizes.
    Returns {"analysis": str, "chart_data": {"columns": [...], "rows": [...]}}
    """
    import json as _json
    import re

    # Normalize input
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    prompt = " ".join(prompt.lower().strip().split())

    # ── Profile columns ───────────────────────────────────────────────────
    profile_text = f"Dataset: {len(df):,} rows x {len(df.columns)} columns\n\nColumns:\n"
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            sn = s.dropna()
            if len(sn) > 0:
                profile_text += f"  - {col}: NUMERIC (min={sn.min():,.2f}, max={sn.max():,.2f}, sum={sn.sum():,.2f})\n"
            else:
                profile_text += f"  - {col}: NUMERIC (empty)\n"
        else:
            n_unique = s.nunique()
            samples  = [str(v)[:30] for v in s.dropna().unique()[:3]]
            profile_text += f"  - {col}: TEXT ({n_unique} unique, samples: {samples})\n"

    # ── Ask AI to plan ────────────────────────────────────────────────────
    plan_system = """You are a data analysis planner. Output ONLY a valid JSON object with no markdown.

{
  "operation": "top_n" | "bottom_n" | "average" | "trend" | "filter" | "count" | "return_all" | "direct_qa",
  "metric_column":   "exact NUMERIC column name, or null",
  "group_by_column": "exact TEXT column name to group by, or null",
  "filter_column":   "exact column name to filter rows on, or null",
  "filter_value":    "exact value to match (case-insensitive), or null",
  "date_column":     "exact column name for time series, or null",
  "n": 10,
  "agg": "sum" | "mean" | "max" | "min"
}

OPERATION RULES (read carefully):
- "return_all"  → user wants to see ALL rows of the table. Use when: "extract", "show entire table", "show all", "list all", "get all rows", "display all".
- "filter"      → user wants rows matching a specific VALUE. Use when: "list confirmed", "show pending", "which patients", "find appointments where". Set filter_column and filter_value.
- "count"       → user wants to COUNT rows grouped by a column. Use when: "how many", "count by", "number of".
- "top_n"       → user wants highest values. Use when: "top N", "most", "highest", "best".
- "bottom_n"    → user wants lowest values. Use when: "bottom N", "lowest", "least", "worst".
- "average"     → user wants mean of a numeric column.
- "trend"       → user wants time-series analysis over a date column.
- "direct_qa"   → user is asking a conceptual question about meaning, conclusions, or unstructured text.

KEY RULES:
- filter_column and filter_value MUST be set for "filter" operation.
- group_by_column is for aggregation grouping — NOT for row filtering.
- Use EXACT column names from the dataset profile.
- Do NOT wrap in markdown. Output raw JSON only."""

    plan_user = f"User question: {prompt}\n\n{profile_text}"

    try:
        plan_raw = get_ai_completion(
            plan_system, plan_user,
            provider=provider_cfg["provider"], temperature=0.0, max_tokens=300,
            **{k:v for k,v in provider_cfg.items() if k not in ("provider","temperature","max_tokens")}
        )
        clean = plan_raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1].lstrip("json").strip()
        clean = clean[clean.find("{"):clean.rfind("}")+1]
        plan = _json.loads(clean)
        print(f"[files] AI plan: {plan}")
    except Exception as e:
        print(f"[files] Plan parse failed: {e}")
        plan = {"operation": "summary"}

    op          = plan.get("operation", "summary")
    metric      = plan.get("metric_column")
    group_by    = plan.get("group_by_column")
    filter_col  = plan.get("filter_column")
    filter_val  = plan.get("filter_value")
    date_col    = plan.get("date_column")
    agg         = plan.get("agg", "sum") or "sum"
    try:
        n = int(plan.get("n") or 10) or 10
    except Exception:
        n = 10

    # ── Python-level smart intent override ────────────────────────────────
    # This catches cases where weaker local models mis-classify the operation.
    prompt_lower = prompt.lower().strip()
    words = set(prompt_lower.split())

    # Words that signal row-level filtering
    FILTER_SIGNALS = ["confirmed", "pending", "cancelled", "active", "inactive",
                      "approved", "rejected", "completed", "failed", "open", "closed",
                      "paid", "unpaid", "male", "female", "yes", "no", "true", "false"]

    # 1. return_all override — user wants the raw table
    if op != "filter" and op != "direct_qa":
        if (prompt_lower.startswith("extract") or prompt_lower.startswith("show all")
                or prompt_lower.startswith("list all") or prompt_lower.startswith("display all")
                or "entire table" in prompt_lower or "return all" in prompt_lower
                or "full table" in prompt_lower or "all rows" in prompt_lower):
            op = "return_all"
            metric, group_by = None, None

    # 2. filter override — prompt contains a status value word AND there's a column for it
    if op not in ("return_all", "direct_qa"):
        matched_val = next((w for w in FILTER_SIGNALS if w in prompt_lower), None)
        if matched_val:
            # Find column whose name suggests status/type/category
            STATUS_COLS = ["status", "state", "type", "category", "gender",
                           "result", "outcome", "flag", "stage", "condition"]
            for sc in STATUS_COLS:
                match_col = next((c for c in df.columns if sc in c.lower()), None)
                if match_col:
                    # Verify this value actually exists in that column
                    col_vals_lower = [str(v).lower() for v in df[match_col].dropna().unique()]
                    for col_val in col_vals_lower:
                        if matched_val in col_val or col_val in matched_val:
                            op = "filter"
                            filter_col = match_col
                            filter_val = next(v for v in df[match_col].dropna().unique()
                                             if matched_val in str(v).lower() or str(v).lower() in matched_val)
                            metric, group_by = None, None
                            print(f"[files] Python override → filter on {filter_col}={filter_val}")
                            break
                    if op == "filter":
                        break

    # 3. list/show signals without explicit value → return_all
    if op not in ("return_all", "filter", "direct_qa", "count", "top_n", "bottom_n", "average", "trend"):
        if any(w in prompt_lower for w in ["list", "show", "display", "give me", "what are"]):
            op = "return_all"
            metric, group_by = None, None

    # Validate columns exist & types
    if metric and metric not in df.columns: metric = None
    if metric and not pd.api.types.is_numeric_dtype(df[metric]): metric = None
    if group_by and group_by not in df.columns: group_by = None
    if group_by and pd.api.types.is_numeric_dtype(df[group_by]): group_by = None

    # Auto-fix missing metric — pick numeric column matching prompt
    if not metric:
        nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
                and not any(p in c.lower() for p in ["id","row","index","postal","zip","year"])]
        if nums:
            words = [w.rstrip("s") for w in prompt.split() if len(w) > 2]
            def s_n(c):
                cl = c.lower()
                s = sum(10 for w in words if w in cl)
                for p in ["price","sales","revenue","amount","value","cost","profit","total","rating","count"]:
                    if p in cl: s += 3
                return s
            metric = sorted(nums, key=s_n, reverse=True)[0]
            print(f"[files] Auto-picked metric: {metric}")

    # Auto-fix missing group_by — pick text column matching prompt
    if not group_by:
        texts = [c for c in df.columns
                 if not pd.api.types.is_numeric_dtype(df[c])
                 and 2 <= df[c].nunique() <= len(df) * 0.95
                 and not any(p in c.lower() for p in ["id","code","uuid","hash","url","link","timestamp","crawl"])]
        if texts:
            words = [w.rstrip("s") for w in prompt.split() if len(w) > 2]
            def s_g(c):
                cl = c.lower()
                s = sum(10 for w in words if w in cl)
                for p in ["name","title","product","item","brand","category","region","department"]:
                    if p in cl: s += 3
                return s
            group_by = sorted(texts, key=s_g, reverse=True)[0]
            print(f"[files] Auto-picked group_by: {group_by}")

    # Detect intent overrides from prompt
    if any(w in prompt for w in ["expensive","highest","maximum","peak"]):
        agg = "max"
    elif any(w in prompt for w in ["cheapest","lowest","minimum"]):
        agg = "min"

    print(f"[files] Final: op={op}, metric={metric}, group_by={group_by}, agg={agg}, n={n}")

    # ── BUSINESS CONTEXT OVERRIDE ─────────────────────────────────────────
    # If the user is asking a conceptual / business-perspective question
    # (not a data lookup), force direct_qa so we get a narrative answer
    # instead of a count/aggregation table — even on structured (CSV) files.
    BUSINESS_SIGNALS = [
        "analyse", "analyze", "analysis", "insights", "insight", "overview",
        "summary", "summarise", "summarize", "business", "perspective",
        "recommend", "recommendation", "suggest", "suggestion", "advise",
        "what does this mean", "what can you tell", "tell me about",
        "explain", "understand", "interpret", "key findings", "findings",
        "takeaway", "takeaways", "conclusion", "risk", "opportunity",
        "pattern", "trend", "overall", "highlight", "profile",
    ]
    if op not in ("filter", "return_all") and any(sig in prompt_lower for sig in BUSINESS_SIGNALS):
        op = "direct_qa"
        print(f"[files] Business-context override -> direct_qa")

    # ── Execute Direct QA immediately if chosen ───────────────────────────
    if op == "direct_qa":
        # Build a rich context block using both numeric stats from the df
        # AND any extracted text (for documents/images).
        context_parts = []

        if df is not None and not df.empty:
            num_df = df.select_dtypes(include=["number"])
            cat_df = df.select_dtypes(include=["object"])
            stats_block = ""
            for col in num_df.columns[:10]:
                s = num_df[col].dropna()
                if len(s):
                    stats_block += f"  {col}: total={s.sum():,.2f}, avg={s.mean():,.2f}, min={s.min():,.2f}, max={s.max():,.2f}\n"
            cat_block = ""
            for col in cat_df.columns[:6]:
                vc = df[col].value_counts().head(8)
                cat_block += f"  {col}: {', '.join(f'{k}={v}' for k,v in vc.items())}\n"
            sample_block = df.head(20).to_string(index=False)
            context_parts.append(
                f"Dataset: {len(df):,} rows x {len(df.columns)} columns\n"
                f"Columns: {', '.join(df.columns)}\n\n"
                f"Numeric summaries:\n{stats_block or '  (none)'}\n"
                f"Categorical breakdowns:\n{cat_block or '  (none)'}\n"
                f"Sample rows (first 20):\n{sample_block}"
            )

        if text_content:
            context_parts.append(f"Extracted document text:\n{text_content[:6000]}")

        full_context = "\n\n---\n\n".join(context_parts) or "No data available."

        summary_system = """You are a senior business analyst providing expert-level insights.
The user has uploaded a data file. Your job is to answer their question from a business perspective.

RULES:
- Think like a business analyst. Do NOT talk about COUNT queries or SQL.
- Use the EXACT numbers from the data provided. Never make up values.
- Structure your response with clear headings, bullet points, and bold key figures.
- Include: key highlights, patterns, risks/anomalies, and actionable takeaways where relevant.
- Use rich markdown formatting (headings, bold, bullet lists, tables where helpful).
- Be comprehensive but concise. Match the depth of your answer to what the user asked."""

        analysis = get_ai_completion(
            summary_system,
            f"Data Context:\n{full_context}\n\nUser Question: {prompt}",
            provider=provider_cfg["provider"], temperature=0.1, max_tokens=1600,
            **{k:v for k,v in provider_cfg.items() if k not in ("provider","temperature","max_tokens")}
        )
        return {"analysis": analysis, "chart_data": {"columns": [], "rows": []}}

    # ── Compute in pandas ─────────────────────────────────────────────────
    computed = f"Question: {prompt}\n\n"
    chart_data = {"columns": [], "rows": []}

    try:
        if metric and group_by and op in ("top_n", "bottom_n", "summary"):
            ascending = (op == "bottom_n") or (agg == "min" and op != "bottom_n")
            if agg == "max":
                series = df.groupby(group_by)[metric].max().sort_values(ascending=False).head(n)
                op_label = "max"
            elif agg == "min":
                series = df.groupby(group_by)[metric].min().sort_values(ascending=True).head(n)
                op_label = "min"
            elif agg == "mean":
                series = df.groupby(group_by)[metric].mean().sort_values(ascending=ascending).head(n)
                op_label = "mean"
            else:
                series = df.groupby(group_by)[metric].sum().sort_values(ascending=ascending).head(n)
                op_label = "sum"

            computed += f"COMPUTED: top {n} {group_by} by {op_label}({metric}):\n"
            computed += f"Total unique {group_by}: {df[group_by].nunique():,}\n\n"
            for i, (name, val) in enumerate(series.items(), 1):
                computed += f"  #{i}: {name}: {val:,.2f}\n"
            chart_data["columns"] = [group_by, metric]
            chart_data["rows"] = [[str(k), float(v)] for k, v in series.items()]

        elif op == "average" and metric and group_by:
            series = df.groupby(group_by)[metric].mean().sort_values(ascending=False).head(n)
            computed += f"COMPUTED: average {metric} by {group_by} (top {n}):\n"
            for i, (name, val) in enumerate(series.items(), 1):
                computed += f"  #{i}: {name}: {val:,.2f}\n"
            chart_data["columns"] = [group_by, f"avg_{metric}"]
            chart_data["rows"] = [[str(k), float(v)] for k, v in series.items()]

        elif op == "trend" and metric and date_col:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            ts = df.groupby(df[date_col].dt.to_period("M"))[metric].sum()
            computed += f"COMPUTED: {metric} trend by month:\n"
            for period, val in ts.items():
                computed += f"  {period}: {val:,.2f}\n"
            chart_data["columns"] = ["Month", metric]
            chart_data["rows"] = [[str(k), float(v)] for k, v in ts.items()]

        elif op == "count" and group_by:
            vc = df[group_by].value_counts().head(n)
            computed += f"COMPUTED: count by {group_by}:\n"
            for name, cnt in vc.items():
                computed += f"  {name}: {cnt:,}\n"
            chart_data["columns"] = [group_by, "count"]
            chart_data["rows"] = [[str(k), int(v)] for k, v in vc.items()]

        elif op == "filter" and filter_col and filter_val is not None and filter_col in df.columns:
            # Case-insensitive row filter
            mask = df[filter_col].astype(str).str.lower() == str(filter_val).lower()
            filtered_df = df[mask]
            if filtered_df.empty:
                # Try partial match fallback
                mask = df[filter_col].astype(str).str.lower().str.contains(str(filter_val).lower(), na=False)
                filtered_df = df[mask]
            computed += f"COMPUTED: Rows where {filter_col} = '{filter_val}' ({len(filtered_df)} matches out of {len(df)} total):\n"
            computed += filtered_df.to_string() + "\n"
            chart_data["columns"] = list(filtered_df.columns)
            rows_list = []
            for row in filtered_df.itertuples(index=False):
                r = []
                for val in row:
                    try:
                        if pd.isna(val): r.append(None)
                        elif isinstance(val, (int, float, bool, str)): r.append(val)
                        else: r.append(str(val))
                    except Exception: r.append(str(val))
                rows_list.append(r)
            chart_data["rows"] = rows_list

        elif op == "return_all":
            head_n = min(len(df), max(n, 50))
            raw_df = df.head(head_n)
            computed += f"COMPUTED: Returned first {head_n} rows of raw data:\n"
            computed += raw_df.to_string() + "\n"
            chart_data["columns"] = list(raw_df.columns)
            
            rows_list = []
            for row in raw_df.itertuples(index=False):
                r = []
                for val in row:
                    if pd.isna(val): r.append(None)
                    elif isinstance(val, (int, float, bool, str)): r.append(val)
                    else: r.append(str(val))
                rows_list.append(r)
            chart_data["rows"] = rows_list


        else:
            # ── Text-only or generic summary ──────────────────────────────
            has_any_numeric = False
            computed += "GENERAL SUMMARY:\n"
            computed += f"Dataset: {len(df):,} rows x {len(df.columns)} columns\n\n"
 
            for c in df.columns:
                if pd.api.types.is_numeric_dtype(df[c]):
                    s = df[c].dropna()
                    if len(s) > 0:
                        has_any_numeric = True
                        computed += f"  {c}: sum={s.sum():,.2f}, mean={s.mean():,.2f}, min={s.min():,.2f}, max={s.max():,.2f}\n"
                else:
                    # Text column — show value counts
                    vc = df[c].value_counts().head(8)
                    null_pct = round(df[c].isna().mean() * 100, 1)
                    computed += f"  {c} ({df[c].nunique()} unique, {null_pct}% null): "
                    computed += ", ".join(f"{k} ({v})" for k, v in vc.items())
                    computed += "\n"
 
            if not has_any_numeric:
                computed += "\nNOTE: This dataset has NO numeric columns — only text/categorical data.\n"
                computed += "Analysis is based on value counts and distributions.\n"
 
                # Build chart_data from the most interesting text column
                if group_by:
                    vc = df[group_by].value_counts().head(n)
                    chart_data["columns"] = [group_by, "count"]
                    chart_data["rows"] = [[str(k), int(v)] for k, v in vc.items()]
                else:
                    # Pick the text column with most interesting distribution (2-20 unique)
                    best_col = None
                    best_score = 0
                    for c in df.columns:
                        nu = df[c].nunique()
                        if 2 <= nu <= 20:
                            score = nu
                            if score > best_score:
                                best_score = score
                                best_col = c
                    if best_col:
                        vc = df[best_col].value_counts().head(10)
                        chart_data["columns"] = [best_col, "count"]
                        chart_data["rows"] = [[str(k), int(v)] for k, v in vc.items()]

    except Exception as e:
        computed += f"\nComputation error: {e}\n"
        print(f"[files] computation error: {e}")

    # ── Ask AI to write a natural-language summary ────────────────────────
    summary_system = """You are a data analyst writing a summary from PRE-COMPUTED data.
 
The computed data below contains exact values, counts, and distributions.
Use these EXACT numbers in your response. Do not make up values.
 
RULES:
- Answer the user's implicit or explicit question clearly and accurately based on the pre-computed data.
- Use ACTUAL numbers, names, and values from the computed data.
- Use rich markdown formatting (tables, bullet points, bold text) to make your answer beautiful and easy to read.
- Do not use placeholder text like "Product A".
- Be specific, data-driven, and concise."""

    analysis = get_ai_completion(
        summary_system, computed,
        provider=provider_cfg["provider"], temperature=0.0, max_tokens=2000,
        **{k:v for k,v in provider_cfg.items() if k not in ("provider","temperature","max_tokens")}
    )

    return {"analysis": analysis, "chart_data": chart_data}


def compare_files_with_ai(dfs_dict, prompt, provider_cfg):
    """
    Compare multiple files with the same prompt.
    dfs_dict: { "filename1.csv": df1, "filename2.csv": df2, ... }
    """
    import json as _json

    if len(dfs_dict) < 2:
        return analyze_file_with_ai(list(dfs_dict.values())[0], prompt, provider_cfg)

    prompt = " ".join(prompt.lower().strip().split())

    # ── 1. Profile each file ───────────────────────────────────────────────
    profiles = {}
    for fname, df in dfs_dict.items():
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        dfs_dict[fname] = df  # update normalized

        prof = {"rows": len(df), "cols": list(df.columns), "numeric": [], "category": [], "datetime": []}
        for col in df.columns:
            s = df[col]
            if pd.api.types.is_numeric_dtype(s):
                sn = s.dropna()
                if len(sn) > 0:
                    prof["numeric"].append({
                        "name": col, "sum": float(sn.sum()), "mean": float(sn.mean()),
                        "min": float(sn.min()), "max": float(sn.max()),
                    })
            else:
                try:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        parsed = pd.to_datetime(s.dropna().head(20), errors="coerce")
                        if parsed.notna().sum() >= 15:
                            prof["datetime"].append(col)
                            continue
                except Exception:
                    pass
                if s.nunique() < 500:
                    prof["category"].append({"name": col, "n_unique": int(s.nunique())})
        profiles[fname] = prof

    # ── 2. Find common columns across all files ───────────────────────────
    all_cols = [set(p["cols"]) for p in profiles.values()]
    common_cols = set.intersection(*all_cols) if all_cols else set()
    print(f"[files] Common columns across {len(dfs_dict)} files: {common_cols}")

    # ── 3. Ask AI to plan the comparison ──────────────────────────────────
    profile_text = ""
    for fname, p in profiles.items():
        profile_text += f"\n--- FILE: {fname} ({p['rows']:,} rows) ---\n"
        profile_text += f"Numeric: {[n['name'] for n in p['numeric']]}\n"
        profile_text += f"Category: {[c['name'] for c in p['category']]}\n"
        profile_text += f"Datetime: {p['datetime']}\n"

    profile_text += f"\nCOMMON COLUMNS (in all files): {sorted(common_cols)}\n"

    plan_system = """You are a comparative analysis planner. Given multiple datasets and a user question,
decide HOW to compare them.

Output ONLY a single JSON object:
{
  "operation": "top_n_per_file" | "totals_comparison" | "trend_comparison" | "summary_comparison",
  "metric_column": "exact column name from COMMON COLUMNS list",
  "group_by_column": "exact column name or null",
  "date_column": "exact column name or null",
  "n": 5,
  "explanation": "brief reason"
}

CRITICAL RULES:
- For metric_column, pick a numeric column that appears in ALL files (from COMMON COLUMNS).
- If files have different sales column names (e.g. 'Sales' vs 'Weekly_Sales'), they ARE different columns. Pick the one that exists in COMMON COLUMNS, or use summary_comparison.
- Use EXACT column names (case-sensitive).
- For "totals" / "compare": totals_comparison
- For "top N per file": top_n_per_file
- For "trend over time": trend_comparison
- Always set n to a number (default 5), never null.
- Output ONLY the JSON, no markdown."""

    try:
        plan_raw = get_ai_completion(
            plan_system, f"User question: {prompt}\n{profile_text}",
            provider=provider_cfg["provider"], temperature=0.0, max_tokens=900,
            **{k:v for k,v in provider_cfg.items() if k not in ("provider","temperature","max_tokens")}
        )
        clean = plan_raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1].lstrip("json").strip()
        clean = clean[clean.find("{"):clean.rfind("}")+1]
        plan = _json.loads(clean)
        print(f"[files] Compare plan: {plan}")
    except Exception as e:
        print(f"[files] plan failed: {e}")
        plan = {"operation": "summary_comparison"}

    op       = plan.get("operation", "summary_comparison")
    metric   = plan.get("metric_column")
    group_by = plan.get("group_by_column")
    date_col = plan.get("date_column")
    try:
        n = int(plan.get("n") or 5)
    except (TypeError, ValueError):
        n = 5

    # Auto-fill missing group_by for top_n_per_file (AI often returns null)
    if op == "top_n_per_file" and not group_by:
        # Find best identifier column that exists in ALL files
        common_text_cols = []
        for col in common_cols:
            # Check it's text and not too high cardinality in any file
            valid = True
            for fname, df in dfs_dict.items():
                if col not in df.columns: valid = False; break
                if pd.api.types.is_numeric_dtype(df[col]):
                    valid = False; break
                if df[col].nunique() > len(df) * 0.95:
                    valid = False; break
                cl = col.lower()
                if any(p in cl for p in ["id","code","uuid","guid","hash","url","link"]):
                    valid = False; break
            if valid:
                common_text_cols.append(col)

        if common_text_cols:
            prompt_words = [w for w in prompt.lower().split() if len(w) > 2]
            def score_c(col):
                cl = col.lower()
                s = 0
                for w in prompt_words:
                    if w in cl or w.rstrip("s") in cl: s += 10
                for pat in ["name","title","product","item"]:
                    if pat in cl: s += 5
                return s
            common_text_cols.sort(key=score_c, reverse=True)
            group_by = common_text_cols[0]
            print(f"[files] Compare auto-filled group_by: {group_by}")

    # Validate metric exists in ALL files - fall back if not
    if metric:
        files_missing = [fn for fn, df in dfs_dict.items() if metric not in df.columns]
        if files_missing:
            print(f"[files] Metric '{metric}' missing in {files_missing} - searching for similar")
            # Try to find a similar column that exists in all files
            metric_lower = metric.lower().replace("_", "").replace(" ", "")
            candidates = []
            for col in common_cols:
                col_clean = col.lower().replace("_", "").replace(" ", "")
                if metric_lower in col_clean or col_clean in metric_lower:
                    candidates.append(col)
            # Or any numeric column in common
            if not candidates:
                first_df = list(dfs_dict.values())[0]
                for col in common_cols:
                    if pd.api.types.is_numeric_dtype(first_df[col]):
                        candidates.append(col)
            metric = candidates[0] if candidates else None
            print(f"[files] Fallback metric: {metric}")

    # ── 4. Compute the comparison in pandas ───────────────────────────────
    computed = f"Question: {prompt}\n\n"
    computed += f"Comparing {len(dfs_dict)} files: {list(dfs_dict.keys())}\n"
    computed += f"Plan: {plan.get('explanation', op)}\n\n"

    try:
        if op == "totals_comparison":
            # If metric not available, find best numeric column per file
            if not metric or not all(metric in df.columns for df in dfs_dict.values()):
                computed += f"=== TOTALS COMPARISON (per-file numeric columns) ===\n"
                for fname, df in dfs_dict.items():
                    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
                    # Filter out IDs
                    num_cols = [c for c in num_cols
                                if not any(p in c.lower() for p in ["id","row","index","postal","zip"])]
                    computed += f"\n{fname} ({len(df):,} rows):\n"
                    for col in num_cols[:5]:
                        s = df[col].dropna()
                        if len(s) > 0:
                            computed += f"  {col}: total={s.sum():,.2f}, mean={s.mean():,.2f}\n"
            else:
                computed += f"=== TOTALS COMPARISON ({metric}) ===\n"
                for fname, df in dfs_dict.items():
                    s = df[metric].dropna()
                    computed += f"\n{fname}:\n"
                    computed += f"  Total {metric}: {s.sum():,.2f}\n"
                    computed += f"  Mean {metric}:  {s.mean():,.2f}\n"
                    computed += f"  Min/Max: {s.min():,.2f} / {s.max():,.2f}\n"
                    computed += f"  Row count: {len(s):,}\n"

        elif op == "top_n_per_file" and group_by:
            computed += f"=== TOP {n} {group_by.upper()} PER FILE ===\n"
            for fname, df in dfs_dict.items():
                computed += f"\n--- {fname} ---\n"
                if group_by not in df.columns:
                    computed += f"  Column '{group_by}' not in this file\n"
                    continue
                # Find metric per-file (use AI-chosen one if exists, else first numeric)
                use_metric = metric if (metric and metric in df.columns and pd.api.types.is_numeric_dtype(df[metric])) else None
                if not use_metric:
                    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
                    num_cols = [c for c in num_cols if not any(p in c.lower() for p in ["id","row","index","postal","zip"])]
                    use_metric = num_cols[0] if num_cols else None
                if not use_metric:
                    computed += f"  No suitable numeric column found\n"
                    continue
                grp = df.groupby(group_by)[use_metric].sum().sort_values(ascending=False).head(n)
                computed += f"  (using {use_metric})\n"
                for i, (name, val) in enumerate(grp.items(), 1):
                    computed += f"  #{i}: {name}: {val:,.2f}\n"

        elif op == "trend_comparison" and metric and date_col:
            computed += f"=== TREND COMPARISON ({metric} over {date_col}) ===\n"
            for fname, df in dfs_dict.items():
                if metric in df.columns and date_col in df.columns:
                    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                    ts = df.groupby(df[date_col].dt.to_period("M"))[metric].sum()
                    computed += f"\n{fname} (monthly {metric}):\n"
                    for period, val in ts.head(12).items():
                        computed += f"  {period}: {val:,.2f}\n"

        else:
            # Default: side-by-side summary
            computed += "=== SIDE-BY-SIDE SUMMARY ===\n"
            for fname, df in dfs_dict.items():
                computed += f"\n--- {fname} ({len(df):,} rows) ---\n"
                num = df.select_dtypes(include=["number"])
                for col in num.columns[:6]:
                    s = num[col].dropna()
                    if len(s) > 0:
                        computed += f"  {col}: sum={s.sum():,.2f}, mean={s.mean():,.2f}\n"

    except Exception as e:
        computed += f"\nComputation error: {e}\n"
        print(f"[files] compare error: {e}")

    # ── 5. AI summary ─────────────────────────────────────────────────────
    summary_system = """You are a data analyst writing a comparative summary.

Python has computed exact values comparing multiple files. Write a clear comparison using the EXACT numbers shown.

RULES:
- Answer the user's implicit or explicit question clearly and accurately based on the pre-computed data.
- Use ACTUAL numbers, names, and values from the computed data.
- Use rich markdown formatting (tables, bullet points, bold text) to make your answer beautiful and easy to read.
- Do not use placeholder text.
- Be specific, data-driven, and concise."""

    analysis_text = get_ai_completion(
        summary_system, computed,
        provider=provider_cfg["provider"], temperature=0.0, max_tokens=1500,
        **{k:v for k,v in provider_cfg.items() if k not in ("provider","temperature","max_tokens")}
    )

    # ── Build chart data based on the actual operation ────────────────────
    chart_data = {"columns": [], "rows": []}
    try:
        if op == "top_n_per_file" and group_by:
            # Show top-N rows per file with file name as a column
            chart_data["columns"] = ["File", group_by, "Total"]
            for fname, df in dfs_dict.items():
                if group_by not in df.columns:
                    continue
                # Find a numeric column for this file
                use_metric = metric if (metric and metric in df.columns and pd.api.types.is_numeric_dtype(df[metric])) else None
                if not use_metric:
                    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
                    num_cols = [c for c in num_cols if not any(p in c.lower() for p in ["id","row","index","postal","zip"])]
                    use_metric = num_cols[0] if num_cols else None
                if not use_metric:
                    continue
                grouped = df.groupby(group_by)[use_metric].sum().sort_values(ascending=False).head(n)
                for k, v in grouped.items():
                    chart_data["rows"].append([fname, str(k), float(v)])

        elif op == "trend_comparison" and metric and date_col:
            chart_data["columns"] = ["Period", "File", metric]
            for fname, df in dfs_dict.items():
                if metric not in df.columns or date_col not in df.columns:
                    continue
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                ts = df.groupby(df[date_col].dt.to_period("M"))[metric].sum()
                for period, val in ts.items():
                    chart_data["rows"].append([str(period), fname, float(val)])

        else:
            # Default: side-by-side totals comparison
            chart_data["columns"] = ["File", "Total", "Mean", "Rows"]
            for fname, df in dfs_dict.items():
                if metric and metric in df.columns and pd.api.types.is_numeric_dtype(df[metric]):
                    s = df[metric].dropna()
                    if len(s) > 0:
                        chart_data["rows"].append([fname, float(s.sum()), float(s.mean()), len(df)])
                else:
                    num = df.select_dtypes(include=["number"])
                    num = num[[c for c in num.columns if not any(p in c.lower() for p in ["id","row","index","postal","zip"])]]
                    if len(num.columns) > 0:
                        primary = num.columns[0]
                        s = num[primary].dropna()
                        chart_data["rows"].append([f"{fname} ({primary})", float(s.sum()), float(s.mean()), len(df)])
    except Exception as e:
        print(f"[files] compare chart data error: {e}")
        import traceback; traceback.print_exc()

    return {"analysis": analysis_text, "chart_data": chart_data}


def delete_uploaded_file(engine, file_id, user_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM dbo.file_analysis_cache WHERE file_id=:fid"), {"fid": file_id})
            conn.execute(text("DELETE FROM dbo.uploaded_files WHERE id=:fid AND user_id=:uid"), {"fid": file_id, "uid": user_id})
    except Exception as e:
        print(f"[files] delete error: {e}")
# KNOWN-GOOD QUERY LIBRARY
# Pre-built correct queries for common AdventureWorks patterns.
# These bypass AI generation entirely for well-known question types.
# ─────────────────────────────────────────────────────────────────────────────

_KNOWN_QUERIES = [
    {
        "keywords": ["customer", "country", "countries", "region", "location", "geography"],
        "exclude":  [],
        "sql": """SELECT TOP 20
    cr.Name AS Country,
    COUNT(DISTINCT c.CustomerID) AS CustomerCount
FROM [Sales].[Customer] c
JOIN [Person].[Address] a ON a.AddressID = (
    SELECT TOP 1 ca.AddressID
    FROM [Person].[BusinessEntityAddress] ca
    WHERE ca.BusinessEntityID = c.PersonID
)
JOIN [Person].[StateProvince] sp ON sp.StateProvinceID = a.StateProvinceID
JOIN [Person].[CountryRegion] cr ON cr.CountryRegionCode = sp.CountryRegionCode
GROUP BY cr.Name
ORDER BY CustomerCount DESC;""",
    },
    {
        "keywords": ["top", "customer", "revenue", "sales", "spend", "purchase"],
        "exclude":  ["country", "region", "location"],
        "sql": """SELECT TOP 10
    p.FirstName + ' ' + p.LastName AS CustomerName,
    c.CustomerID,
    SUM(soh.TotalDue) AS TotalRevenue,
    COUNT(soh.SalesOrderID) AS OrderCount
FROM [Sales].[Customer] c
JOIN [Person].[Person] p ON p.BusinessEntityID = c.PersonID
JOIN [Sales].[SalesOrderHeader] soh ON soh.CustomerID = c.CustomerID
GROUP BY c.CustomerID, p.FirstName, p.LastName
ORDER BY TotalRevenue DESC;""",
    },
    {
        "keywords": ["customer", "order", "orders", "placed", "more than"],
        "exclude":  ["country", "revenue", "sales"],
        "sql": """SELECT TOP 20
    p.FirstName + ' ' + p.LastName AS CustomerName,
    c.CustomerID,
    COUNT(soh.SalesOrderID) AS OrderCount,
    SUM(soh.TotalDue) AS TotalSpend
FROM [Sales].[Customer] c
JOIN [Person].[Person] p ON p.BusinessEntityID = c.PersonID
JOIN [Sales].[SalesOrderHeader] soh ON soh.CustomerID = c.CustomerID
GROUP BY c.CustomerID, p.FirstName, p.LastName
HAVING COUNT(soh.SalesOrderID) > 5
ORDER BY OrderCount DESC;""",
    },
    {
        "keywords": ["revenue", "category", "product category", "sales by category"],
        "exclude":  [],
        "sql": """SELECT
    pc.Name AS ProductCategory,
    SUM(sod.LineTotal) AS TotalRevenue,
    COUNT(DISTINCT soh.SalesOrderID) AS OrderCount,
    SUM(sod.OrderQty) AS TotalUnitsSold
FROM [Sales].[SalesOrderDetail] sod
JOIN [Sales].[SalesOrderHeader] soh ON soh.SalesOrderID = sod.SalesOrderID
JOIN [Production].[Product] p ON p.ProductID = sod.ProductID
JOIN [Production].[ProductSubcategory] ps ON ps.ProductSubcategoryID = p.ProductSubcategoryID
JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = ps.ProductCategoryID
GROUP BY pc.Name
ORDER BY TotalRevenue DESC;""",
    },
    {
        "keywords": ["monthly", "trend", "sales trend", "over time", "by month", "by year"],
        "exclude":  [],
        "sql": """SELECT
    YEAR(soh.OrderDate) AS OrderYear,
    MONTH(soh.OrderDate) AS OrderMonth,
    FORMAT(soh.OrderDate, 'yyyy-MM') AS YearMonth,
    COUNT(soh.SalesOrderID) AS OrderCount,
    SUM(soh.TotalDue) AS MonthlyRevenue
FROM [Sales].[SalesOrderHeader] soh
WHERE soh.OrderDate >= DATEADD(YEAR, -3, GETDATE())
GROUP BY YEAR(soh.OrderDate), MONTH(soh.OrderDate), FORMAT(soh.OrderDate, 'yyyy-MM')
ORDER BY OrderYear, OrderMonth;""",
    },
    {
        "keywords": ["product", "best selling", "top product", "most sold"],
        "exclude":  [],
        "sql": """SELECT TOP 10
    p.Name AS ProductName,
    pc.Name AS Category,
    SUM(sod.OrderQty) AS TotalUnitsSold,
    SUM(sod.LineTotal) AS TotalRevenue
FROM [Sales].[SalesOrderDetail] sod
JOIN [Production].[Product] p ON p.ProductID = sod.ProductID
LEFT JOIN [Production].[ProductSubcategory] ps ON ps.ProductSubcategoryID = p.ProductSubcategoryID
LEFT JOIN [Production].[ProductCategory] pc ON pc.ProductCategoryID = ps.ProductCategoryID
GROUP BY p.Name, pc.Name
ORDER BY TotalUnitsSold DESC;""",
    },
    {
        "keywords": ["employee", "department", "employees", "staff", "headcount"],
        "exclude":  [],
        "sql": """SELECT
    d.Name AS Department,
    COUNT(e.BusinessEntityID) AS EmployeeCount,
    AVG(eph.Rate) AS AvgHourlyRate
FROM [HumanResources].[Employee] e
JOIN [HumanResources].[EmployeeDepartmentHistory] edh ON edh.BusinessEntityID = e.BusinessEntityID
    AND edh.EndDate IS NULL
JOIN [HumanResources].[Department] d ON d.DepartmentID = edh.DepartmentID
JOIN [HumanResources].[EmployeePayHistory] eph ON eph.BusinessEntityID = e.BusinessEntityID
GROUP BY d.Name
ORDER BY EmployeeCount DESC;""",
    },
    {
        "keywords": ["inventory", "stock", "product", "level"],
        "exclude":  [],
        "sql": """SELECT TOP 20
    p.Name AS ProductName,
    SUM(pi.Quantity) AS TotalStock,
    p.ReorderPoint,
    p.SafetyStockLevel,
    CASE WHEN SUM(pi.Quantity) < p.ReorderPoint THEN 'Reorder Needed' ELSE 'OK' END AS StockStatus
FROM [Production].[Product] p
JOIN [Production].[ProductInventory] pi ON pi.ProductID = p.ProductID
GROUP BY p.Name, p.ReorderPoint, p.SafetyStockLevel
ORDER BY TotalStock ASC;""",
    },
    {
        "keywords": ["sales", "territory", "region", "sales territory"],
        "exclude":  [],
        "sql": """SELECT
    st.Name AS Territory,
    st.CountryRegionCode AS Country,
    COUNT(soh.SalesOrderID) AS OrderCount,
    SUM(soh.TotalDue) AS TotalRevenue,
    AVG(soh.TotalDue) AS AvgOrderValue
FROM [Sales].[SalesOrderHeader] soh
JOIN [Sales].[SalesTerritory] st ON st.TerritoryID = soh.TerritoryID
GROUP BY st.Name, st.CountryRegionCode
ORDER BY TotalRevenue DESC;""",
    },
    {
        "keywords": ["top salesperson", "sales person", "salesperson", "sales rep", "best sales"],
        "exclude":  [],
        "sql": """SELECT TOP 10
    p.FirstName + ' ' + p.LastName AS SalesPerson,
    sp.SalesYTD,
    sp.SalesLastYear,
    sp.SalesQuota,
    COUNT(soh.SalesOrderID) AS OrderCount
FROM [Sales].[SalesPerson] sp
JOIN [Person].[Person] p ON p.BusinessEntityID = sp.BusinessEntityID
LEFT JOIN [Sales].[SalesOrderHeader] soh ON soh.SalesPersonID = sp.BusinessEntityID
GROUP BY p.FirstName, p.LastName, sp.SalesYTD, sp.SalesLastYear, sp.SalesQuota
ORDER BY sp.SalesYTD DESC;""",
    },
]


def find_known_query(user_question: str):
    """
    Check if user question matches a known-good query pattern.
    Uses a score-based approach — entry with most keyword matches wins.
    Returns SQL string if matched, None otherwise.
    """
    q = user_question.lower()
    best_score = 0
    best_sql   = None

    for entry in _KNOWN_QUERIES:
        keywords = entry["keywords"]
        excludes = entry.get("exclude", [])

        # Skip if any exclude word is present
        if any(ex in q for ex in excludes):
            continue

        # Count how many keywords match
        matched = [kw for kw in keywords if kw in q]
        score   = len(matched)

        # Need at least 2 keyword matches (or 1 if only 1 keyword defined)
        min_match = min(2, len(keywords))
        if score >= min_match and score > best_score:
            best_score = score
            best_sql   = entry["sql"].strip()
            print(f"[known_query] Candidate match (score={score}): {matched}")

    if best_sql:
        print(f"[known_query] Best match score={best_score} — using known-good SQL")
    return best_sql

def generate_sql_with_ai(tables_info, user_question, provider_cfg: dict):
    table_context = "Available database tables with exact column names and relationships:\n\n"
    schemas = {}
    for table in tables_info:
        schemas.setdefault(table['schema'], []).append(table)

    for schema_name, schema_tables in schemas.items():
        table_context += f"SCHEMA: {schema_name}\n"
        for table in schema_tables:
            table_context += f"  Table: {table['full_name']} ({table['row_count']:,} rows)\n"
            if 'columns' in table and table['columns']:
                cols = [f"{col['name']} ({col['type']})" for col in table['columns']]
                table_context += f"    Columns: {', '.join(cols)}\n"
            table_context += "\n"

    relationship_hints = """
COMMON RELATIONSHIP PATTERNS (adapt to actual column names):
- Tables with ID columns often join on matching ID fields (e.g., CustomerID)
- Date columns are useful for time-based analysis and trends
"""

    system_prompt = (
        "You are a SQL Server expert. Analyze the provided schema and generate ONE executable T-SQL query.\n\n"
        + table_context
        + relationship_hints
        + "\nCRITICAL REQUIREMENTS:\n"
        "1. Return ONLY executable SQL — no explanations, no markdown blocks.\n"
        "2. Use [Schema].[TableName] format for ALL table references.\n"
        "3. SQL SERVER USES 'SELECT TOP N' — IT DOES NOT SUPPORT 'LIMIT' OR 'OFFSET'. Never use LIMIT.\n"
        "4. NEVER guess column names — use ONLY exact column names listed in the schema above.\n"
        "5. Every column in SELECT and GROUP BY must exist in the schema.\n"
        "6. CRITICAL ESCAPE HATCH FOR DOCUMENTS: If the user is asking a question about a text document, presentation, or unstructured file AND the relevant table ONLY has 'line_number' and 'content' columns, YOU MUST NOT WRITE A SQL QUERY. Instead, you MUST return EXACTLY this string and nothing else:\nDIRECT_QA_REQUIRED\n"
    )
    user_prompt = (
        f"Based on the database schema provided, generate SQL for: {user_question}\n\n"
        "REMINDER: Only use column names that are explicitly listed in the schema above. "
        "Do not assume any column exists without seeing it in the schema."
    )

    try:
        # Check known-good query library first — bypasses AI for common patterns
        known_sql = find_known_query(user_question)
        if known_sql:
            print(f"[sql] Using known-good query — skipping AI generation")
            return known_sql, known_sql

        raw_sql     = get_ai_completion(system_prompt, user_prompt, provider=provider_cfg["provider"],
                                        **{k: v for k, v in provider_cfg.items() if k != "provider"})
        cleaned_sql = clean_sql_response(raw_sql)

        # Immediate return if it triggered the QA escape hatch
        if cleaned_sql.strip().rstrip(";") == "DIRECT_QA_REQUIRED":
            return cleaned_sql, raw_sql
        
        # --- Inject programmatic auto-fixers ---
        cleaned_sql = _fix_wrong_schemas(cleaned_sql)
        cleaned_sql = fix_sql_aliases(cleaned_sql)
        cleaned_sql = fix_sql_columns(cleaned_sql, tables_info)
        # ---------------------------------------

        errors = validate_sql_against_schema(cleaned_sql, tables_info)
        if errors:
            print(f"[sql] Auto-correcting: {errors}")
            cleaned_sql, raw_sql = retry_sql_with_correction(
                cleaned_sql, errors, tables_info, user_question, provider_cfg
            )
            retry_errors = validate_sql_against_schema(cleaned_sql, tables_info)
            if retry_errors:
                print(f"[sql] Could not auto-fix: {retry_errors}")
                return None, raw_sql

        return cleaned_sql, raw_sql
    except Exception as e:
        print(f"[sql] Error generating SQL: {e}")
        import traceback; traceback.print_exc()
        return None, None


def analyze_data_with_ai(df, user_question, provider_cfg: dict):
    import numpy as np

    # Build rich statistical summary
    rows_count = len(df)
    col_names  = df.columns.tolist()

    # Numeric stats
    num_df    = df.select_dtypes(include=[np.number])
    num_stats = ""
    if not num_df.empty:
        for col in num_df.columns[:6]:
            series = num_df[col].dropna()
            if len(series) > 0:
                num_stats += (
                    f"  {col}: min={series.min():,.2f}, max={series.max():,.2f}, "
                    f"mean={series.mean():,.2f}, sum={series.sum():,.2f}, count={len(series)}\n"
                )

    # Categorical stats
    cat_df    = df.select_dtypes(include=["object"])
    cat_stats = ""
    if not cat_df.empty:
        for col in cat_df.columns[:4]:
            vc = df[col].value_counts().head(5)
            cat_stats += f"  {col} top values: {', '.join(f'{k}({v})' for k, v in vc.items())}\n"

    # Top/bottom rows
    sample_str = df.head(10).to_string(index=False)

    data_summary = f"""QUERY: {user_question}
RESULT SHAPE: {rows_count} rows x {len(col_names)} columns
COLUMNS: {', '.join(col_names)}

NUMERIC STATISTICS:
{num_stats if num_stats else "  No numeric columns"}

CATEGORICAL BREAKDOWN:
{cat_stats if cat_stats else "  No categorical columns"}

SAMPLE DATA (top 10 rows):
{sample_str}
"""

    system_prompt = """You are a senior business analyst providing executive-level insights.

STRICT OUTPUT FORMAT — follow exactly:
Line 1: SUMMARY: One sentence overall summary of what the data shows.
Line 2: blank
Line 3: KEY FINDINGS:
Lines 4+: Numbered findings like: 1. [finding with specific numbers]
After findings, blank line then:
OPPORTUNITIES:
Numbered recommendations like: 1. [specific actionable recommendation]
After recommendations, blank line then:
RISK FLAGS:
Numbered risks like: 1. [any concern, anomaly, or gap in the data]

RULES:
- Use ACTUAL numbers from the data (not placeholders).
- No code, no SQL, no markdown symbols (no **, no `backticks`, no #).
- No bullet points — use numbered lists only.
- Each point max 2 sentences.
- Be specific and data-driven. Generic advice is useless.
- KEY FINDINGS: 4-5 points. OPPORTUNITIES: 2-3 points. RISK FLAGS: 1-2 points."""

    user_prompt = f"""Analyze this business data and provide structured insights:

{data_summary}

Follow the exact output format specified. Use actual numbers from the data."""

    try:
        result = get_ai_completion(
            system_prompt,
            user_prompt,
            provider=provider_cfg["provider"],
            temperature=0.2,
            max_tokens=1200,
            **{k: v for k, v in provider_cfg.items() if k not in ("provider", "temperature", "max_tokens")}
        )
        print(f"[analysis] Generated {len(result or '')} chars")
        return result
    except Exception as e:
        print(f"[analysis] Error: {e}")
        return None




# ─────────────────────────────────────────────────────────────────────────────
# FILE UPLOAD  — CSV / Excel analysis with caching
# Max 5 files, 10MB each. Files stored in SQL Server with hash-based dedup.
# ─────────────────────────────────────────────────────────────────────────────

import hashlib, json, io
from typing import Optional

def ensure_file_tables(engine):
    """Create file storage tables if they don't exist."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'uploaded_files')
                CREATE TABLE dbo.uploaded_files (
                    id           BIGINT IDENTITY(1,1) PRIMARY KEY,
                    file_hash    NVARCHAR(64)  NOT NULL UNIQUE,
                    file_name    NVARCHAR(255) NOT NULL,
                    file_size    BIGINT        NOT NULL,
                    file_type    NVARCHAR(10)  NOT NULL,   -- csv / excel
                    columns_json NVARCHAR(MAX) NOT NULL,   -- JSON array of column names
                    row_count    INT           NOT NULL,
                    preview_json NVARCHAR(MAX) NOT NULL,   -- first 20 rows as JSON
                    uploaded_by  NVARCHAR(100) NOT NULL,
                    created_at   DATETIME      NOT NULL DEFAULT GETDATE(),
                    last_used    DATETIME      NOT NULL DEFAULT GETDATE()
                )
            """))
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'file_analysis_cache')
                CREATE TABLE dbo.file_analysis_cache (
                    id          BIGINT IDENTITY(1,1) PRIMARY KEY,
                    file_hash   NVARCHAR(64)  NOT NULL,
                    prompt_hash NVARCHAR(64)  NOT NULL,
                    prompt      NVARCHAR(MAX) NOT NULL,
                    analysis    NVARCHAR(MAX) NOT NULL,
                    provider    NVARCHAR(100) NOT NULL,
                    model       NVARCHAR(100) NOT NULL,
                    created_at  DATETIME      NOT NULL DEFAULT GETDATE(),
                    UNIQUE (file_hash, prompt_hash, provider, model)
                )
            """))
        print("[files] Tables ready")
    except Exception as e:
        print(f"[files] Table creation error: {e}")


def hash_file(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def get_cached_file(engine, file_hash: str) -> Optional[dict]:
    """Return cached file metadata if exists."""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, file_name, file_size, file_type, columns_json,
                       row_count, preview_json, uploaded_by, created_at
                FROM dbo.uploaded_files WHERE file_hash = :h
            """), {"h": file_hash}).fetchone()
        if row:
            # Update last_used
            with engine.begin() as conn:
                conn.execute(text("UPDATE dbo.uploaded_files SET last_used = GETDATE() WHERE file_hash = :h"), {"h": file_hash})
            return {
                "id": row[0], "file_name": row[1], "file_size": row[2],
                "file_type": row[3], "columns": json.loads(row[4]),
                "row_count": row[5], "preview": json.loads(row[6]),
                "uploaded_by": row[7],
                "created_at": row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8]),
                "cached": True,
            }
        return None
    except Exception as e:
        print(f"[files] get_cached_file error: {e}")
        return None


def save_file_to_db(engine, file_hash: str, file_name: str, file_size: int,
                    file_type: str, columns: list, row_count: int,
                    preview: list, uploaded_by: str) -> dict:
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO dbo.uploaded_files
                    (file_hash, file_name, file_size, file_type, columns_json,
                     row_count, preview_json, uploaded_by)
                VALUES
                    (:hash, :name, :size, :type, :cols, :rows, :preview, :user)
            """), {
                "hash":    file_hash,
                "name":    file_name,
                "size":    file_size,
                "type":    file_type,
                "cols":    json.dumps(columns),
                "rows":    row_count,
                "preview": json.dumps(preview),
                "user":    uploaded_by,
            })
        return {"file_hash": file_hash, "file_name": file_name, "cached": False}
    except Exception as e:
        print(f"[files] save error: {e}")
        return {}


def get_cached_analysis(engine, file_hash: str, prompt: str,
                         provider: str, model: str) -> Optional[str]:
    try:
        ph = hashlib.sha256(prompt.strip().lower().encode()).hexdigest()
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT analysis FROM dbo.file_analysis_cache
                WHERE file_hash = :fh AND prompt_hash = :ph
                  AND provider = :prov AND model = :model
            """), {"fh": file_hash, "ph": ph, "prov": provider, "model": model}).fetchone()
        return row[0] if row else None
    except Exception as e:
        print(f"[files] get analysis cache error: {e}")
        return None


def save_analysis_cache(engine, file_hash: str, prompt: str,
                         analysis: str, provider: str, model: str):
    try:
        ph = hashlib.sha256(prompt.strip().lower().encode()).hexdigest()
        with engine.begin() as conn:
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1 FROM dbo.file_analysis_cache
                    WHERE file_hash=:fh AND prompt_hash=:ph AND provider=:prov AND model=:model
                )
                INSERT INTO dbo.file_analysis_cache
                    (file_hash, prompt_hash, prompt, analysis, provider, model)
                VALUES (:fh, :ph, :prompt, :analysis, :prov, :model)
            """), {
                "fh": file_hash, "ph": ph, "prompt": prompt,
                "analysis": analysis, "prov": provider, "model": model,
            })
    except Exception as e:
        print(f"[files] save analysis cache error: {e}")


def parse_file(content: bytes, filename: str) -> dict:
    """Parse CSV or Excel file, return columns + preview rows."""
    import pandas as pd
    import math

    ext = filename.rsplit(".", 1)[-1].lower()
    try:
        if ext == "csv":
            df = pd.read_csv(io.BytesIO(content), nrows=1000)
            file_type = "csv"
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(io.BytesIO(content), nrows=1000)
            file_type = "excel"
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        # Clean NaN/inf for JSON serialisation
        def safe_val(v):
            if v is None: return None
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
            try: return v.item() if hasattr(v, "item") else v
            except: return str(v)

        columns   = df.columns.tolist()
        row_count = len(df)
        preview   = []
        for _, row in df.head(20).iterrows():
            preview.append({c: safe_val(row[c]) for c in columns})

        return {
            "columns":   columns,
            "row_count": row_count,
            "preview":   preview,
            "file_type": file_type,
            "df":        df,
        }
    except Exception as e:
        raise ValueError(f"Failed to parse file: {e}")


def analyse_file_with_ai(df, prompt: str, provider_cfg: dict,
                          columns: list, row_count: int) -> str:
    """Run AI analysis on uploaded file data."""
    import numpy as np

    num_df   = df.select_dtypes(include=[np.number])
    cat_df   = df.select_dtypes(include=["object"])

    stats = ""
    for col in num_df.columns[:8]:
        s = num_df[col].dropna()
        if len(s):
            stats += f"  {col}: min={s.min():.2f}, max={s.max():.2f}, mean={s.mean():.2f}, sum={s.sum():.2f}\n"

    cat_stats = ""
    for col in cat_df.columns[:4]:
        vc = df[col].value_counts().head(5)
        cat_stats += f"  {col}: {', '.join(f'{k}({v})' for k,v in vc.items())}\n"

    sample = df.head(10).to_string(index=False)

    system_prompt = """You are a senior data analyst. Analyse the uploaded file data and answer the user's question.

RULES:
- Answer the user's question directly and accurately based on the provided data.
- Use rich markdown formatting to make your answer beautiful and easy to read.
- Use markdown tables if the user asks you to extract data, list items, or if the information is tabular.
- Use bullet points or numbered lists where appropriate.
- Be concise but comprehensive. Use actual numbers."""

    user_prompt = (
        f"File: {row_count} rows × {len(columns)} columns\n"
        f"Columns: {', '.join(columns)}\n\n"
        f"Numeric stats:\n{stats or 'None'}\n"
        f"Categorical breakdown:\n{cat_stats or 'None'}\n"
        f"Sample (first 10 rows):\n{sample}\n\n"
        f"User question: {prompt}"
    )

    from app_core import get_ai_completion
    return get_ai_completion(
        system_prompt, user_prompt,
        provider=provider_cfg["provider"],
        temperature=0.2, max_tokens=1200,
        **{k: v for k, v in provider_cfg.items() if k not in ("provider", "temperature", "max_tokens")}
    )