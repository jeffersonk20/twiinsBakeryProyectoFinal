import os

insert_code = '''
@app.route("/api/admin/ingresos", methods=["GET"])
@administrador_requerido
def api_admin_ingresos():
    periodo = request.args.get("periodo", "semana").lower().strip()
    if periodo not in {"hoy", "semana", "mes", "todo"}:
        periodo = "semana"

    hoy = date.today()
    inicio_hoy = datetime.combine(hoy, datetime.min.time())
    inicio_semana = datetime.combine(hoy - timedelta(days=6), datetime.min.time())
    inicio_mes = datetime.combine(hoy.replace(day=1), datetime.min.time())

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT p.id_pago, p.id_reserva, p.monto, p.metodo_pago,
                   COALESCE(p.fecha_pago, p.fecha_creacion) AS fecha,
                   r.codigo, r.nombre_cliente, r.estado AS estado_reserva,
                   r.total, r.anticipo_requerido, r.monto_pagado,
                   p.referencia
            FROM PAGO p
            JOIN RESERVA r ON r.id_reserva = p.id_reserva
            WHERE p.estado = 'PAGADO' AND p.monto > 0
            ORDER BY fecha DESC, p.id_pago DESC
            """
        )
        pagos_raw = cursor.fetchall()

        cursor.execute(
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
            })

        for m in manuales_raw:
            monto = float(m["monto"])
            f = m["fecha"]
            if isinstance(f, str):
                try:
                    dt = datetime.fromisoformat(f.replace("Z", ""))
                except Exception:
                    dt = datetime.strptime(f[:19], "%Y-%m-%d %H:%M:%S")
            else:
                dt = f

            cat = m["categoria"] or ("VENTA_DIRECTA" if m["tipo"] == "INGRESO" else "GASTO")
            etiqueta = "Ingreso manual" if m["tipo"] == "INGRESO" else "Resta / Egreso"

            transacciones_todas.append({
                "id": f"MANUAL-{m['id_movimiento']}",
                "origen": "MANUAL",
                "id_pago": None,
                "id_movimiento": m["id_movimiento"],
                "id_reserva": m["id_reserva"],
                "codigo_reserva": None,
                "cliente": "Administración",
                "concepto": m["concepto"],
                "tipo": m["tipo"],
                "subtipo": cat,
                "subtipo_etiqueta": etiqueta,
                "categoria": cat,
                "metodo_pago": m["metodo_pago"] or "EFECTIVO",
                "fecha_dt": dt,
                "fecha": dt.strftime("%Y-%m-%d %H:%M"),
                "fecha_corta": dt.strftime("%d/%m/%Y"),
                "monto": round(monto, 2),
                "es_editable": True,
                "notas": m["notas"] or "",
            })

        transacciones_todas.sort(key=lambda x: x["fecha_dt"], reverse=True)

        def calc_neto(items):
            ing = sum(x["monto"] for x in items if x["tipo"] == "INGRESO")
            res = sum(x["monto"] for x in items if x["tipo"] == "RESTA")
            return round(ing - res, 2)

        metricas_fijas = {
            "hoy": calc_neto([t for t in transacciones_todas if t["fecha_dt"] >= inicio_hoy]),
            "semana": calc_neto([t for t in transacciones_todas if t["fecha_dt"] >= inicio_semana]),
            "mes": calc_neto([t for t in transacciones_todas if t["fecha_dt"] >= inicio_mes]),
            "total_historico": calc_neto(transacciones_todas),
        }

        if periodo == "hoy":
            filtradas = [t for t in transacciones_todas if t["fecha_dt"] >= inicio_hoy]
        elif periodo == "semana":
            filtradas = [t for t in transacciones_todas if t["fecha_dt"] >= inicio_semana]
        elif periodo == "mes":
            filtradas = [t for t in transacciones_todas if t["fecha_dt"] >= inicio_mes]
        else:
            filtradas = transacciones_todas

        ingresos_res = sum(t["monto"] for t in filtradas if t["tipo"] == "INGRESO" and t["origen"] == "RESERVA")
        ingresos_man = sum(t["monto"] for t in filtradas if t["tipo"] == "INGRESO" and t["origen"] == "MANUAL")
        restas_egresos = sum(t["monto"] for t in filtradas if t["tipo"] == "RESTA")
        ingreso_bruto = round(ingresos_res + ingresos_man, 2)
        ingreso_neto = round(ingreso_bruto - restas_egresos, 2)

        anticipos_m = round(sum(t["monto"] for t in filtradas if t["subtipo"] == "ANTICIPO"), 2)
        anticipos_c = sum(1 for t in filtradas if t["subtipo"] == "ANTICIPO")
        liquidaciones_m = round(sum(t["monto"] for t in filtradas if t["subtipo"] == "LIQUIDACION"), 2)
        liquidaciones_c = sum(1 for t in filtradas if t["subtipo"] == "LIQUIDACION")
        completos_m = round(sum(t["monto"] for t in filtradas if t["subtipo"] == "PAGO_COMPLETO"), 2)
        completos_c = sum(1 for t in filtradas if t["subtipo"] == "PAGO_COMPLETO")
        canceladas_m = round(sum(t["monto"] for t in filtradas if t["subtipo"] == "ANTICIPO_RETENIDO"), 2)
        canceladas_c = sum(1 for t in filtradas if t["subtipo"] == "ANTICIPO_RETENIDO")

        reservas_ids = set(t["id_reserva"] for t in filtradas if t["origen"] == "RESERVA" and t["id_reserva"])
        total_pedidos = len(reservas_ids)
        ticket_medio = round(ingresos_res / total_pedidos, 2) if total_pedidos > 0 else 0.0

        nombres_dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        nombres_meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        puntos_grafica = []

        if periodo == "hoy":
            franjas = [
                (8, 10, "08:00 - 10:00"),
                (10, 12, "10:00 - 12:00"),
                (12, 14, "12:00 - 14:00"),
                (14, 16, "14:00 - 16:00"),
                (16, 18, "16:00 - 18:00"),
                (18, 20, "18:00 - 20:00"),
                (20, 24, "20:00+"),
            ]
            for h_ini, h_fin, label in franjas:
                items_f = [t for t in filtradas if h_ini <= t["fecha_dt"].hour < h_fin]
                ing = sum(t["monto"] for t in items_f if t["tipo"] == "INGRESO")
                res = sum(t["monto"] for t in items_f if t["tipo"] == "RESTA")
                puntos_grafica.append({
                    "label": label,
                    "ingreso": round(ing, 2),
                    "resta": round(res, 2),
                    "neto": round(ing - res, 2),
                    "conteo": len(items_f),
                })
        elif periodo == "semana":
            for offset in range(6, -1, -1):
                dia_target = hoy - timedelta(days=offset)
                items_d = [t for t in transacciones_todas if t["fecha_dt"].date() == dia_target]
                ing = sum(t["monto"] for t in items_d if t["tipo"] == "INGRESO")
                res = sum(t["monto"] for t in items_d if t["tipo"] == "RESTA")
                label = f"{nombres_dias[dia_target.weekday()]} {dia_target.day}"
                puntos_grafica.append({
                    "label": label,
                    "ingreso": round(ing, 2),
                    "resta": round(res, 2),
                    "neto": round(ing - res, 2),
                    "conteo": len(items_d),
                })
        elif periodo == "mes":
            dia_1 = hoy.replace(day=1)
            semanas = [
                (dia_1, dia_1 + timedelta(days=6), "Semana 1"),
                (dia_1 + timedelta(days=7), dia_1 + timedelta(days=13), "Semana 2"),
                (dia_1 + timedelta(days=14), dia_1 + timedelta(days=20), "Semana 3"),
                (dia_1 + timedelta(days=21), hoy + timedelta(days=10), "Semana 4+"),
            ]
            for f_ini, f_fin, label in semanas:
                items_s = [t for t in filtradas if f_ini <= t["fecha_dt"].date() <= f_fin]
                ing = sum(t["monto"] for t in items_s if t["tipo"] == "INGRESO")
                res = sum(t["monto"] for t in items_s if t["tipo"] == "RESTA")
                puntos_grafica.append({
                    "label": label,
                    "ingreso": round(ing, 2),
                    "resta": round(res, 2),
                    "neto": round(ing - res, 2),
                    "conteo": len(items_s),
                })
        else:
            for m_back in range(5, -1, -1):
                year = hoy.year
                month = hoy.month - m_back
                while month <= 0:
                    month += 12
                    year -= 1
                items_m = [t for t in transacciones_todas if t["fecha_dt"].year == year and t["fecha_dt"].month == month]
                ing = sum(t["monto"] for t in items_m if t["tipo"] == "INGRESO")
                res = sum(t["monto"] for t in items_m if t["tipo"] == "RESTA")
                puntos_grafica.append({
                    "label": f"{nombres_meses[month - 1]} {str(year)[2:]}",
                    "ingreso": round(ing, 2),
                    "resta": round(res, 2),
                    "neto": round(ing - res, 2),
                    "conteo": len(items_m),
                })

        for t in filtradas:
            t.pop("fecha_dt", None)

        return jsonify({
            "periodo": periodo,
            "metricas_fijas": metricas_fijas,
            "resumen_periodo": {
                "ingreso_neto": ingreso_neto,
                "ingreso_bruto": ingreso_bruto,
                "ingresos_reservas": round(ingresos_res, 2),
                "ingresos_manuales": round(ingresos_man, 2),
                "restas_egresos": round(restas_egresos, 2),
                "total_pedidos": total_pedidos,
                "ticket_medio": ticket_medio,
                "anticipos_monto": anticipos_m,
                "anticipos_conteo": anticipos_c,
                "liquidaciones_monto": liquidaciones_m,
                "liquidaciones_conteo": liquidaciones_c,
                "pagos_completos_monto": completos_m,
                "pagos_completos_conteo": completos_c,
                "canceladas_monto": canceladas_m,
                "canceladas_conteo": canceladas_c,
                "total_transacciones": len(filtradas),
            },
            "grafica": puntos_grafica,
            "transacciones": filtradas,
        })
    except mysql.connector.Error as error:
        return _error_base_datos(error, "No se pudieron consultar los datos financieros.")
    except Exception:
        app.logger.exception("Error al procesar ingresos financieros.")
        return jsonify({"error": "No se pudieron consultar los ingresos."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/ingresos/movimiento", methods=["POST"])
@administrador_requerido
def api_admin_crear_movimiento():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "Los datos enviados no son válidos."}), 400

    tipo = str(datos.get("tipo", "")).strip().upper()
    if tipo not in {"INGRESO", "RESTA"}:
        return jsonify({"error": "El tipo de movimiento debe ser 'INGRESO' o 'RESTA'."}), 400

    try:
        monto = float(datos.get("monto", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "El monto debe ser un número válido."}), 400

    if monto <= 0 or monto > 100000:
        return jsonify({"error": "El monto debe ser mayor a 0 y menor a $100,000."}), 400

    concepto = str(datos.get("concepto", "")).strip()
    if len(concepto) < 3 or len(concepto) > 200:
        return jsonify({"error": "El concepto debe tener entre 3 y 200 caracteres."}), 400

    categoria = str(datos.get("categoria", "OTRO")).strip().upper()
    metodos_validos = {"EFECTIVO", "TARJETA", "TRANSFERENCIA", "OTRO"}
    metodo_pago = str(datos.get("metodo_pago", "EFECTIVO")).strip().upper()
    if metodo_pago not in metodos_validos:
        metodo_pago = "EFECTIVO"

    notas = str(datos.get("notas", "")).strip()
    if len(notas) > 300:
        notas = notas[:300]

    fecha_str = datos.get("fecha")
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if fecha_str:
        try:
            fecha_dt = datetime.fromisoformat(str(fecha_str).strip())
            fecha_actual = fecha_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    admin_id = session.get("id_admin")

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            """
            INSERT INTO MOVIMIENTO_FINANCIERO (tipo, monto, concepto, categoria, metodo_pago, fecha, id_admin, notas)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (tipo, monto, concepto, categoria, metodo_pago, fecha_actual, admin_id, notas),
        )
        conexion.commit()
        id_nuevo = cursor.lastrowid
        return jsonify({
            "mensaje": f"{'Ingreso' if tipo == 'INGRESO' else 'Resta'} registrado con éxito.",
            "id_movimiento": id_nuevo
        }), 201
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo registrar el movimiento financiero.")
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al registrar movimiento financiero.")
        return jsonify({"error": "No se pudo guardar el movimiento."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/ingresos/movimiento/<int:id_movimiento>", methods=["DELETE"])
@administrador_requerido
def api_admin_eliminar_movimiento(id_movimiento):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            "SELECT id_movimiento, tipo, concepto, monto FROM MOVIMIENTO_FINANCIERO WHERE id_movimiento = %s",
            (id_movimiento,)
        )
        mov = cursor.fetchone()
        if not mov:
            return jsonify({"error": "El movimiento no existe o ya fue eliminado."}), 404

        cursor.execute("DELETE FROM MOVIMIENTO_FINANCIERO WHERE id_movimiento = %s", (id_movimiento,))
        conexion.commit()
        return jsonify({
            "mensaje": f"Movimiento '{mov['concepto']}' (${float(mov['monto']):.2f}) eliminado exitosamente."
        })
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo eliminar el movimiento.")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()
'''

with open('app.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = '@app.route("/api/admin/reservas", methods=["GET"])'
if target in code:
    code = code.replace(target, insert_code + "\n\n" + target, 1)
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print("Insertion successful!")
else:
    print("Target not found!")
