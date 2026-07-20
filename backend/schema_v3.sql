-- =============================================================================
-- schema_v3.sql  —  SQL Data Analysis Agent  (Fresh Schema v3)
-- 8-Table Consolidated Design
-- Database : AdventureWorks2025
-- Run as   : sa / sysadmin role
-- =============================================================================

USE AdventureWorks2025;
GO

-- =============================================================================
-- STEP 1 : DROP OLD TABLES  (order matters — child before parent)
-- =============================================================================

-- old voice tables
IF OBJECT_ID('dbo.voice_transcripts',   'U') IS NOT NULL DROP TABLE dbo.voice_transcripts;
IF OBJECT_ID('dbo.voice_cache',         'U') IS NOT NULL DROP TABLE dbo.voice_cache;

-- old chat / audit tables
IF OBJECT_ID('dbo.chat_history',        'U') IS NOT NULL DROP TABLE dbo.chat_history;
IF OBJECT_ID('dbo.chat_sessions',       'U') IS NOT NULL DROP TABLE dbo.chat_sessions;
IF OBJECT_ID('dbo.ai_query_audit',      'U') IS NOT NULL DROP TABLE dbo.ai_query_audit;

-- old cache tables
IF OBJECT_ID('dbo.file_analysis_cache', 'U') IS NOT NULL DROP TABLE dbo.file_analysis_cache;
IF OBJECT_ID('dbo.response_cache',      'U') IS NOT NULL DROP TABLE dbo.response_cache;

-- old file table
IF OBJECT_ID('dbo.uploaded_files',      'U') IS NOT NULL DROP TABLE dbo.uploaded_files;

-- new v3 tables (safe re-run)
IF OBJECT_ID('dbo.voice_log',           'U') IS NOT NULL DROP TABLE dbo.voice_log;
IF OBJECT_ID('dbo.chat_log',            'U') IS NOT NULL DROP TABLE dbo.chat_log;
IF OBJECT_ID('dbo.image_files',         'U') IS NOT NULL DROP TABLE dbo.image_files;
IF OBJECT_ID('dbo.document_files',      'U') IS NOT NULL DROP TABLE dbo.document_files;
IF OBJECT_ID('dbo.structured_files',    'U') IS NOT NULL DROP TABLE dbo.structured_files;
IF OBJECT_ID('dbo.query_cache',         'U') IS NOT NULL DROP TABLE dbo.query_cache;
IF OBJECT_ID('dbo.files',               'U') IS NOT NULL DROP TABLE dbo.files;
IF OBJECT_ID('dbo.app_users',           'U') IS NOT NULL DROP TABLE dbo.app_users;

-- old views
IF OBJECT_ID('dbo.v_session_list',   'V') IS NOT NULL DROP VIEW dbo.v_session_list;
IF OBJECT_ID('dbo.v_cache_dashboard','V') IS NOT NULL DROP VIEW dbo.v_cache_dashboard;
IF OBJECT_ID('dbo.v_voice_history',  'V') IS NOT NULL DROP VIEW dbo.v_voice_history;
IF OBJECT_ID('dbo.v_sessions',       'V') IS NOT NULL DROP VIEW dbo.v_sessions;
IF OBJECT_ID('dbo.v_cache_stats',    'V') IS NOT NULL DROP VIEW dbo.v_cache_stats;
IF OBJECT_ID('dbo.v_files',          'V') IS NOT NULL DROP VIEW dbo.v_files;

GO
PRINT '[v3] All old tables/views dropped.';
GO


-- =============================================================================
-- TABLE 1 : dbo.app_users
-- Auth, roles, last-login tracking
-- =============================================================================
CREATE TABLE dbo.app_users (
    id            INT           IDENTITY(1,1) PRIMARY KEY,
    username      NVARCHAR(200) NOT NULL UNIQUE,        -- login email
    password_hash NVARCHAR(64)  NOT NULL,               -- SHA-256 hex
    role          NVARCHAR(20)  NOT NULL DEFAULT 'Analyst'
                  CONSTRAINT chk_au_role CHECK (role IN ('Admin','Analyst','Viewer')),
    full_name     NVARCHAR(200) NULL,
    last_login    DATETIME      NULL,
    created_at    DATETIME      NOT NULL DEFAULT GETDATE()
);
CREATE INDEX IX_au_username ON dbo.app_users (username);

