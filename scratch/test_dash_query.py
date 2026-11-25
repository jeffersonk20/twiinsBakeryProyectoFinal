import sys
import os
from datetime import date, timedelta
sys.path.insert(0, os.path.abspath('.'))
from app import obtener_conexion

conn = obtener_conexion()
cur = conn.cursor(dictionary=True)

hoy_str = date.today().isoformat()
hace_6_dias_str = (date.today() - timedelta(days=6)).isoformat()

print("Hoy local:", hoy_str)
print("Hace 6 dias:", hace_6_dias_str)

cur.execute("SELECT COUNT(*) AS total FROM RESERVA WHERE DATE(fecha_reserva) = %s", (hoy_str,))
row_hoy = cur.fetchone()
print("Reservas hoy:", row_hoy["total"] if row_hoy else 0)

cur.execute("SELECT COUNT(*) AS total FROM RESERVA")
row_tot = cur.fetchone()
print("Total reservas:", row_tot["total"] if row_tot else 0)

cur.execute("""
    SELECT DATE(fecha_reserva) AS dia, COUNT(*) AS total
    FROM RESERVA
    WHERE DATE(fecha_reserva) >= %s AND DATE(fecha_reserva) <= %s
    GROUP BY DATE(fecha_reserva)
    ORDER BY dia ASC
""", (hace_6_dias_str, hoy_str))
rows_semana = cur.fetchall()
print("Reservas semana:", rows_semana)
