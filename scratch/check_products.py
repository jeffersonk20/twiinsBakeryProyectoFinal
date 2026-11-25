import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from app import obtener_conexion

conn = obtener_conexion()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT * FROM PRODUCTO")
rows = cur.fetchall()
print(f"Total productos en DB: {len(rows)}")
for r in rows:
    print(r)
