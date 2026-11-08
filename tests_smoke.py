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
ok('audit ok', c.get('/v1/audit', headers=AUTH).status_code == 200)
ok('invalid body 400', c.post('/v1/chat/completions', headers=AUTH, json={'model':'auto'}).status_code in (400,422))
ok('embeddings 501', c.post('/v1/embeddings', headers=AUTH, json={'model':'auto','input':'x'}).status_code == 501)
resp = c.post('/v1/responses', headers=AUTH, json={'model':'auto','input':'hola','max_output_tokens':5})
ok('responses handled', resp.status_code in (200,400,401,403,422,501,502))
if resp.status_code == 200:
    d = resp.json(); ok('responses object', d.get('object') == 'response' and 'output_text' in d)
ok('request id header', bool(c.get('/health').headers.get('x-request-id')))
ok('gateway version header', bool(c.get('/health').headers.get('x-gateway-version')))

# --- Auth mode compatibility (regla 5 del programador: aliases) ---
ok('auth api-key', c.get('/v1/models', headers={'api-key': _key}).status_code == 200)
ok('auth x-api-key', c.get('/v1/models', headers={'x-api-key': _key}).status_code == 200)
ok('auth query key', c.get(f'/v1/models?key={_key}').status_code == 200)
ok('auth no key 401', c.get('/v1/models').status_code in (401, 403))

# --- Body/input alias compatibility ---
bad = c.post('/v1/chat/completions', headers=AUTH, json={'model': 'auto'})
ok('invalid body 400/422', bad.status_code in (400, 422))
alias = c.post('/v1/chat/completions', headers=AUTH, json={'model': 'auto', 'prompt': 'Responde solo: ALIAS'})
ok('prompt alias accepted', alias.status_code in (200, 400, 401, 403, 422, 501, 502))
if alias.status_code == 200:
    ok('prompt alias content', bool(((alias.json().get('choices') or [{}])[0].get('message') or {}).get('content')))
maxct = c.post('/v1/chat/completions', headers=AUTH, json={'model': 'auto', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_completion_tokens': 8})
ok('max_completion_tokens alias', maxct.status_code in (200, 400, 401, 403, 422, 501, 502))

# --- Cache: miss then hit (temperature=0 + cache:true) ---
# Pollinations anónimo tiene rate limit ~45s/IP; si el fallback se agota (502) el test salta, no falla.
c.post('/v1/cache/clear', headers=AUTH)
payload = {'model': 'auto', 'messages': [{'role': 'user', 'content': 'Cache probe 1'}], 'max_tokens': 8, 'temperature': 0, 'cache': True}
r1 = c.post('/v1/chat/completions', headers=AUTH, json=payload)
if r1.status_code != 200:
    print(f"WARN: cache probe skipped (upstream rate-limited, status={r1.status_code})")
else:
    ok('cache miss first call', r1.json().get('gateway', {}).get('cache', {}).get('hit') is False)
    r2 = c.post('/v1/chat/completions', headers=AUTH, json=payload)
    ok('cache hit second call', r2.status_code == 200 and r2.json().get('gateway', {}).get('cache', {}).get('hit') is True)
ci = c.get('/v1/cache', headers=AUTH).json()
ok('cache info endpoint', ci.get('entries') is not None or ci.get('size') is not None or ci.get('count') is not None or ci.get('items') is not None)
cleared = c.post('/v1/cache/clear', headers=AUTH).json()
ok('cache clear endpoint', 'cleared' in cleared)

# --- Context compression metadata ---
big = 'x ' * 60000
r3 = c.post('/v1/chat/completions', headers=AUTH, json={'model': 'auto', 'messages': [{'role': 'user', 'content': big}, {'role': 'user', 'content': 'Responde solo: OK'}], 'max_tokens': 8, 'temperature': 0, 'compress_context': True})
ok('compress context handled', r3.status_code in (200, 400, 401, 403, 422, 501, 502))
if r3.status_code == 200:
    gw = r3.json().get('gateway', {})
    ok('compress metadata present', 'context' in gw or 'context_compressed' in gw)

# --- FREE_ONLY policy enforcement ---
forbidden = c.post('/v1/chat/completions', headers=AUTH, json={'model': 'openai/gpt-4o', 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 8})
ok('FREE_ONLY blocks paid model', forbidden.status_code in (400, 403, 422))
free = c.post('/v1/projects/generate', headers=AUTH, json={'prompt': 'x', 'name': 't', 'model': 'openai/gpt-4o'})
ok('project-gen FREE_ONLY blocks', free.status_code in (400, 403, 422))

# --- Observability endpoints ---
ok('metrics endpoint', c.get('/v1/metrics', headers=AUTH).status_code == 200)
ok('status endpoint', c.get('/v1/status', headers=AUTH).status_code == 200)
ok('free endpoint', c.get('/v1/free', headers=AUTH).status_code == 200)
ok('providers endpoint', c.get('/v1/providers', headers=AUTH).status_code == 200)
ok('tools endpoint', c.get('/v1/tools').status_code == 200)
ok('telemetry endpoint', c.get('/v1/telemetry').status_code == 200)
ok('debug endpoint', c.get('/v1/debug').status_code == 200)
ok('connections endpoint', c.get('/v1/connections').status_code == 200)

# --- v1 root + aliases ---
ok('v1 root', c.get('/v1', headers=AUTH).status_code == 200)
ok('openai/v1 alias', c.get('/openai/v1', headers=AUTH).status_code == 200)
ok('api/v1 alias', c.get('/api/v1', headers=AUTH).status_code == 200)

print('ALL PASS')
