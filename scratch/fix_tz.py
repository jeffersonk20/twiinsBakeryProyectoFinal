import sys, os
sys.path.insert(0, os.path.abspath('.'))
from app import obtener_conexion
conn = obtener_conexion()
cur = conn.cursor()
cur.execute("UPDATE MOVIMIENTO_FINANCIERO SET fecha = '2026-11-24 20:23:45' WHERE id_movimiento = 1")
conn.commit()
print("Updated id_movimiento 1 date to 2026-11-24 successfully.")
conn.close()
