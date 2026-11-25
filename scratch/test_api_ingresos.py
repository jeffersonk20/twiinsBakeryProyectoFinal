import sys
import os
import json
from decimal import Decimal
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.abspath('.'))
from app import app

client = app.test_client()
with client.session_transaction() as sess:
    sess['es_admin'] = True
    sess['id_admin'] = 1
    sess['admin_email'] = 'twiinsbakery01@gmail.com'

print("Test script setup complete.")