GO
PRINT '[v3] app_users created.';
GO


-- =============================================================================
-- TABLE 2 : dbo.query_cache
-- Unified cache for SQL queries + file analysis prompts
--
-- hit_count  = times served FROM cache (no AI call)
-- run_count  = times AI actually executed this query
-- Timing breakdown:
--   first_exec_ms    = original AI + SQL time on first run
--   cache_lookup_ms  = time to find match in this table
--   sql_rerun_ms     = SQL re-execution time on cache serve
--   cached_exec_ms   = cache_lookup_ms + sql_rerun_ms (total user wait on hit)
-- =============================================================================
CREATE TABLE dbo.query_cache (
    id               INT           IDENTITY(1,1) PRIMARY KEY,

    -- discriminator
    cache_type       NVARCHAR(10)  NOT NULL
                     CONSTRAINT chk_qc_type CHECK (cache_type IN ('sql','file')),

    -- lookup keys
    prompt_hash      NVARCHAR(64)  NOT NULL,            -- SHA-256 of normalised question
    provider         NVARCHAR(100) NULL,
    model            NVARCHAR(100) NULL,
    user_question    NVARCHAR(MAX) NOT NULL,

    -- SQL-only  (NULL for file cache)
    sql_query        NVARCHAR(MAX) NULL,
    raw_sql          NVARCHAR(MAX) NULL,
    embedding        NVARCHAR(MAX) NULL,                -- JSON float[] for cosine similarity

    -- File-only  (NULL for SQL cache)
    file_id          BIGINT        NULL,                -- FK → files.id
    chart_data       NVARCHAR(MAX) NULL,                -- JSON {columns, rows}

    -- Shared result
    analysis         NVARCHAR(MAX) NULL,

    -- Counters
    hit_count        INT           NOT NULL DEFAULT 0,
    run_count        INT           NOT NULL DEFAULT 1,

    -- Timing (all 4 stored separately)
    first_exec_ms    FLOAT         NULL,
    cache_lookup_ms  FLOAT         NULL,
    sql_rerun_ms     FLOAT         NULL,
    cached_exec_ms   FLOAT         NULL,                -- = lookup + rerun

    created_at       DATETIME      NOT NULL DEFAULT GETDATE(),
    last_accessed    DATETIME      NULL
);

CREATE UNIQUE INDEX UX_qc_sql
    ON dbo.query_cache (prompt_hash, provider, model)
    WHERE cache_type = 'sql';

CREATE UNIQUE INDEX UX_qc_file
    ON dbo.query_cache (file_id, prompt_hash)
    WHERE cache_type = 'file' AND file_id IS NOT NULL;

CREATE INDEX IX_qc_embed
    ON dbo.query_cache (provider, model, cache_type)
    WHERE embedding IS NOT NULL;

CREATE INDEX IX_qc_hits
    ON dbo.query_cache (cache_type, hit_count DESC, last_accessed DESC);

GO
PRINT '[v3] query_cache created.';
GO


