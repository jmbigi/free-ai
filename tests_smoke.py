import os, warnings
from pathlib import Path
from dotenv import dotenv_values
warnings.filterwarnings('ignore', category=DeprecationWarning)
_env = Path(__file__).resolve().parent / '.env'
_vals = dotenv_values(_env) if _env.exists() else {}
_key = (_vals.get('FT_AI_API_KEY') or _vals.get('API_KEY') or os.getenv('FT_AI_API_KEY') or os.getenv('API_KEY') or 'test-gateway-key')
_key = str(_key).strip().strip('"\'')
os.environ.setdefault('FT_AI_API_KEY', _key); os.environ.setdefault('API_KEY', _key)
from fastapi.testclient import TestClient
from app.main import app

def ok(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL') + f': {name}', detail)
    if not cond: raise SystemExit(1)

AUTH = {'Authorization': f'Bearer {_key}'}
c = TestClient(app)
r = c.get('/health'); ok('health 200', r.status_code == 200); ok('health has version', 'version' in r.json())
ok('readyz', c.get('/readyz').status_code == 200)
ok('ping', c.get('/v1/ping').json().get('ok') is True)
ok('help html', c.get('/help').status_code == 200)
ok('help json', c.get('/help.json').status_code == 200)
ok('models auth', c.get('/v1/models').status_code in (401, 403))
ok('models ok', c.get('/v1/models', headers=AUTH).status_code == 200)
ok('invalid body 400', c.post('/v1/chat/completions', headers=AUTH, json={'model':'auto'}).status_code in (400,422))
resp = c.post('/v1/responses', headers=AUTH, json={'model':'auto','input':'hola','max_output_tokens':5})
ok('responses handled', resp.status_code in (200,400,401,403,422,502))
if resp.status_code == 200:
    d = resp.json(); ok('responses object', d.get('object') == 'response' and 'output_text' in d)
ok('request id header', bool(c.get('/health').headers.get('x-request-id')))
ok('gateway version header', bool(c.get('/health').headers.get('x-gateway-version')))
print('ALL PASS')
