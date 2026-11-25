import sys
import os
import json
from decimal import Decimal
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath('.'))
from app import app, obtener_conexion

# Test registering a RESTA
conn = obtener_conexion()
cur = conn.cursor()
cur.execute("""
    INSERT INTO MOVIMIENTO_FINANCIERO (tipo, monto, concepto, categoria, metodo_pago, fecha, notas)
    VALUES ('RESTA', 24.50, 'Compra de insumos: fresas frescas y chocolate belga', 'INSUMOS', 'EFECTIVO', datetime('now', 'localtime'), 'Factura #102')
""")
conn.commit()
print("Resta de prueba insertada.")

cur.execute("SELECT * FROM MOVIMIENTO_FINANCIERO")
print("Movimientos en BD:", cur.fetchall())
conn.close()
