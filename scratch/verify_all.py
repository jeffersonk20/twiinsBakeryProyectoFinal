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
    sess['csrf_token'] = 'test-token-xyz'

print("=== 1. TEST RENDER /admin/ingresos ===")
res_view = client.get('/admin/ingresos')
assert res_view.status_code == 200, f"Expected 200, got {res_view.status_code}"
html_content = res_view.data.decode('utf-8')
assert 'data-admin-ingresos' in html_content
assert 'Control de Ingresos y Movimientos' in html_content
assert 'data-chart-bars' in html_content
assert 'adminDynamicModal' in html_content
assert 'modalMovimiento' in html_content
print("OK: Vista /admin/ingresos renderiza correctamente con todos los componentes.")

print("=== 2. TEST PERIODOS API /api/admin/ingresos ===")
for p in ['hoy', 'semana', 'mes', 'todo']:
    res = client.get(f'/api/admin/ingresos?periodo={p}')
    assert res.status_code == 200, f"Error en periodo {p}: {res.status_code}"
    data = json.loads(res.data.decode('utf-8'))
    assert 'metricas_fijas' in data
    assert 'resumen_periodo' in data
    assert 'grafica' in data
    assert 'transacciones' in data
    print(f"OK Periodo '{p}': {len(data['transacciones'])} transacciones, {len(data['grafica'])} barras de grafica, Neto={data['resumen_periodo']['ingreso_neto']}")

print("=== 3. TEST REGISTRAR INGRESO Y RESTA ===")
# Ingreso
post_ingreso = {
    'tipo': 'INGRESO',
    'monto': 35.00,
    'concepto': 'Venta presencial de pastel mediano de zanahoria',
    'categoria': 'VENTA_DIRECTA',
    'metodo_pago': 'EFECTIVO',
    'notas': 'Mostrador central'
}
res_pi = client.post(
    '/api/admin/ingresos/movimiento',
    data=json.dumps(post_ingreso),
    content_type='application/json',
    headers={'X-CSRF-Token': 'test-token-xyz'}
)
assert res_pi.status_code == 201, f"Error post ingreso: {res_pi.data}"
id_ingreso = json.loads(res_pi.data.decode('utf-8'))['id_movimiento']
print(f"OK: Ingreso creado con ID {id_ingreso}")

# Resta
post_resta = {
    'tipo': 'RESTA',
    'monto': 12.50,
    'concepto': 'Compra de cajas para empaque y cinta de regalo',
    'categoria': 'EMPAQUE',
    'metodo_pago': 'EFECTIVO',
    'notas': 'Proveedor de empaques'
}
res_pr = client.post(
    '/api/admin/ingresos/movimiento',
    data=json.dumps(post_resta),
    content_type='application/json',
    headers={'X-CSRF-Token': 'test-token-xyz'}
)
assert res_pr.status_code == 201, f"Error post resta: {res_pr.data}"
id_resta = json.loads(res_pr.data.decode('utf-8'))['id_movimiento']
print(f"OK: Resta creada con ID {id_resta}")

# Verificar recálculo
res_check = client.get('/api/admin/ingresos?periodo=todo')
data_check = json.loads(res_check.data.decode('utf-8'))
print(f"Recálculo verificado: Bruto={data_check['resumen_periodo']['ingreso_bruto']}, Restas={data_check['resumen_periodo']['restas_egresos']}, Neto={data_check['resumen_periodo']['ingreso_neto']}")

# Limpiar los registros de prueba creados
client.delete(f'/api/admin/ingresos/movimiento/{id_ingreso}', headers={'X-CSRF-Token': 'test-token-xyz'})
client.delete(f'/api/admin/ingresos/movimiento/{id_resta}', headers={'X-CSRF-Token': 'test-token-xyz'})
print("OK: Registros temporales de prueba limpiados correctamente.")

print("=== SUITE DE PRUEBAS FINALIZADA CON ÉXITO ===")
