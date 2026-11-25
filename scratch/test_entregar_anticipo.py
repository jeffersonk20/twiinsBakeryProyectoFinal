import sys
import os
import json

sys.path.insert(0, os.path.abspath('.'))
from app import app

client = app.test_client()
with client.session_transaction() as sess:
    sess['es_admin'] = True
    sess['id_admin'] = 1
    sess['admin_email'] = 'twiinsbakery01@gmail.com'
    sess['csrf_token'] = 'token-test-entregar'

print("=== 1. VERIFICAR TRANSACCIÓN CON ANTICIPO RETENIDO ===")
res1 = client.get('/api/admin/ingresos?periodo=todo')
assert res1.status_code == 200
data1 = json.loads(res1.data.decode('utf-8'))
neto_inicial = data1['resumen_periodo']['ingreso_neto']
print(f"Neto inicial: ${neto_inicial}")

tx_cancelada = next((t for t in data1['transacciones'] if t['subtipo'] == 'ANTICIPO_RETENIDO'), None)
assert tx_cancelada is not None, "No se encontró transacción de anticipo retenido"
print(f"Transacción cancelada encontrada: Código={tx_cancelada['codigo_reserva']}, Monto=${tx_cancelada['monto']}, Puede entregar={tx_cancelada.get('puede_entregar_anticipo')}")
assert tx_cancelada.get('puede_entregar_anticipo') == True

print("=== 2. EJECUTAR ENTREGA DE ANTICIPO RETENIDO ===")
res_entregar = client.post(
    '/api/admin/ingresos/entregar-anticipo-retenido',
    data=json.dumps({'id_reserva': tx_cancelada['id_reserva']}),
    content_type='application/json',
    headers={'X-CSRF-Token': 'token-test-entregar'}
)
print(f"Status entrega: {res_entregar.status_code}, Resp: {res_entregar.data.decode('utf-8')}")
assert res_entregar.status_code == 201
data_ent = json.loads(res_entregar.data.decode('utf-8'))
id_mov = data_ent['id_movimiento']

print("=== 3. VERIFICAR QUE SE RESTÓ DEL SISTEMA ===")
res2 = client.get('/api/admin/ingresos?periodo=todo')
data2 = json.loads(res2.data.decode('utf-8'))
neto_posterior = data2['resumen_periodo']['ingreso_neto']
print(f"Neto posterior: ${neto_posterior}")
diferencia = round(neto_inicial - neto_posterior, 2)
print(f"Diferencia restada del sistema: ${diferencia} (Esperado: ${tx_cancelada['monto']})")
assert diferencia == tx_cancelada['monto']

print("=== 4. VERIFICAR PREVENCIÓN DE DUPLICADOS ===")
res_dup = client.post(
    '/api/admin/ingresos/entregar-anticipo-retenido',
    data=json.dumps({'id_reserva': tx_cancelada['id_reserva']}),
    content_type='application/json',
    headers={'X-CSRF-Token': 'token-test-entregar'}
)
print(f"Status duplicado: {res_dup.status_code}, Resp: {res_dup.data.decode('utf-8')}")
assert res_dup.status_code == 400

print("=== 5. VERIFICAR ESTADO EN LISTA DE TRANSACCIONES ===")
tx_cancelada_actualizada = next((t for t in data2['transacciones'] if t['id_reserva'] == tx_cancelada['id_reserva'] and t['origen'] == 'RESERVA'), None)
assert tx_cancelada_actualizada['anticipo_devuelto'] == True
assert tx_cancelada_actualizada['puede_entregar_anticipo'] == False
print(f"Estado actualizado en transacción: anticipo_devuelto={tx_cancelada_actualizada['anticipo_devuelto']}, etiqueta='{tx_cancelada_actualizada['subtipo_etiqueta']}'")

# Verificar que la RESTA aparece en la lista de transacciones
tx_resta_generada = next((t for t in data2['transacciones'] if t['id_movimiento'] == id_mov), None)
assert tx_resta_generada is not None
print(f"Nueva transacción de resta creada: Concepto='{tx_resta_generada['concepto']}', Monto=-${tx_resta_generada['monto']}")

print("=== TODOS LOS TESTS PASARON EXITOSAMENTE ===")
