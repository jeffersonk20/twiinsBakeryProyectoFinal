import sys, os
sys.path.insert(0, os.path.abspath('.'))
from app import obtener_conexion
conn = obtener_conexion()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT id_pago, monto, fecha_pago, fecha_creacion FROM PAGO WHERE estado='PAGADO'")
print("=== PAGOS ===")
for p in cur.fetchall():
    print(p)

cur.execute("SELECT id_movimiento, tipo, monto, concepto, fecha FROM MOVIMIENTO_FINANCIERO")
print("=== MOVIMIENTOS ===")
for m in cur.fetchall():
    print(m)
conn.close()
