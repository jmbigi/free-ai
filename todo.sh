#!/usr/bin/env bash
set -euo pipefail

# Free AI Gateway - TODO-EN-UNO: crear, instalar, verificar, operar, mejorar
# Uso: ./todo.sh [all|help|env|install|check|smoke|status|health|audit|search|decision|restart|logs|improve|public-check]
# Seguro: no imprime claves completas. Lee FT_AI_API_KEY/API_KEY desde entorno o .env.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv"; PY="$VENV/bin/python"; PIP="$VENV/bin/pip"
SERVICE="free-ai-gateway.service"
BASE="${GATEWAY_BASE_URL:-https://ia.forthtrade.com}"
LOCAL="http://127.0.0.1:${PORT:-8000}"

c() { printf '\033[%sm%s\033[0m\n' "$1" "$2"; }
info() { c '36;1' "==> $*"; }
ok()   { c '32;1' "OK: $*"; }
warn() { c '33;1' "WARN: $*"; }
err()  { c '31;1' "ERR: $*"; }
hr() { printf '%s\n' '------------------------------------------------------------'; }

need_py() { [[ -x "$PY" ]] || { err "Falta $PY"; echo "Ejecuta: ./todo.sh install"; exit 1; }; }

load_key() {
  [[ -n "${FT_AI_API_KEY:-}" ]] && { printf '%s' "$FT_AI_API_KEY"; return; }
  [[ -n "${API_KEY:-}" ]] && { printf '%s' "$API_KEY"; return; }
  [[ -f .env && -x "$PY" ]] && "$PY" - <<'PY'
from dotenv import dotenv_values
v=dotenv_values('.env')
print((v.get('FT_AI_API_KEY') or v.get('API_KEY') or '').strip().strip('"\''))
PY
}