-- =============================================================================
-- TABLE 3 : dbo.chat_log
-- Unified chat history + audit in one table.
-- Sessions are identified by session_key (UUID string) — no separate table.
-- execution_status + input_source replace ai_query_audit entirely.
-- =============================================================================
CREATE TABLE dbo.chat_log (
    id               BIGINT        IDENTITY(1,1) PRIMARY KEY,

    -- session  (GROUP BY session_key replaces chat_sessions)
    session_key      NVARCHAR(36)  NOT NULL,            -- uuid4 string
    session_title    NVARCHAR(200) NULL,                -- set from first question

    -- who
    user_id          INT           NOT NULL,
    user_email       NVARCHAR(200) NOT NULL,

    -- what
    question         NVARCHAR(MAX) NOT NULL,
    input_source     NVARCHAR(20)  NOT NULL DEFAULT 'keyboard'
                     CONSTRAINT chk_cl_input
                     CHECK (input_source IN ('keyboard','voice','quick_prompt','file')),

    -- result
    sql_query        NVARCHAR(MAX) NULL,
    analysis         NVARCHAR(MAX) NULL,
    row_count        INT           NULL,
    columns_json     NVARCHAR(MAX) NULL,

    -- cache link
    cache_id         INT           NULL,                -- FK → query_cache.id
    source           NVARCHAR(10)  NULL
                     CONSTRAINT chk_cl_source
                     CHECK (source IN ('cache','model',NULL)),

    -- audit
    execution_status NVARCHAR(10)  NOT NULL DEFAULT 'SUCCESS'
                     CONSTRAINT chk_cl_status
                     CHECK (execution_status IN ('SUCCESS','FAILURE')),
    error            NVARCHAR(MAX) NULL,

    -- provider
    provider         NVARCHAR(100) NULL,
    model            NVARCHAR(100) NULL,
    exec_ms          FLOAT         NULL,
    hit_count        INT           NOT NULL DEFAULT 1,

    created_at       DATETIME      NOT NULL DEFAULT GETDATE()
);

CREATE INDEX IX_cl_user_session ON dbo.chat_log (user_id, session_key, created_at DESC);
CREATE INDEX IX_cl_session      ON dbo.chat_log (session_key, created_at ASC);
CREATE INDEX IX_cl_status       ON dbo.chat_log (execution_status, created_at DESC);
CREATE INDEX IX_cl_input        ON dbo.chat_log (input_source, created_at DESC);

GO
PRINT '[v3] chat_log created.';
GO


-- =============================================================================
-- TABLE 4 : dbo.files  (base / parent)
-- Common metadata for all uploaded files.
-- Child tables hold category-specific payload.
-- file_type is the EXACT extension — constrained to all 18 supported formats.
-- =============================================================================
CREATE TABLE dbo.files (
    id           BIGINT        IDENTITY(1,1) PRIMARY KEY,
    user_id      INT           NOT NULL,
    file_hash    NVARCHAR(64)  NOT NULL,               -- SHA-256 (+ ::sheet for Excel)
    file_name    NVARCHAR(255) NOT NULL,
    file_size    BIGINT        NOT NULL,

    -- exact format stored
    file_type    NVARCHAR(10)  NOT NULL
                 CONSTRAINT chk_f_type CHECK (file_type IN (
                     'csv','xlsx','xls','json','tsv','xml',          -- Structured (6)
                     'pdf','docx','doc','pptx','ppt','txt',          -- Documents  (6)
                     'png','jpg','jpeg','webp','bmp','tiff'          -- Images/OCR (6+)
                 )),

    -- broad category — drives which child table to use
    category     NVARCHAR(12)  NOT NULL
                 CONSTRAINT chk_f_cat CHECK (category IN ('structured','document','image_ocr')),

    sheet_name   NVARCHAR(255) NULL,                   -- Excel sheet (NULL otherwise)
    uploaded_at  DATETIME      NOT NULL DEFAULT GETDATE(),
    last_used    DATETIME      NULL,

    CONSTRAINT UQ_user_file UNIQUE (user_id, file_hash)
);

CREATE INDEX IX_f_user     ON dbo.files (user_id, last_used DESC);
CREATE INDEX IX_f_category ON dbo.files (user_id, category);

GO
PRINT '[v3] files (base) created.';
GO


-- =============================================================================
-- TABLE 5 : dbo.structured_files
-- CSV, XLSX, XLS, JSON, TSV, XML — tabular data
-- =============================================================================
CREATE TABLE dbo.structured_files (
    file_id      BIGINT        PRIMARY KEY,             -- 1:1 with files.id
    row_count    INT           NULL,
    col_count    INT           NULL,
    columns_json NVARCHAR(MAX) NULL,                    -- JSON string[] column names
    data_json    NVARCHAR(MAX) NULL,                    -- full rows as JSON (≤ 8 MB)

    CONSTRAINT FK_sf FOREIGN KEY (file_id)
        REFERENCES dbo.files(id) ON DELETE CASCADE
);

