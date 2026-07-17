import json
from sqlalchemy import text
from ..models.standard_document import StandardDocument


class MetadataRepository:
    """
    The platform control center.
    Stores full lineage and processing metadata for every ingested document.
    The SQL Agent reads from this to discover available tables and their schemas.
    """

    def ensure_table(self, engine):
        """Create dbo.document_metadata if it doesn't exist."""
        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    IF NOT EXISTS (
                        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_NAME = 'document_metadata' AND TABLE_SCHEMA = 'dbo'
                    )
                    CREATE TABLE dbo.document_metadata (
                        id                 BIGINT IDENTITY(1,1) PRIMARY KEY,
                        user_id            INT           NOT NULL,
                        file_hash          NVARCHAR(64)  NOT NULL,
                        file_name          NVARCHAR(500) NOT NULL,
                        file_size          BIGINT        NULL,
                        technical_type     NVARCHAR(50)  NULL,
                        business_type      NVARCHAR(50)  NULL,
                        extraction_method  NVARCHAR(100) NULL,
                        parser_used        NVARCHAR(100) NULL,
                        ocr_used           BIT           DEFAULT 0,
                        llm_used           BIT           DEFAULT 0,
                        confidence         FLOAT         NULL,
                        policy_action      NVARCHAR(50)  NULL,
                        flagged            BIT           DEFAULT 0,
                        flag_reason        NVARCHAR(MAX) NULL,
                        row_count          INT           NULL,
                        col_count          INT           NULL,
                        page_count         INT           NULL,
                        sql_table_name     NVARCHAR(200) NULL,
                        columns_json       NVARCHAR(MAX) NULL,
                        lineage_json       NVARCHAR(MAX) NULL,
                        business_violations NVARCHAR(MAX) NULL,
                        processing_time_ms FLOAT         NULL,
                        status             NVARCHAR(50)  NOT NULL DEFAULT 'completed',
                        uploaded_at        DATETIME      NOT NULL DEFAULT GETDATE(),
                        uploaded_files_id  BIGINT        NULL
                    )
                """))
        except Exception as e:
            print(f"[MetadataRepository] Table creation warning: {e}")

    def register(
        self,
        engine,
        doc: StandardDocument,
        user_id: int,
        file_hash: str,
        file_name: str,
        file_size: int,
        sql_table_name: str,
        uploaded_files_id: int = None,
    ) -> int:
        """
        Store full document metadata and lineage.
        Returns the inserted metadata record ID.
        """
        self.ensure_table(engine)

        try:
            with engine.begin() as conn:
                result = conn.execute(text("""
                    INSERT INTO dbo.document_metadata (
                        user_id, file_hash, file_name, file_size,
                        technical_type, business_type, extraction_method,
                        parser_used, ocr_used, llm_used,
                        confidence, policy_action,
                        flagged, flag_reason,
                        row_count, col_count, page_count,
                        sql_table_name, columns_json, lineage_json,
                        business_violations, processing_time_ms,
                        status, uploaded_files_id
                    )
                    OUTPUT INSERTED.id
                    VALUES (
                        :user_id, :file_hash, :file_name, :file_size,
                        :technical_type, :business_type, :extraction_method,
                        :parser_used, :ocr_used, :llm_used,
                        :confidence, :policy_action,
                        :flagged, :flag_reason,
                        :row_count, :col_count, :page_count,
                        :sql_table_name, :columns_json, :lineage_json,
                        :business_violations, :processing_time_ms,
                        :status, :uploaded_files_id
                    )
                """), {
                    "user_id":             user_id,
                    "file_hash":           file_hash,
                    "file_name":           file_name,
                    "file_size":           file_size,
                    "technical_type":      doc.technical_file_type.value if doc.technical_file_type else None,
                    "business_type":       doc.business_type.value if doc.business_type else None,
                    "extraction_method":   doc.extraction_strategy.value if doc.extraction_strategy else None,
                    "parser_used":         doc.parser_used,
                    "ocr_used":            1 if doc.ocr_used else 0,
                    "llm_used":            1 if doc.llm_used else 0,
                    "confidence":          doc.confidence,
                    "policy_action":       doc.policy_action.value if doc.policy_action else None,
                    "flagged":             1 if doc.flagged else 0,
                    "flag_reason":         doc.flag_reason,
                    "row_count":           doc.row_count,
                    "col_count":           doc.col_count,
                    "page_count":          doc.page_count,
                    "sql_table_name":      sql_table_name,
                    "columns_json":        json.dumps(doc.columns),
                    "lineage_json":        json.dumps(doc.lineage) if doc.lineage else None,
                    "business_violations": json.dumps(doc.business_rule_violations),
                    "processing_time_ms":  doc.processing_time_ms,
                    "status":              "flagged" if doc.flagged else "completed",
                    "uploaded_files_id":   uploaded_files_id,
                })
                meta_id = result.fetchone()[0]
                print(f"[MetadataRepository] Registered doc metadata id={meta_id}")
                return meta_id
        except Exception as e:
            print(f"[MetadataRepository] Register error: {e}")
            return None

    def get_user_tables(self, engine, user_id: int) -> list[dict]:
        """
        Returns all tables created for a user.
        Used by the SQL Agent to discover available data.
        """
        self.ensure_table(engine)
        try:
            with engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT
                        id, file_name, business_type, sql_table_name,
                        columns_json, row_count, col_count,
                        confidence, flagged, uploaded_at, uploaded_files_id
                    FROM dbo.document_metadata
                    WHERE user_id = :uid AND status != 'rejected'
                      AND sql_table_name IS NOT NULL AND sql_table_name != ''
                    ORDER BY uploaded_at DESC
                """), {"uid": user_id}).fetchall()
            return [
                {
                    "id":           r[0],
                    "file_name":    r[1],
                    "business_type": r[2],
                    "table_name":   r[3],
                    "columns":      json.loads(r[4]) if r[4] else [],
                    "row_count":    r[5],
                    "col_count":    r[6],
                    "confidence":   r[7],
                    "flagged":      bool(r[8]),
                    "uploaded_at":  str(r[9]),
                    "file_id":      r[10],
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[MetadataRepository] get_user_tables error: {e}")
            return []