mask() { local s="${1:-}"; [[ -z "$s" ]] && echo MISSING || { [[ ${#s} -le 8 ]] && echo SET || echo "${s:0:4}...${s: -4}"; }; }
auth_hdr() { local k; k="$(load_key)"; [[ -n "$k" ]] || { err "Define FT_AI_API_KEY/API_KEY en entorno o .env"; exit 1; }; printf 'Authorization: Bearer %s' "$k"; }

cmd_help() {
  cat <<'EOF'
Free AI Gateway - TODO-EN-UNO
Uso: ./todo.sh <comando>

Comandos:
  all            env + install + check + smoke + status + health + improve
  env            Crea .env desde .env.example si falta (no sobreescribe)
  install        Crea/actualiza .venv e instala requirements
  check          py_compile + import sanity
  smoke          Smoke tests locales
  status         Estado systemd --user + probes local/público
  health         /health público resumido
  audit          /v1/audit (auth)
  search "q"     POST /v1/search (auth)
  decision "q"   POST /v1/decision (auth, sin búsqueda web por defecto)
  restart        Reinicia free-ai-gateway.service (systemd --user)
  logs [N]       Logs del servicio
  public-check   DNS/HTTPS/readyz
  improve        Reporte con evidencia y mejoras recomendadas
  help           Esta ayuda

Cliente (Kimi/OpenCode/KiloCode/DeepSeek harness/OpenAI-compatible):
  export FT_AI_API_KEY="TU_API_KEY_GATEWAY"
  Base URL: https://ia.forthtrade.com/v1   Model: auto

Notas: FREE_ONLY=gratis/controlado != ilimitado. Rotar FT_AI_API_KEY si se expuso.
EOF
}

cmd_env() {
  if [[ -f .env ]]; then
    ok ".env ya existe (no modificado)"
  else
    [[ -f .env.example ]] || { err "Falta .env.example"; exit 1; }
    cp .env.example .env
    if command -v openssl >/dev/null 2>&1 && grep -q 'change-this' .env; then
      K="$(openssl rand -hex 32)"
      "$PY" - "$K" <<'PY' 2>/dev/null || python3 - "$K" <<'PY'
import sys
from pathlib import Path
k=sys.argv[1]; p=Path('.env'); t=p.read_text()
for name in ('API_KEY','FT_AI_API_KEY'):
  t=t.replace(f'{name}=change-this-to-a-strong-random-key', f'{name}={k}')
p.write_text(t)
print('generated')
PY
    fi
    ok "Creado .env desde .env.example"
  fi
  local k; k="$(load_key)"; info "API key gateway: $(mask "$k")"
}

cmd_install() {
  info "Instalando entorno Python"
  command -v python3 >/dev/null || { err "python3 no encontrado"; exit 1; }
  [[ -d "$VENV" ]] || python3 -m venv "$VENV"
  "$PIP" install --upgrade pip >/dev/null
  "$PIP" install -r requirements.txt
  ok "Dependencias instaladas"
}

cmd_check() {
  need_py
  info "py_compile"
  "$PY" -m py_compile app/*.py app/providers/*.py
  info "imports"
  "$PY" -c "import app.main,app.router,app.auth,app.cache,app.context,app.search,app.knowledge,app.tool_support,app.observability,app.help_page; print('imports ok')"
  ok "Check OK"
}

cmd_smoke() { need_py; info "Smoke tests"; "$PY" tests_smoke.py; ok "Smoke OK"; }

cmd_status() {
  info "Servicio systemd --user"
  systemctl --user status "$SERVICE" --no-pager -l 2>&1 | sed -n '1,12p' || warn "No se pudo leer estado"
  hr
  curl -fsS -o /dev/null -w "local  health %{http_code} %{time_total}s\n" "$LOCAL/health" 2>&1 || warn "local health falló"
  curl -fsS -o /dev/null -w "public health %{http_code} %{time_total}s\n" "$BASE/health" 2>&1 || warn "public health falló"
  curl -fsS -o /dev/null -w "public readyz %{http_code} %{time_total}s\n" "$BASE/readyz" 2>&1 || true
}

cmd_health() {
  curl -fsS "$BASE/health" | "$PY" -c '
import sys,json
d=json.load(sys.stdin)
print("status=",d.get("status"),"version=",d.get("version"),"uptime_s=",d.get("uptime_s"))
print("active=",d.get("active_providers"))
print("base=",d.get("public_base_url"))
print("help=", (d.get("help") or {}).get("html"))
' 2>/dev/null || curl -fsS "$BASE/health"
}

cmd_audit() {
  local h; h="$(auth_hdr)"
  curl -fsS "$BASE/v1/audit" -H "$h" | "$PY" -c '
import sys,json
d=json.load(sys.stdin); f=d.get("free_audit") or {}; e=d.get("efficiency") or {}; i=d.get("intelligence") or {}
print("FREE=",f.get("verdict"),"clearly_free_models=",f.get("clearly_free_models_count"))
print("cache_items=", (e.get("response_cache") or {}).get("items"), "catalog_ttl=", e.get("catalog_cache_ttl_s"))
print("smart_routing=", i.get("smart_routing"), "cooldowns=", i.get("cooldowns_active"))
print("note=", (f.get("honest_note") or "")[:220])
' 2>/dev/null || curl -fsS "$BASE/v1/audit" -H "$h"
}

cmd_search() {
  local h q="${1:-OpenAI tool calling compatibility}"; h="$(auth_hdr)"
  curl -sS -X POST "$BASE/v1/search" -H "$h" -H 'Content-Type: application/json' \
    -d "{\"query\":$(printf '%s' "$q" | "$PY" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"max_results\":3}" | \
    "$PY" -c 'import sys,json
d=json.load(sys.stdin); print("provider=",d.get("provider"),"count=",len(d.get("results") or []),"err=",str(d.get("error",""))[:120])
for r in (d.get("results") or [])[:3]: print("-", (r.get("title") or "")[:90])'
}

cmd_decision() {
  local h q="${1:-Resume en 2 bullets: que es un AI gateway OpenAI-compatible}"; h="$(auth_hdr)"
  curl -sS --max-time 120 -X POST "$BASE/v1/decision" -H "$h" -H 'Content-Type: application/json' \
    -d "{\"objective\":$(printf '%s' "$q" | "$PY" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"search\":false,\"max_tokens\":180,\"temperature\":0}" | \
    "$PY" -c 'import sys,json
d=json.load(sys.stdin); g=d.get("gateway") or {}; det=d.get("detail") or {}
print("ok=",bool(d.get("answer")),"selected=",g.get("selected") or d.get("model") or det.get("provider"))
print((d.get("answer") or det.get("message") or "")[:800])'
}

cmd_restart() {
  info "Reiniciando $SERVICE"
  systemctl --user restart "$SERVICE"; sleep 4
  systemctl --user is-active "$SERVICE" && ok "Servicio activo" || { err "Servicio no activo"; cmd_logs 40; exit 1; }
  curl -fsS -o /dev/null -w "health %{http_code} %{time_total}s\n" "$BASE/health" || warn "Health público no respondió"
}

cmd_logs() { journalctl --user -u "$SERVICE" -n "${1:-80}" --no-pager; }

cmd_public_check() {
  info "DNS / HTTPS / Gateway"
  getent ahostsv4 ia.forthtrade.com 2>&1 | awk '{print $1}' | head -1 | sed 's/^/dns ia.forthtrade.com -> /' || true
  curl -fsSI --max-time 10 https://ia.forthtrade.com/health 2>&1 | grep -Ei 'HTTP/|x-gateway-version|x-request-id' | head -4 || warn "HTTPS health falló"
  curl -fsS -o /dev/null -w "readyz %{http_code} %{time_total}s\n" "$BASE/readyz" 2>&1 || true
}

cmd_improve() {
  need_py
  info "Reporte de mejora (evidencia real)"
  local k; k="$(load_key)"; echo "key: $(mask "$k")  base: $BASE"
  hr; cmd_health || true
  hr
  if [[ -n "$k" ]]; then
    cmd_audit || true; hr
    info "Chat probe (auto)"
    curl -sS --max-time 45 "$BASE/v1/chat/completions" -H "Authorization: Bearer $k" -H 'Content-Type: application/json' \
      -d '{"model":"auto","messages":[{"role":"user","content":"Responde solo: OK"}],"max_tokens":8,"temperature":0}' | "$PY" -c '
import sys,json
d=json.load(sys.stdin); g=d.get("gateway") or {}; det=d.get("detail") or {}
c=((d.get("choices") or [{}])[0].get("message") or {}).get("content")
print("ok=",bool(c and not det),"selected=",g.get("selected") or det.get("provider"),"tries=",len(g.get("attempts") or det.get("attempts") or []))
if det: print("error=",(det.get("message") or "")[:240])
' 2>&1 || true
  else
    warn "Sin API key: omito audit/chat"
  fi
  hr
  cat <<'EOF'
Mejoras recomendadas (con evidencia):
- [Disponibilidad] Agregar claves/cuentas free-tier válidas en .env y validar /v1/providers,/v1/audit.
- [Búsqueda] TAVILY_API_KEY / BRAVE_SEARCH_API_KEY / SEARXNG_BASE_URL; DDG es best-effort/rate-limited.
- [Latencia] temperature=0 para caché, max_tokens bajo, no bombardear anónimos; /readyz para probes.
- [Tools/agentes] Probar flujos reales; ajustar por attempts/errores.
- [Seguridad] Rotar FT_AI_API_KEY si expuesta; HTTPS; no exponer claves upstream.
- [Honestidad] FREE_ONLY=gratis/controlado != ilimitado (cuotas/rate limits/capacidad).
EOF
}

cmd_all() {
  info "TODO-EN-UNO: flujo completo seguro"
  cmd_env; hr
  cmd_install; hr
  cmd_check; hr
  cmd_smoke; hr
  cmd_status; hr
  cmd_health || true; hr
  cmd_improve || true; hr
  ok "Flujo completo terminado. Revisa WARN/ERR arriba."
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  help|-h|--help) cmd_help ;;
  all) cmd_all ;;
  env) cmd_env ;;
  install) cmd_install ;;
  check) cmd_check ;;
  smoke) cmd_smoke ;;
  status) cmd_status ;;
  health) cmd_health ;;
  audit) cmd_audit ;;
  search) cmd_search "$@" ;;
  decision) cmd_decision "$@" ;;
  restart) cmd_restart ;;
  logs) cmd_logs "$@" ;;
  public-check) cmd_public_check ;;
  improve) cmd_improve ;;
  *) err "Comando desconocido: $cmd"; cmd_help; exit 1 ;;
esac
