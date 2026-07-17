import sqlalchemy.engine.url as url
import sys

u1 = url.make_url('mssql+pyodbc://QFTCHNLPT-04800/AdventureWorks2025?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes')
print(f"NO @: user={u1.username}, host={u1.host}, db={u1.database}")

u2 = url.make_url('mssql+pyodbc://@QFTCHNLPT-04800/AdventureWorks2025?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes')
print(f"WITH @: user={u2.username}, host={u2.host}, db={u2.database}")