GO
PRINT '[v3] structured_files created.';
GO


-- =============================================================================
-- TABLE 6 : dbo.document_files
-- PDF, DOCX, DOC, PPTX, PPT, TXT — text / document data
-- =============================================================================
CREATE TABLE dbo.document_files (
    file_id        BIGINT        PRIMARY KEY,
    page_count     INT           NULL,
    word_count     INT           NULL,
    extracted_text NVARCHAR(MAX) NULL,                  -- full text for AI context

    CONSTRAINT FK_df FOREIGN KEY (file_id)
        REFERENCES dbo.files(id) ON DELETE CASCADE
);

GO
PRINT '[v3] document_files created.';
GO


-- =============================================================================
-- TABLE 7 : dbo.image_files
-- PNG, JPG, WEBP, BMP, TIFF, Scanned PDF — OCR / image data
-- =============================================================================
CREATE TABLE dbo.image_files (
    file_id         BIGINT        PRIMARY KEY,
    width_px        INT           NULL,
    height_px       INT           NULL,
    ocr_text        NVARCHAR(MAX) NULL,                 -- OCR extracted text
    ocr_confidence  FLOAT         NULL,                 -- 0.0 – 1.0
    is_scanned_pdf  BIT           NOT NULL DEFAULT 0,   -- 1 = scanned PDF

    CONSTRAINT FK_if FOREIGN KEY (file_id)
        REFERENCES dbo.files(id) ON DELETE CASCADE
);

GO
PRINT '[v3] image_files created.';
GO


-- =============================================================================
-- TABLE 8 : dbo.voice_log
-- Merged voice_transcripts + voice_cache
-- audio_hash NULL  → browser Web Speech API (no file stored)
-- audio_hash SET   → Whisper (audio file on disk)
-- hit_count        → fuzzy-match dedup (≥85%) increments instead of new row
-- expires_at NULL  → permanent history row
-- expires_at SET   → cache entry with TTL
-- =============================================================================
CREATE TABLE dbo.voice_log (
    id          INT           IDENTITY(1,1) PRIMARY KEY,
    user_id     INT           NULL,
    user_email  NVARCHAR(200) NOT NULL,

    -- Whisper audio identity (NULL for browser speech)
    audio_hash  NVARCHAR(64)  NULL,                     -- SHA-256 of raw .webm bytes
    file_path   NVARCHAR(512) NULL,                     -- path to cached .webm

    -- Transcript
    raw_text    NVARCHAR(MAX) NOT NULL,                 -- exact Whisper/browser output
    clean_text  NVARCHAR(MAX) NOT NULL,                 -- after SQL keyword grammar fixes

    -- Language
    language    NVARCHAR(10)  NULL,
    lang_prob   FLOAT         NULL,                     -- 0.0 – 1.0

    -- Counters + timing
    hit_count   INT           NOT NULL DEFAULT 1,       -- fuzzy dedup count
    latency_ms  FLOAT         NULL,

    -- Cache TTL (NULL = permanent history)
    expires_at  DATETIME      NULL,
    created_at  DATETIME      NOT NULL DEFAULT GETDATE(),
    last_hit_at DATETIME      NULL
);

-- audio_hash must be unique where set (SQL Server treats NULLs as distinct)
CREATE UNIQUE INDEX UX_vl_hash ON dbo.voice_log (audio_hash)
    WHERE audio_hash IS NOT NULL;

CREATE INDEX IX_vl_user   ON dbo.voice_log (user_email, created_at DESC);
CREATE INDEX IX_vl_expiry ON dbo.voice_log (expires_at) WHERE expires_at IS NOT NULL;

GO
PRINT '[v3] voice_log created.';
GO


-- =============================================================================
-- FOREIGN KEY CONSTRAINTS
-- =============================================================================
ALTER TABLE dbo.query_cache ADD CONSTRAINT FK_qc_file
    FOREIGN KEY (file_id) REFERENCES dbo.files(id) ON DELETE SET NULL;

