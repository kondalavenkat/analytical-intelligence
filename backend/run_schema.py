"""
run_schema.py — execute schema_v3.sql against the database
Run: python run_schema.py
"""
from sqlalchemy import create_engine, text
import urllib.parse, sys

params = urllib.parse.quote_plus(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=QFTCHNLPT-04800;DATABASE=AdventureWorks2025;"
    "UID=sa;PWD=Passw0rd@098;TrustServerCertificate=yes;"
)
engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}")

with open("schema_v3.sql", "r", encoding="utf-8") as f:
    sql = f.read()

# Split on GO statements (case-insensitive, any whitespace around)
import re
batches = [b.strip() for b in re.split(r"^\s*GO\s*$", sql, flags=re.MULTILINE | re.IGNORECASE)]
batches = [b for b in batches if b and not b.startswith("--")]

success = errors = 0
for i, batch in enumerate(batches):
    try:
        with engine.begin() as conn:
            conn.execute(text(batch))
        success += 1
    except Exception as e:
        print(f"[batch {i+1}] ⚠  {str(e)[:200]}")
        errors += 1

print(f"\n{'='*50}")
print(f" Schema v3: {success} batches OK, {errors} errors")
print(f"{'='*50}")
sys.exit(0 if errors == 0 else 1)
