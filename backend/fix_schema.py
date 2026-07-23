import sys
import os

sys.path.insert(0, os.path.abspath("backend"))

from app_core import get_auth_engine
from sqlalchemy import text

engine = get_auth_engine()
with engine.begin() as conn:
    print("Altering dbo.files...")
    try:
        conn.execute(text("ALTER TABLE dbo.files ALTER COLUMN file_hash NVARCHAR(255) NOT NULL"))
        print("Success for dbo.files")
    except Exception as e:
        print(f"Error for dbo.files: {e}")
        
    print("Altering dbo.document_metadata...")
    try:
        conn.execute(text("ALTER TABLE dbo.document_metadata ALTER COLUMN file_hash NVARCHAR(255) NOT NULL"))
        print("Success for dbo.document_metadata")
    except Exception as e:
        print(f"Error for dbo.document_metadata: {e}")
