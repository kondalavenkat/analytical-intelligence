import json
import re
from sqlalchemy import text
from ..models.standard_document import StandardDocument


class DynamicSQLEngine:
    """
    Creates or alters SQL tables based on the StandardDocument schema.
    Runs BEFORE SQL Agent so the Agent queries pre-existing stored data.

    Responsibilities:
    - CREATE TABLE if it doesn't exist
    - ALTER TABLE to add new columns if the schema expands (schema drift)
    - INSERT extracted rows into the table
    - Return the table name for metadata registration
    """

    # SQL type mapping from pandas dtype
    DTYPE_MAP = {
        "int64":   "BIGINT",
        "int32":   "INT",
        "float64": "FLOAT",
        "float32": "FLOAT",
        "bool":    "BIT",
        "object":  "NVARCHAR(MAX)",
        "datetime64[ns]": "DATETIME",
    }

    def ingest(self, engine, doc: StandardDocument, user_id: int, file_hash: str) -> str:
        """
        Main entry point. Ensures table exists, handles schema drift, inserts data.
        Returns the table name.
        """
        if doc.df is None or doc.df.empty:
            print("[DynamicSQLEngine] No DataFrame to ingest.")
            return ""

        table_name = self._generate_table_name(doc, user_id, file_hash)

        if self._table_exists(engine, table_name):
            self._handle_schema_drift(engine, table_name, doc)
        else:
            self._create_table(engine, table_name, doc)

        self._insert_data(engine, table_name, doc)
        print(f"[DynamicSQLEngine] Ingested {doc.row_count} rows into [{table_name}]")
        return table_name

    def _generate_table_name(self, doc: StandardDocument, user_id: int, file_hash: str) -> str:
        """Generate a safe, deterministic table name."""
        subtype = (doc.business_type.value if doc.business_type else "generic")
        # First 8 chars of hash for uniqueness
        short_hash = file_hash[:8] if file_hash else "00000000"
        name = f"ui_{subtype}_{user_id}_{short_hash}"
        # Sanitize: only alphanumeric + underscore
        name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        return name[:128]  # SQL Server 128 char limit

    def _table_exists(self, engine, table_name: str) -> bool:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = :name
            """), {"name": table_name}).fetchone()
        return result is not None

    def _get_column_defs(self, doc: StandardDocument) -> list[tuple[str, str]]:
        """Return (sanitized_col_name, sql_type) pairs."""
        col_defs = []
        for col in doc.df.columns:
            safe_col = re.sub(r"[^a-zA-Z0-9_]", "_", str(col).strip())
            dtype    = str(doc.df[col].dtype)
            sql_type = self.DTYPE_MAP.get(dtype, "NVARCHAR(MAX)")
            col_defs.append((safe_col, sql_type))
        return col_defs

    def _create_table(self, engine, table_name: str, doc: StandardDocument):
        col_defs = self._get_column_defs(doc)
        cols_sql  = ",\n    ".join(f"[{c}] {t} NULL" for c, t in col_defs)
        ddl = f"""
            CREATE TABLE dbo.[{table_name}] (
                _row_id BIGINT IDENTITY(1,1) PRIMARY KEY,
                {cols_sql}
            )
        """
        with engine.begin() as conn:
            conn.execute(text(ddl))
        print(f"[DynamicSQLEngine] Created table [{table_name}]")

    def _handle_schema_drift(self, engine, table_name: str, doc: StandardDocument):
        """Add new columns that exist in doc but not in the existing table."""
        with engine.connect() as conn:
            existing = {
                row[0].lower()
                for row in conn.execute(text("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=:name
                """), {"name": table_name}).fetchall()
            }

        for safe_col, sql_type in self._get_column_defs(doc):
            if safe_col.lower() not in existing:
                with engine.begin() as conn:
                    conn.execute(text(
                        f"ALTER TABLE dbo.[{table_name}] ADD [{safe_col}] {sql_type} NULL"
                    ))
                print(f"[DynamicSQLEngine] Schema drift — added [{safe_col}] to [{table_name}]")

    def _insert_data(self, engine, table_name: str, doc: StandardDocument):
        """Bulk insert rows from the DataFrame."""
        df = doc.df.fillna("").astype(str)
        col_defs    = self._get_column_defs(doc)
        col_names   = ", ".join(f"[{c}]" for c, _ in col_defs)
        placeholders = ", ".join(f":{c}" for c, _ in col_defs)

        rows = []
        for _, row in df.iterrows():
            row_dict = {}
            for (safe_col, _), orig_col in zip(col_defs, doc.df.columns):
                val = row.get(orig_col, "")
                row_dict[safe_col] = val if val != "" else None
            rows.append(row_dict)

        if not rows:
            return

        sql = f"INSERT INTO dbo.[{table_name}] ({col_names}) VALUES ({placeholders})"
        with engine.begin() as conn:
            conn.execute(text(sql), rows)
