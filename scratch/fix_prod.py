import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from app import obtener_conexion

conn = obtener_conexion()
cur = conn.cursor()
cur.execute("UPDATE PRODUCTO SET disponible = 1, en_vitrina = 1, numero_porciones = 8 WHERE id_producto = 9")
conn.commit()
print("Producto 9 actualizado a disponible=1, porciones=8")
