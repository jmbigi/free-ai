import os, warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
os.environ.setdefault('FT_AI_API_KEY','test-gateway-key')
from fastapi.testclient import TestClient
from app.main import app

def ok(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL') + f': {name}', detail)
    if not cond:
        raise SystemExit(1)

AUTH = {'Authorization':'Bearer test-gateway-key'}
c = TestClient(app)
r = c.get('/health'); ok('health 200', r.status_code == 200); ok('health has version', 'version' in r.json())
ok('readyz', c.get('/readyz').status_code == 200)
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
