# Lightweight smoke tests (no pytest required). Run: .venv/bin/python tests_smoke.py
from __future__ import annotations
import os, sys
os.environ.setdefault('CACHE_ENABLED', '1')
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

key = settings.api_key or 'test'
# If no key configured, inject one for test client via env is hard; but settings reads .env. Use existing.
c = TestClient(app)

def ok(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL') + ':', name, detail if not cond else '')
    if not cond:
        raise SystemExit(1)

r = c.get('/health')
ok('health 200', r.status_code == 200)
ok('health has version', 'version' in r.json())
r = c.get('/readyz')
ok('readyz', r.status_code == 200 and r.json().get('status') == 'ready')
r = c.get('/help')
ok('help html', r.status_code == 200 and 'OpenCode' in r.text and 'KiloCode' in r.text and 'FT_AI_API_KEY' in r.text)
r = c.get('/help.json')
ok('help json', r.status_code == 200 and r.json()['openai_base_url'].endswith('/v1'))
r = c.get('/v1/models')
ok('models auth', r.status_code == 401)
r = c.get('/v1/models', headers={'Authorization': f'Bearer {key}'})
ok('models ok', r.status_code == 200 and r.json().get('object') == 'list')
# invalid body
r = c.post('/v1/chat/completions', headers={'Authorization': f'Bearer {key}'}, json='nope')
ok('invalid body 400', r.status_code in (400, 422))
# size guard
r = c.post('/v1/chat/completions', headers={'Authorization': f'Bearer {key}', 'content-length': str(3*1024*1024)}, json={'model':'auto','messages':[{'role':'user','content':'x'}]})
ok('body guard 413', r.status_code == 413)
# responses shape normalization (may fail upstream by rate limits; accept 200 or 502 with structured error)
r = c.post('/v1/responses', headers={'Authorization': f'Bearer {key}'}, json={'model':'pollinations/openai-fast','input':'Responde solo: OK','max_output_tokens':8,'temperature':0,'cache':False})
ok('responses handled', r.status_code in (200,502), str(r.status_code))
if r.status_code == 200:
    ok('responses object', r.json().get('object') == 'response')
else:
    ok('responses structured error', 'error' in r.json() and 'request_id' in r.json()['error'])
# headers
r = c.get('/health')
ok('request id header', bool(r.headers.get('x-request-id')))
ok('gateway version header', bool(r.headers.get('x-gateway-version')))
print('ALL PASS')
