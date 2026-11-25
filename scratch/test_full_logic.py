import sys
import os
import json
from decimal import Decimal
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath('.'))
from app import app, obtener_conexion

def get_ingresos_data(periodo='semana'):
    hoy = date.today()
    inicio_hoy = datetime.combine(hoy, datetime.min.time())
    inicio_semana = datetime.combine(hoy - timedelta(days=6), datetime.min.time())
    inicio_mes = datetime.combine(hoy.replace(day=1), datetime.min.time())

    conn = obtener_conexion()
    cur = conn.cursor(dictionary=True)

    # 1. Obtener todos los pagos confirmados
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
    pagos_raw = cur.fetchall()

    # 2. Obtener todos los movimientos financieros manuales
    cur.execute("""
        SELECT id_movimiento, tipo, monto, concepto, categoria, metodo_pago, fecha, notas, id_reserva, id_admin
        FROM MOVIMIENTO_FINANCIERO
        ORDER BY fecha DESC, id_movimiento DESC
    """)
    manuales_raw = cur.fetchall()

    if cur:
        cur.close()
    if conn and conn.is_connected():
        conn.close()

    # Normalizar transacciones
    transacciones_todas = []

    for p in pagos_raw:
        monto = float(p['monto'])
        total_res = float(p['total'] or 0)
        anticipo_req = float(p['anticipo_requerido'] or 0)
        estado_res = p['estado_reserva']
        
        if estado_res == 'CANCELADA':
            subtipo = 'ANTICIPO_RETENIDO'
            etiqueta = 'Anticipo retenido (Cancelada)'
            categoria = 'RESERVA_CANCELADA'
        elif monto >= total_res and total_res > 0:
            subtipo = 'PAGO_COMPLETO'
            etiqueta = 'Pago completo (100%)'
            categoria = 'RESERVA_COMPLETA'
        elif abs(monto - anticipo_req) < 0.05:
            subtipo = 'ANTICIPO'
            etiqueta = 'Anticipo (50%)'
            categoria = 'ANTICIPO_RESERVA'
        else:
            subtipo = 'LIQUIDACION'
            etiqueta = 'Liquidación de saldo'
            categoria = 'LIQUIDACION_RESERVA'

        # Fecha a objeto datetime
        f = p['fecha']
        if isinstance(f, str):
            try:
                dt = datetime.fromisoformat(f.replace('Z', ''))
            except Exception:
                dt = datetime.strptime(f[:19], '%Y-%m-%d %H:%M:%S')
        else:
            dt = f

        transacciones_todas.append({
            'id': f"PAGO-{p['id_pago']}",
            'origen': 'RESERVA',
            'id_pago': p['id_pago'],
            'id_movimiento': None,
            'id_reserva': p['id_reserva'],
            'codigo_reserva': p['codigo'],
            'cliente': p['nombre_cliente'] or 'Cliente',
            'concepto': f"Reserva {p['codigo']} ({etiqueta})",
            'tipo': 'INGRESO',
            'subtipo': subtipo,
            'categoria': categoria,
            'metodo_pago': p['metodo_pago'] or 'TARJETA',
            'fecha_dt': dt,
            'fecha': dt.strftime('%Y-%m-%d %H:%M'),
            'monto': round(monto, 2),
            'es_editable': False,
            'notas': f"Total reserva: ${total_res:.2f}"
        })

    for m in manuales_raw:
        monto = float(m['monto'])
        f = m['fecha']
        if isinstance(f, str):
            try:
                dt = datetime.fromisoformat(f.replace('Z', ''))
            except Exception:
                dt = datetime.strptime(f[:19], '%Y-%m-%d %H:%M:%S')
        else:
            dt = f

        transacciones_todas.append({
            'id': f"MANUAL-{m['id_movimiento']}",
            'origen': 'MANUAL',
            'id_pago': None,
            'id_movimiento': m['id_movimiento'],
            'id_reserva': m['id_reserva'],
            'codigo_reserva': None,
            'cliente': 'Administración',
            'concepto': m['concepto'],
            'tipo': m['tipo'], # 'INGRESO' o 'RESTA'
            'subtipo': m['categoria'],
            'categoria': m['categoria'],
            'metodo_pago': m['metodo_pago'] or 'EFECTIVO',
            'fecha_dt': dt,
            'fecha': dt.strftime('%Y-%m-%d %H:%M'),
            'monto': round(monto, 2),
            'es_editable': True,
            'notas': m['notas'] or ''
        })

    # Ordenar por fecha_dt descendente
    transacciones_todas.sort(key=lambda x: x['fecha_dt'], reverse=True)

    # Métricas fijas (Globales para tarjetas fijas en UI)
    def calc_neto(items):
        ing = sum(x['monto'] for x in items if x['tipo'] == 'INGRESO')
        res = sum(x['monto'] for x in items if x['tipo'] == 'RESTA')
        return round(ing - res, 2)

    ingreso_hoy = calc_neto([t for t in transacciones_todas if t['fecha_dt'] >= inicio_hoy])
    ingreso_semana = calc_neto([t for t in transacciones_todas if t['fecha_dt'] >= inicio_semana])
    ingreso_mes = calc_neto([t for t in transacciones_todas if t['fecha_dt'] >= inicio_mes])
    total_historico = calc_neto(transacciones_todas)

    # Filtrar según período solicitado
    if periodo == 'hoy':
        dt_limite = inicio_hoy
        filtradas = [t for t in transacciones_todas if t['fecha_dt'] >= dt_limite]
    elif periodo == 'semana':
        dt_limite = inicio_semana
        filtradas = [t for t in transacciones_todas if t['fecha_dt'] >= dt_limite]
    elif periodo == 'mes':
        dt_limite = inicio_mes
        filtradas = [t for t in transacciones_todas if t['fecha_dt'] >= dt_limite]
    else: # 'todo'
        dt_limite = None
        filtradas = transacciones_todas

    # Resumen del período
    ingresos_res = sum(t['monto'] for t in filtradas if t['tipo'] == 'INGRESO' and t['origen'] == 'RESERVA')
    ingresos_man = sum(t['monto'] for t in filtradas if t['tipo'] == 'INGRESO' and t['origen'] == 'MANUAL')
    restas_egresos = sum(t['monto'] for t in filtradas if t['tipo'] == 'RESTA')
    ingreso_bruto = round(ingresos_res + ingresos_man, 2)
    ingreso_neto = round(ingreso_bruto - restas_egresos, 2)

    anticipos_m = sum(t['monto'] for t in filtradas if t['subtipo'] == 'ANTICIPO')
    anticipos_c = sum(1 for t in filtradas if t['subtipo'] == 'ANTICIPO')
    liquidaciones_m = sum(t['monto'] for t in filtradas if t['subtipo'] == 'LIQUIDACION')
    liquidaciones_c = sum(1 for t in filtradas if t['subtipo'] == 'LIQUIDACION')
    completos_m = sum(t['monto'] for t in filtradas if t['subtipo'] == 'PAGO_COMPLETO')
    completos_c = sum(1 for t in filtradas if t['subtipo'] == 'PAGO_COMPLETO')
    canceladas_m = sum(t['monto'] for t in filtradas if t['subtipo'] == 'ANTICIPO_RETENIDO')
    canceladas_c = sum(1 for t in filtradas if t['subtipo'] == 'ANTICIPO_RETENIDO')

    reservas_ids = set(t['id_reserva'] for t in filtradas if t['origen'] == 'RESERVA' and t['id_reserva'])
    total_pedidos = len(reservas_ids)
    ticket_medio = round(ingresos_res / total_pedidos, 2) if total_pedidos > 0 else 0.0

    print("=== METRICAS FIJAS ===")
    print(f"Hoy: ${ingreso_hoy}, Semana: ${ingreso_semana}, Mes: ${ingreso_mes}, Total: ${total_historico}")
    print("=== RESUMEN PERIODO ===")
    print(f"Neto: ${ingreso_neto}, Bruto: ${ingreso_bruto}, Restas: ${restas_egresos}, Pedidos: {total_pedidos}, Ticket Medio: ${ticket_medio}")
    print(f"Anticipos: ${anticipos_m} ({anticipos_c}), Completos: ${completos_m} ({completos_c}), Canceladas Retenidas: ${canceladas_m} ({canceladas_c})")
    print(f"Transacciones filtradas: {len(filtradas)}")

get_ingresos_data('todo')
