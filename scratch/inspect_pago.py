import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from app import obtener_conexion

conn = obtener_conexion()
cur = conn.cursor(dictionary=True)

cur.execute("PRAGMA table_info(PAGO)")
print("COLUMNAS PAGO:")
for col in cur.fetchall():
    print(col)

cur.execute("SELECT * FROM PAGO LIMIT 5")
print("DATOS PAGO:")
for row in cur.fetchall():
    print(row)

cur.execute("PRAGMA table_info(RESERVA)")
print("COLUMNAS RESERVA:")
for col in cur.fetchall():
    print(col)
