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
    sess['csrf_token'] = 'test-token-123'

# 1. GET /api/admin/ingresos?periodo=semana
res = client.get('/api/admin/ingresos?periodo=semana')
print(f"Status GET ingresos: {res.status_code}")
data = json.loads(res.data.decode('utf-8'))
print("Metricas fijas:", data.get('metricas_fijas'))
print("Resumen periodo:", data.get('resumen_periodo'))
print("Puntos grafica:", len(data.get('grafica', [])))
print("Transacciones:", len(data.get('transacciones', [])))

# 2. POST /api/admin/ingresos/movimiento (Ingreso)
post_data = {
    'tipo': 'INGRESO',
    'monto': 18.50,
    'concepto': 'Venta rápida de 2 postres de tiramisú',
    'categoria': 'VENTA_DIRECTA',
    'metodo_pago': 'EFECTIVO',
    'notas': 'Mostrador presencial'
}
res_post = client.post(
    '/api/admin/ingresos/movimiento',
    data=json.dumps(post_data),
    content_type='application/json',
    headers={'X-CSRF-Token': 'test-token-123'}
)
print(f"Status POST movimiento: {res_post.status_code}, Resp: {res_post.data.decode('utf-8')}")
id_mov = json.loads(res_post.data.decode('utf-8')).get('id_movimiento')

# 3. DELETE /api/admin/ingresos/movimiento/<id>
if id_mov:
    res_del = client.delete(
        f'/api/admin/ingresos/movimiento/{id_mov}',
        headers={'X-CSRF-Token': 'test-token-123'}
    )
    print(f"Status DELETE movimiento: {res_del.status_code}, Resp: {res_del.data.decode('utf-8')}")
