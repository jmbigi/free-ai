# Acceso público (desde cualquier equipo)

## Estado verificado en este servidor
- Servicio: `free-ai-gateway.service` **active/enabled**, `uvicorn` en `127.0.0.1:8000` (loopback), `Linger=yes`.
- Prueba local: `http://127.0.0.1:8000/health` → OK.
- Acceso público: **solo** `https://ia.forthtrade.com` vía Apache. Puerto 8000 directo cerrado.
- Unit versionado: `deploy/free-ai-gateway.service`.

> **Importante:** no expongas `0.0.0.0:8000` a Internet. Bypassea HTTPS, la redacción de query keys en logs y el proxy. El único acceso público debe ser el reverse proxy HTTPS 80/443.

## Opción A — Acceso directo (solo LAN/pruebas, deshabilitado por defecto)
Solo si controlás firewall y red confiable: arrancar con `HOST=0.0.0.0 ./run.sh` (o editar el unit). No recomendado: HTTP sin TLS expone la API key y evita la redacción de logs del proxy.

## Opción B — HTTPS con Apache reverse proxy (recomendado en este servidor)
Apache ya sirve 80/443. Plantilla: `deploy/apache-free-ai-gateway.conf`.
Pasos (requieren sudo/DNS):
1. Crear DNS `A`/`AAAA` para `ai.TU_DOMINIO` → IP del servidor.
2. Copiar config y habilitar sitio:
```bash
sudo cp /home/admin/free-ai/deploy/apache-free-ai-gateway.conf /etc/httpd/sites-available/free-ai-gateway.conf
sudo ln -s ../sites-available/free-ai-gateway.conf /etc/httpd/sites-enabled/free-ai-gateway.conf
```
3. Obtener certificado:
```bash
sudo certbot --apache -d ai.TU_DOMINIO
```
4. Validar/recargar:
```bash
sudo apachectl configtest && sudo systemctl reload httpd
```
5. Usar base URL: `https://ai.TU_DOMINIO/v1`

## Opción C — Caddy
Plantilla: `deploy/Caddyfile.example`. Caddy gestiona TLS automáticamente si el DNS apunta al servidor.

## Configuración en clientes (KiloCode/OpenCode/DeepSeek harness/OpenAI-compatible)
- **Base URL**: `https://TU_DOMINIO/v1` (HTTPS reverse proxy)
- **API Key**: la `API_KEY` del gateway (`.env`), **no** las claves upstream.
- **Modelo**: `auto` (recomendado, fallback + caché + compresión).

Ejemplo OpenAI SDK:
```python
from openai import OpenAI
client = OpenAI(base_url="https://ai.TU_DOMINIO/v1", api_key="TU_API_KEY_GATEWAY")
r = client.chat.completions.create(model="auto", messages=[{"role":"user","content":"Hola"}])
print(r.choices[0].message.content)
```

## Seguridad operativa
- Mantén `API_KEY` secreta; rota si se expone.
- No expongas `.env` ni claves upstream.
- Usa siempre HTTPS por el reverse proxy; mantené 8000 en loopback y bloqueado por firewall.
- Los query keys (`?key=`) se aceptan por compatibilidad, pero se redactan en logs uvicorn/Apache. Preferí headers (`Authorization: Bearer`).


## Conexión desde Kimi / Moonshot / clientes OpenAI-compatible
Este gateway expone una API **OpenAI-compatible** con **una sola API key del gateway** (`API_KEY` en `.env` del servidor). No uses claves upstream.

### Caso 1 — Usar este gateway como endpoint en un cliente compatible (recomendado)
Configura el cliente/harness para apuntar a tu gateway:
- **Base URL:** `https://ai.TU_DOMINIO/v1` (HTTPS reverse proxy). No usar IP:8000 directo.
- **API Key:** `TU_API_KEY_GATEWAY` (valor de `API_KEY` del gateway).
- **Model:** `auto` (recomendado: fallback + caché + control `FREE_ONLY`).

Ejemplo `curl`:
```bash
curl https://ai.TU_DOMINIO/v1/chat/completions   -H "Authorization: Bearer TU_API_KEY_GATEWAY"   -H "Content-Type: application/json"   -d '{"model":"auto","messages":[{"role":"user","content":"Hola desde Kimi/client"}]}'
```

Ejemplo Python OpenAI SDK:
```python
from openai import OpenAI
client = OpenAI(base_url="https://ai.TU_DOMINIO/v1", api_key="TU_API_KEY_GATEWAY")
resp = client.chat.completions.create(
    model="auto",
    messages=[{"role":"user","content":"Hola"}],
)
print(resp.choices[0].message.content)
```

### Caso 2 — “Conectarme desde Kimi” para que Kimi sea el proveedor upstream
Si lo que quieres es que **Kimi/Moonshot** responda *a través de este gateway*, agrega una clave/configuración upstream válida de Moonshot/Kimi en `.env` del servidor (`MOONSHOT_API_KEY` o alias soportado por `app/config.py`) y reinicia:
```bash
systemctl --user restart free-ai-gateway.service
```
Luego consulta modelos/proveedores con `GET /v1/providers` y `GET /v1/models` (autenticado). **Importante:** con `FREE_ONLY=1` (política por defecto), el gateway bloquea candidatos no identificados como free-tier explícito; el acceso oficial a Moonshot/Kimi normalmente depende de cuenta/créditos/términos del proveedor. Para usarlo bajo tu responsabilidad y con credenciales válidas, revisa `FREE_ONLY`/`ALLOW_PAID_MODELS` en `.env` y la documentación/estado real del proveedor. El gateway no puede garantizar que una cuenta upstream sea gratuita o ilimitada.

### Verificación rápida
```bash
curl -sS https://ia.forthtrade.com/health
curl -sS https://ia.forthtrade.com/v1/status -H "Authorization: Bearer TU_API_KEY_GATEWAY"
curl -sS https://ia.forthtrade.com/v1/free -H "Authorization: Bearer TU_API_KEY_GATEWAY"
```
