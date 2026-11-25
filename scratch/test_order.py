import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from app import app

client = app.test_client()
with client.session_transaction() as sess:
    sess['es_admin'] = True
    sess['id_admin'] = 1
    sess['admin_email'] = 'twiinsbakery01@gmail.com'

resp = client.get('/api/admin/reservas')
print("Status:", resp.status_code)
if resp.status_code == 200:
    data = resp.get_json()
    print("Total reservas:", len(data))
    ids = [r['id'] for r in data]
    print("IDs de reservas:", ids)
    is_desc = all(ids[i] >= ids[i+1] for i in range(len(ids)-1))
    print("¿Están ordenadas de más reciente a más antigua (id desc)?:", is_desc)
    for r in data[:4]:
        print(f"ID: {r['id']} | Código: {r['codigo']} | Cliente: {r['cliente']} | Fecha creación/ID order")
