import os

with open('app.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Update api_admin_ingresos to track returned deposits
old_logic = '''        cursor.execute(
            """
            SELECT id_movimiento, tipo, monto, concepto, categoria, metodo_pago, fecha, notas, id_reserva, id_admin
            FROM MOVIMIENTO_FINANCIERO
            ORDER BY fecha DESC, id_movimiento DESC
            """
        )
        manuales_raw = cursor.fetchall()

        transacciones_todas = []

        for p in pagos_raw:
            monto = float(p["monto"])
            total_res = float(p["total"] or 0)
            anticipo_req = float(p["anticipo_requerido"] or 0)
            estado_res = p["estado_reserva"]

            if estado_res == "CANCELADA":
                subtipo = "ANTICIPO_RETENIDO"
                etiqueta = "Anticipo retenido (Cancelada)"
                categoria = "RESERVA_CANCELADA"
            elif monto >= total_res and total_res > 0:
                subtipo = "PAGO_COMPLETO"
                etiqueta = "Pago completo (100%)"
                categoria = "RESERVA_COMPLETA"
            elif abs(monto - anticipo_req) < 0.05:
                subtipo = "ANTICIPO"
                etiqueta = "Anticipo (50%)"
                categoria = "ANTICIPO_RESERVA"
            else:
                subtipo = "LIQUIDACION"
                etiqueta = "Liquidación de saldo"
                categoria = "LIQUIDACION_RESERVA"

            f = p["fecha"]
            if isinstance(f, str):
                try:
                    dt = datetime.fromisoformat(f.replace("Z", ""))
                except Exception:
                    dt = datetime.strptime(f[:19], "%Y-%m-%d %H:%M:%S")
            else:
                dt = f

            transacciones_todas.append({
                "id": f"PAGO-{p['id_pago']}",
                "origen": "RESERVA",
                "id_pago": p["id_pago"],
                "id_movimiento": None,
                "id_reserva": p["id_reserva"],
                "codigo_reserva": p["codigo"],
                "cliente": p["nombre_cliente"] or "Cliente",
                "concepto": f"Reserva {p['codigo']} ({etiqueta})",
                "tipo": "INGRESO",
                "subtipo": subtipo,
                "subtipo_etiqueta": etiqueta,
                "categoria": categoria,
                "metodo_pago": p["metodo_pago"] or "TARJETA",
                "fecha_dt": dt,
                "fecha": dt.strftime("%Y-%m-%d %H:%M"),
                "fecha_corta": dt.strftime("%d/%m/%Y"),
                "monto": round(monto, 2),
                "es_editable": False,
                "notas": f"Total reserva: ${total_res:.2f}",
            })'''

new_logic = '''        cursor.execute(
            """
            SELECT id_movimiento, tipo, monto, concepto, categoria, metodo_pago, fecha, notas, id_reserva, id_admin
            FROM MOVIMIENTO_FINANCIERO
            ORDER BY fecha DESC, id_movimiento DESC
            """
        )
        manuales_raw = cursor.fetchall()

        # Identificar reservas cuyo anticipo retenido ya fue entregado/devuelto al cliente
        reservas_anticipo_devuelto = set()
        for m in manuales_raw:
            if m["tipo"] == "RESTA" and m.get("id_reserva"):
                reservas_anticipo_devuelto.add(m["id_reserva"])

        transacciones_todas = []

        for p in pagos_raw:
            monto = float(p["monto"])
            total_res = float(p["total"] or 0)
            anticipo_req = float(p["anticipo_requerido"] or 0)
            estado_res = p["estado_reserva"]
            id_res = p["id_reserva"]

            puede_entregar = False
            ya_devuelto = id_res in reservas_anticipo_devuelto

            if estado_res == "CANCELADA":
                subtipo = "ANTICIPO_RETENIDO"
                if ya_devuelto:
                    etiqueta = "Anticipo retenido (Ya entregado)"
                    categoria = "RESERVA_CANCELADA_DEVUELTA"
                else:
                    etiqueta = "Anticipo retenido (Cancelada)"
                    categoria = "RESERVA_CANCELADA"
                    puede_entregar = True
            elif monto >= total_res and total_res > 0:
                subtipo = "PAGO_COMPLETO"
                etiqueta = "Pago completo (100%)"
                categoria = "RESERVA_COMPLETA"
            elif abs(monto - anticipo_req) < 0.05:
                subtipo = "ANTICIPO"
                etiqueta = "Anticipo (50%)"
                categoria = "ANTICIPO_RESERVA"
            else:
                subtipo = "LIQUIDACION"
                etiqueta = "Liquidación de saldo"
                categoria = "LIQUIDACION_RESERVA"

            f = p["fecha"]
            if isinstance(f, str):
                try:
                    dt = datetime.fromisoformat(f.replace("Z", ""))
                except Exception:
                    dt = datetime.strptime(f[:19], "%Y-%m-%d %H:%M:%S")
            else:
                dt = f

            transacciones_todas.append({
                "id": f"PAGO-{p['id_pago']}",
                "origen": "RESERVA",
                "id_pago": p["id_pago"],
                "id_movimiento": None,
                "id_reserva": id_res,
                "codigo_reserva": p["codigo"],
                "cliente": p["nombre_cliente"] or "Cliente",
                "concepto": f"Reserva {p['codigo']} ({etiqueta})",
                "tipo": "INGRESO",
                "subtipo": subtipo,
                "subtipo_etiqueta": etiqueta,
                "categoria": categoria,
                "metodo_pago": p["metodo_pago"] or "TARJETA",
                "fecha_dt": dt,
                "fecha": dt.strftime("%Y-%m-%d %H:%M"),
                "fecha_corta": dt.strftime("%d/%m/%Y"),
                "monto": round(monto, 2),
                "es_editable": False,
                "puede_entregar_anticipo": puede_entregar,
                "anticipo_devuelto": ya_devuelto,
                "notas": f"Total reserva: ${total_res:.2f}",
            })'''

assert old_logic in code, "old_logic not found!"
code = code.replace(old_logic, new_logic, 1)

# 2. Add endpoint api_admin_entregar_anticipo_retenido right after api_admin_eliminar_movimiento
new_endpoint = '''
@app.route("/api/admin/ingresos/entregar-anticipo-retenido", methods=["POST"])
@administrador_requerido
def api_admin_entregar_anticipo_retenido():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "Los datos enviados no son válidos."}), 400

    id_reserva = datos.get("id_reserva")
    try:
        id_reserva = int(id_reserva)
    except (TypeError, ValueError):
        return jsonify({"error": "El ID de reserva no es válido."}), 400

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # 1. Verificar reserva cancelada con pago pagado
        cursor.execute(
            """
            SELECT r.id_reserva, r.codigo, r.nombre_cliente, r.estado,
                   p.id_pago, p.monto, p.metodo_pago
            FROM RESERVA r
            JOIN PAGO p ON p.id_reserva = r.id_reserva
            WHERE r.id_reserva = %s AND r.estado = 'CANCELADA' AND p.estado = 'PAGADO' AND p.monto > 0
            ORDER BY p.id_pago DESC
            LIMIT 1
            """,
            (id_reserva,),
        )
        reserva = cursor.fetchone()
        if not reserva:
            return jsonify({"error": "No se encontró un anticipo retenido pagado para esta reserva."}), 404

        # 2. Verificar que no se haya devuelto ya
        cursor.execute(
            """
            SELECT id_movimiento FROM MOVIMIENTO_FINANCIERO
            WHERE id_reserva = %s AND tipo = 'RESTA'
            LIMIT 1
            """,
            (id_reserva,),
        )
        if cursor.fetchone():
            return jsonify({"error": "El anticipo retenido de esta reserva ya fue registrado como entregado previamente."}), 400

        monto_devolver = float(reserva["monto"])
        concepto = f"Anticipo retenido entregado - Reserva {reserva['codigo']} ({reserva['nombre_cliente']})"
        categoria = "DEVOLUCION_ANTICIPO"
        metodo = reserva["metodo_pago"] or "EFECTIVO"
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        admin_id = session.get("id_admin")
        notas = "Anticipo retenido devuelto / entregado al cliente por la administración."

        cursor.execute(
            """
            INSERT INTO MOVIMIENTO_FINANCIERO (tipo, monto, concepto, categoria, metodo_pago, fecha, id_reserva, id_admin, notas)
            VALUES ('RESTA', %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (monto_devolver, concepto, categoria, metodo, fecha_actual, id_reserva, admin_id, notas),
        )
        conexion.commit()
        id_nuevo = cursor.lastrowid

        return jsonify({
            "mensaje": f"Se registró la entrega del anticipo retenido de ${monto_devolver:.2f} (Reserva {reserva['codigo']}). El valor se restó del sistema.",
            "id_movimiento": id_nuevo,
            "monto": monto_devolver
        }), 201
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo registrar la entrega del anticipo.")
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al registrar entrega de anticipo retenido.")
        return jsonify({"error": "Ocurrió un error al procesar la entrega del anticipo."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()
'''

target_endpoint = '@app.route("/api/admin/reservas", methods=["GET"])'
assert target_endpoint in code, "target_endpoint not found!"
code = code.replace(target_endpoint, new_endpoint + "\n\n" + target_endpoint, 1)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Patch applied successfully!")