ALTER TABLE dbo.chat_log ADD CONSTRAINT FK_cl_user
    FOREIGN KEY (user_id) REFERENCES dbo.app_users(id);

ALTER TABLE dbo.chat_log ADD CONSTRAINT FK_cl_cache
    FOREIGN KEY (cache_id) REFERENCES dbo.query_cache(id) ON DELETE SET NULL;

ALTER TABLE dbo.files ADD CONSTRAINT FK_f_user
    FOREIGN KEY (user_id) REFERENCES dbo.app_users(id);

ALTER TABLE dbo.voice_log ADD CONSTRAINT FK_vl_user
    FOREIGN KEY (user_id) REFERENCES dbo.app_users(id) ON DELETE SET NULL;

GO
PRINT '[v3] Foreign keys applied.';
GO


-- =============================================================================
-- VIEWS
-- =============================================================================

-- Session list  (replaces chat_sessions table entirely)
CREATE OR ALTER VIEW dbo.v_sessions AS
SELECT
    user_id,
    user_email,
    session_key,
    MIN(session_title)                                               AS title,
    MIN(created_at)                                                  AS created_at,
    MAX(created_at)                                                  AS updated_at,
    COUNT(*)                                                         AS message_count,
    SUM(CASE WHEN execution_status = 'FAILURE' THEN 1 ELSE 0 END)   AS error_count
FROM dbo.chat_log
GROUP BY user_id, user_email, session_key;
GO

-- Cache dashboard  (replaces UNION ALL across two old tables)
CREATE OR ALTER VIEW dbo.v_cache_stats AS
SELECT
    id,
    cache_type,
    user_question,
    provider,
    model,
    hit_count,
    run_count,
    ROUND(first_exec_ms,   0)   AS first_exec_ms,
    ROUND(cached_exec_ms,  1)   AS cached_exec_ms,
    ROUND(cache_lookup_ms, 1)   AS cache_lookup_ms,
    ROUND(sql_rerun_ms,    1)   AS sql_rerun_ms,
    CASE
        WHEN cached_exec_ms > 0 AND first_exec_ms > 0
        THEN ROUND(first_exec_ms / cached_exec_ms, 1)
        ELSE NULL
    END                         AS speedup_x,
    created_at,
    last_accessed
FROM dbo.query_cache;
GO

-- Unified file view  (joins base + all 3 child tables)
CREATE OR ALTER VIEW dbo.v_files AS
SELECT
    f.id,
    f.user_id,
    f.file_name,
    f.file_type,
    f.category,
    f.file_size,
    f.sheet_name,
    f.uploaded_at,
    f.last_used,
    sf.row_count,
    sf.col_count,
    sf.columns_json,
    df.page_count,
    df.word_count,
    img.width_px,
    img.height_px,
    img.ocr_confidence,
    img.is_scanned_pdf
FROM dbo.files f
LEFT JOIN dbo.structured_files sf  ON sf.file_id = f.id
LEFT JOIN dbo.document_files   df  ON df.file_id = f.id
LEFT JOIN dbo.image_files      img ON img.file_id = f.id;
GO

PRINT '[v3] Views created.';
GO


-- =============================================================================
-- VERIFY: show table + column counts
-- =============================================================================
SELECT
    t.TABLE_NAME,
    COUNT(c.COLUMN_NAME) AS column_count
FROM INFORMATION_SCHEMA.TABLES  t
JOIN INFORMATION_SCHEMA.COLUMNS c
    ON c.TABLE_NAME  = t.TABLE_NAME
   AND c.TABLE_SCHEMA = t.TABLE_SCHEMA
WHERE t.TABLE_SCHEMA = 'dbo'
  AND t.TABLE_NAME IN (
      'app_users','query_cache','chat_log',
      'files','structured_files','document_files','image_files',
      'voice_log'
  )
  AND t.TABLE_TYPE = 'BASE TABLE'
GROUP BY t.TABLE_NAME
ORDER BY t.TABLE_NAME;
GO

PRINT '=========================================================';
PRINT ' Schema v3 complete.  8 tables + 3 views ready.         ';
PRINT '=========================================================';
GO
