import sys
import os
import json

sys.path.insert(0, os.path.abspath('.'))
from app import app

client = app.test_client()

print("=== 1. VERIFICAR ACCESO NO AUTENTICADO (ANÓNIMO) ===")
# GET ingresos
res = client.get('/api/admin/ingresos')
assert res.status_code == 401, f"Expected 401, got {res.status_code}"
print("OK: Anónimo bloqueado en GET /api/admin/ingresos con 401.")

# POST movimiento
res = client.post('/api/admin/ingresos/movimiento', json={'tipo': 'INGRESO', 'monto': 10, 'concepto': 'hack'})
assert res.status_code == 401, f"Expected 401, got {res.status_code}"
print("OK: Anónimo bloqueado en POST /api/admin/ingresos/movimiento con 401.")

# POST entregar anticipo
res = client.post('/api/admin/ingresos/entregar-anticipo-retenido', json={'id_reserva': 1})
assert res.status_code == 401, f"Expected 401, got {res.status_code}"
print("OK: Anónimo bloqueado en POST /api/admin/ingresos/entregar-anticipo-retenido con 401.")

# DELETE movimiento
res = client.delete('/api/admin/ingresos/movimiento/1')
assert res.status_code == 401, f"Expected 401, got {res.status_code}"
print("OK: Anónimo bloqueado en DELETE /api/admin/ingresos/movimiento con 401.")

print("=== 2. VERIFICAR ACCESO DE USUARIO CLIENTE (NO ADMIN) ===")
with client.session_transaction() as sess:
    sess['es_cliente'] = True
    sess['id_cliente'] = 99
    sess['es_admin'] = False
    sess.pop('id_admin', None)

res = client.get('/api/admin/ingresos')
assert res.status_code == 401, f"Expected 401, got {res.status_code}"
print("OK: Cliente bloqueado en /api/admin/ingresos con 401.")

res = client.get('/admin/ingresos')
assert res.status_code == 302, f"Expected 302 redirect, got {res.status_code}"
assert '/admin/login' in res.headers.get('Location', '')
print("OK: Cliente redirigido a login al intentar entrar a /admin/ingresos.")

print("=== 3. VERIFICAR VALIDACIÓN CSRF EN ADMIN ===")
# Sesión admin pero sin CSRF Token válido
with client.session_transaction() as sess:
    sess['es_admin'] = True
    sess['id_admin'] = 1
    sess['admin_email'] = 'twiinsbakery01@gmail.com'
    sess['csrf_token'] = 'token-secreto-admin-123'

# Intento de POST sin token
res = client.post(
    '/api/admin/ingresos/movimiento',
    json={'tipo': 'INGRESO', 'monto': 10, 'concepto': 'Prueba sin CSRF'}
)
assert res.status_code == 403, f"Expected 403 CSRF error, got {res.status_code}"
print("OK: Petición sin CSRF rechazada con 403.")

# Intento con token falso
res = client.post(
    '/api/admin/ingresos/movimiento',
    json={'tipo': 'INGRESO', 'monto': 10, 'concepto': 'Prueba con CSRF falso'},
    headers={'X-CSRF-Token': 'token-falso-invalido'}
)
assert res.status_code == 403, f"Expected 403 CSRF error, got {res.status_code}"
print("OK: Petición con CSRF inválido rechazada con 403.")

print("=== 4. VERIFICAR RESISTENCIA A VALORES INYECTADOS EN MONTO Y CAMPOS ===")
# Monto negativo o no numérico
res = client.post(
    '/api/admin/ingresos/movimiento',
    json={'tipo': 'INGRESO', 'monto': -500, 'concepto': 'Inyección monto negativo'},
    headers={'X-CSRF-Token': 'token-secreto-admin-123'}
)
assert res.status_code == 400
print("OK: Monto negativo rechazado con 400.")

# Tipo inválido
res = client.post(
    '/api/admin/ingresos/movimiento',
    json={'tipo': 'HACK', 'monto': 100, 'concepto': 'Tipo inválido'},
    headers={'X-CSRF-Token': 'token-secreto-admin-123'}
)
assert res.status_code == 400
print("OK: Tipo de operación inválido rechazado con 400.")

print("=== AUDITORÍA DE SEGURIDAD FINALIZADA CON ÉXITO ===")
