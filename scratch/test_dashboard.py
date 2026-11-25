import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from app import app

client = app.test_client()
with client.session_transaction() as sess:
    sess['es_admin'] = True
    sess['id_admin'] = 1
    sess['admin_email'] = 'twiinsbakery01@gmail.com'

resp = client.get('/api/admin/dashboard')
print("Status:", resp.status_code)
print("Data:", resp.get_data(as_text=True))
