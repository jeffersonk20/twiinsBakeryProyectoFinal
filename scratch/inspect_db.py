import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from app import obtener_conexion

conn = obtener_conexion()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT id_reserva, codigo, fecha_reserva, fecha_retiro, estado FROM RESERVA")
rows = cur.fetchall()
print("RESERVAS:")
for r in rows:
    print(r)

cur.execute("SELECT DATE('now') as now_utc, DATE('now', 'localtime') as now_local")
print("SQLITE DATES:", cur.fetchall())

cur.execute("SELECT id_producto, nombre, disponible FROM PRODUCTO")
prods = cur.fetchall()
print("PRODUCTOS:")
for p in prods:
    print(p)
