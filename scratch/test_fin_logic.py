import sys
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
sys.path.insert(0, os.path.abspath('.'))
from app import obtener_conexion

conn = obtener_conexion()
cur = conn.cursor(dictionary=True)

# 1. Consultar todos los pagos PAGADOS
cur.execute("""
    SELECT p.id_pago, p.id_reserva, p.monto, p.metodo_pago, 
           COALESCE(p.fecha_pago, p.fecha_creacion) AS fecha,
           r.codigo, r.nombre_cliente, r.estado AS estado_reserva,
           r.total, r.anticipo_requerido, r.monto_pagado,
           p.referencia
    FROM PAGO p
    JOIN RESERVA r ON r.id_reserva = p.id_reserva
    WHERE p.estado = 'PAGADO' AND p.monto > 0
    ORDER BY fecha DESC, p.id_pago DESC
""")
pagos = cur.fetchall()

# 2. Consultar movimientos manuales
cur.execute("""
    SELECT id_movimiento, tipo, monto, concepto, categoria, metodo_pago, fecha, notas
    FROM MOVIMIENTO_FINANCIERO
    ORDER BY fecha DESC, id_movimiento DESC
""")
movimientos_manuales = cur.fetchall()

print(f"Pagos: {len(pagos)}, Manuales: {len(movimientos_manuales)}")

total_reservas = sum(Decimal(str(p['monto'])) for p in pagos)
total_manual_ingreso = sum(Decimal(str(m['monto'])) for m in movimientos_manuales if m['tipo'] == 'INGRESO')
total_manual_resta = sum(Decimal(str(m['monto'])) for m in movimientos_manuales if m['tipo'] == 'RESTA')
total_neto = total_reservas + total_manual_ingreso - total_manual_resta

print(f"Total Reservas: ${total_reservas}")
print(f"Total Manual Ingresos: ${total_manual_ingreso}")
print(f"Total Manual Restas: ${total_manual_resta}")
print(f"Total Neto: ${total_neto}")
