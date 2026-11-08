# 2026-11-08: KimiCode conectado al gateway local

## Configuración

- KimiCode: **2.5.2** (`~/.nvm/versions/node/v22.23.2/bin/kimi`).
- Backup previo: `~/.kimi-code/config.toml.bak-20261108-191646`.
- Provider añadido:

```toml
[providers.free-ai-local]
type = "openai"
base_url = "http://127.0.0.1:8000/v1"
api_key_env = "FT_AI_API_KEY"

[models."free-ai-local/auto"]
provider = "free-ai-local"
model = "auto"
max_context_size = 128000
max_output_size = 8192
display_name = "Free AI Gateway local (auto)"
capabilities = ["thinking", "tool_use"]
```

No se imprimen ni commitean claves; `FT_AI_API_KEY` se toma del `.env` local.

## Verificación

- `kimi doctor`: **OK config.toml / OK tui.toml / all valid**.
- `kimi -m free-ai-local/auto -p "Responde solo: ok" --output-format text`:
  **exit 0**, respuesta `ok`.
- Gateway local: `http://127.0.0.1:8000/v1`; NCM LM1B-large activo en
  `11436`; Qwen/Ollama inactivo.
- `auto` usa primero proveedores remotos gratuitos; LM1B-large no entra en
  `auto` porque es unconditional.

## Reproducir

```bash
cd /home/kubuntu/free-ai
set -a; . ./.env; set +a
kimi -m free-ai-local/auto -p "Responde solo: ok" --output-format text
```

Si el provider local no aparece, revisar `kimi doctor` y el bloque
`[providers.free-ai-local]` del `config.toml`.
