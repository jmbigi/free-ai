# Acceso público (desde cualquier equipo)

## Estado verificado en este servidor
- Servicio: `free-ai-gateway.service` **active/enabled**, `uvicorn` en `0.0.0.0:8000`, `Linger=yes`.
- Prueba local: `http://127.0.0.1:8000/health` → OK.
- Prueba desde la red del host: `http://109.123.248.91:8000/health` → OK (el puerto 8000 responde en la interfaz pública del servidor).

> **Importante:** que `0.0.0.0:8000` responda localmente no garantiza acceso desde Internet: puede haber firewall del proveedor/VPS, security group o NAT bloqueando el puerto 8000. Si no carga desde otro equipo, usa reverse proxy HTTPS por 80/443 (recomendado) o abre el puerto 8000 en el firewall del proveedor.

## Opción A — Acceso directo (rápido, menos recomendado)
Si el proveedor/firewall permite TCP 8000:
- Base URL: `http://109.123.248.91:8000/v1` (o `http://TU_DOMINIO:8000/v1`)
- API key: valor de `API_KEY` en `/home/admin/free-ai/.env`
- Prueba:
```bash
curl http://109.123.248.91:8000/health
curl http://109.123.248.91:8000/v1/chat/completions \
  -H "Authorization: Bearer TU_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Responde solo: OK"}]}'
```
Riesgo: HTTP sin TLS expone la API key si se usa por Internet público. Preferir HTTPS.

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
- **Base URL**: `https://TU_DOMINIO/v1` (o `http://IP:8000/v1` en prueba controlada)
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
- Prefiere HTTPS.
- Si dejas 8000 abierto, considera limitar por firewall a IPs conocidas (requiere acceso admin del proveedor/firewall).
