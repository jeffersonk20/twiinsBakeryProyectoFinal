import sys
import os
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.abspath('.'))
from app import obtener_conexion

conn = obtener_conexion()
cur = conn.cursor(dictionary=True)

# 1. Pagos de reservas
cur.execute("""
    SELECT p.id_pago, p.id_reserva, p.monto, p.metodo_pago, p.fecha_pago, p.fecha_creacion,
           r.codigo, r.nombre_cliente, r.estado AS estado_reserva, r.total, r.anticipo_requerido, r.monto_pagado
    FROM PAGO p
    JOIN RESERVA r ON r.id_reserva = p.id_reserva
    WHERE p.estado = 'PAGADO'
    ORDER BY p.id_pago DESC
""")
pagos = cur.fetchall()
print(f"Total pagos encontrados: {len(pagos)}")
for p in pagos:
    print(p)

# 2. Insertar movimiento manual de prueba
cur.execute("""
    INSERT INTO MOVIMIENTO_FINANCIERO (tipo, monto, concepto, categoria, metodo_pago)
    VALUES ('INGRESO', 15.00, 'Venta directa en mostrador: 3 cafés y 2 porciones', 'VENTA_DIRECTA', 'EFECTIVO')
""")
conn.commit()

cur.execute("SELECT * FROM MOVIMIENTO_FINANCIERO")
movs = cur.fetchall()
print("Movimientos manuales:", movs)
