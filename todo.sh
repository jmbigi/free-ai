#!/usr/bin/env bash
set -euo pipefail
# Free AI Gateway - TODO-EN-UNO
# ./todo.sh [all|env|install|check|smoke|status|health|audit|search|decision|restart|logs|public-check|improve|help]
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"
VENV="$ROOT/.venv"; PY="$VENV/bin/python"; PIP="$VENV/bin/pip"
SERVICE="free-ai-gateway.service"; BASE="${GATEWAY_BASE_URL:-https://ia.forthtrade.com}"; LOCAL="http://127.0.0.1:${PORT:-8000}"
c(){ printf '\033[%sm%s\033[0m\n' "$1" "$2"; }; info(){ c '36;1' "==> $*"; }; ok(){ c '32;1' "OK: $*"; }; warn(){ c '33;1' "WARN: $*"; }; err(){ c '31;1' "ERR: $*"; }; hr(){ printf '%s\n' '------------------------------------------------------------'; }
need_py(){ [[ -x "$PY" ]] || { err "Falta $PY. Ejecuta: ./todo.sh install"; exit 1; }; }
load_key(){
  [[ -n "${FT_AI_API_KEY:-}" ]] && { printf '%s' "$FT_AI_API_KEY"; return; }
  [[ -n "${API_KEY:-}" ]] && { printf '%s' "$API_KEY"; return; }
  [[ -f .env && -x "$PY" ]] && "$PY" - <<'PY'
from dotenv import dotenv_values
v=dotenv_values('.env')
print((v.get('FT_AI_API_KEY') or v.get('API_KEY') or '').strip().strip('\'"'))
PY
}
mask(){ local s="${1:-}"; [[ -z "$s" ]] && echo MISSING || { [[ ${#s} -le 8 ]] && echo SET || echo "${s:0:4}...${s: -4}"; }; }
auth_hdr(){ local k; k="$(load_key)"; [[ -n "$k" ]] || { err "Define FT_AI_API_KEY/API_KEY en entorno o .env"; exit 1; }; printf 'Authorization: Bearer %s' "$k"; }
cmd_help(){ cat <<'EOF'
Uso: ./todo.sh <comando>
  all            env+install+check+smoke+status+health+improve (seguro)
  env            Crea .env desde .env.example si falta (NO sobreescribe)
  install        venv + requirements
  check          py_compile + imports
  smoke          tests_smoke.py
  status         systemd --user + probes local/público
  health         /health resumido
  audit          /v1/audit (auth)
  search "q"     /v1/search (auth)
  decision "q"   /v1/decision (auth, search:false por defecto)
  restart        reinicia free-ai-gateway.service
  logs [N]       logs del servicio
  public-check   DNS/HTTPS/readyz
  improve        reporte con evidencia
  code-test [q]  prueba de generación de código (evidencia, respeta rate limits)
  project-gen "prompt" [name]  ForthTrade IA genera proyecto temporal (extrae ### FILE, borra temp)
Cliente: export FT_AI_API_KEY=... ; Base https://ia.forthtrade.com/v1 ; model auto
Nota: FREE_ONLY=gratis/controlado != ilimitado. Rotar FT_AI_API_KEY si se expuso.
EOF
}
cmd_env(){
  if [[ -f .env ]]; then ok ".env existe (no modificado)"; else
    [[ -f .env.example ]] || { err "Falta .env.example"; exit 1; }
    cp .env.example .env
    if command -v openssl >/dev/null 2>&1 && grep -q 'change-this' .env; then
      K="$(openssl rand -hex 32)"
      python3 - "$K" <<'PYK'
import sys
from pathlib import Path
k=sys.argv[1]; p=Path('.env'); t=p.read_text()
for n in ('API_KEY','FT_AI_API_KEY'):
    t=t.replace(f'{n}=change-this-to-a-strong-random-key', f'{n}={k}')
p.write_text(t)
PYK
      ok "Generada API key gateway en .env (revísala/respáldala con seguridad)"
    else
      warn "Edita API_KEY/FT_AI_API_KEY en .env"
    fi
    ok "Creado .env desde .env.example"
  fi
  local k; k="$(load_key)"; info "API key gateway: $(mask "$k")"
}
cmd_install(){ info "Instalando"; command -v python3 >/dev/null || { err "python3 no encontrado"; exit 1; }; [[ -d "$VENV" ]] || python3 -m venv "$VENV"; "$PIP" install --upgrade pip >/dev/null; "$PIP" install -r requirements.txt; ok "Instalado"; }
cmd_check(){ need_py; info "py_compile"; "$PY" -m py_compile app/*.py app/providers/*.py; info "imports"; "$PY" -c "import app.main,app.router,app.auth,app.cache,app.context,app.search,app.knowledge,app.tool_support,app.observability,app.help_page; print('imports ok')"; ok "Check OK"; }
cmd_smoke(){ need_py; "$PY" tests_smoke.py; ok "Smoke OK"; }
cmd_status(){ info "systemd --user"; systemctl --user status "$SERVICE" --no-pager -l 2>&1 | sed -n '1,12p' || warn "sin estado"; hr; curl -fsS -o /dev/null -w "local  health %{http_code} %{time_total}s\n" "$LOCAL/health" 2>&1 || warn "local falló"; curl -fsS -o /dev/null -w "public health %{http_code} %{time_total}s\n" "$BASE/health" 2>&1 || warn "public falló"; curl -fsS -o /dev/null -w "public readyz %{http_code} %{time_total}s\n" "$BASE/readyz" 2>&1 || true; }
cmd_health(){ curl -fsS "$BASE/health" | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print("status=",d.get("status"),"version=",d.get("version"),"active=",d.get("active_providers"),"base=",d.get("public_base_url"))' 2>/dev/null || curl -fsS "$BASE/health"; }
cmd_audit(){ local h; h="$(auth_hdr)"; curl -fsS "$BASE/v1/audit" -H "$h" | "$PY" -c 'import sys,json; d=json.load(sys.stdin); f=d.get("free_audit") or {}; print("FREE=",f.get("verdict"),"clearly_free=",f.get("clearly_free_models_count")); print((f.get("honest_note") or "")[:220])' 2>/dev/null || curl -fsS "$BASE/v1/audit" -H "$h"; }
cmd_search(){ local h q="${1:-OpenAI tool calling}"; h="$(auth_hdr)"; curl -sS -X POST "$BASE/v1/search" -H "$h" -H 'Content-Type: application/json' -d "{\"query\":$(printf '%s' "$q" | "$PY" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"max_results\":3}" | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print("provider=",d.get("provider"),"count=",len(d.get("results") or [])); [print("-",r.get("title","")[:90]) for r in (d.get("results") or [])[:3]]'; }
cmd_decision(){ local h q="${1:-Resume que es un AI gateway OpenAI-compatible}"; h="$(auth_hdr)"; curl -sS --max-time 120 -X POST "$BASE/v1/decision" -H "$h" -H 'Content-Type: application/json' -d "{\"objective\":$(printf '%s' "$q" | "$PY" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"search\":false,\"max_tokens\":160,\"temperature\":0}" | "$PY" -c 'import sys,json; d=json.load(sys.stdin); g=d.get("gateway") or {}; det=d.get("detail") or {}; print("ok=",bool(d.get("answer")),"selected=",g.get("selected") or det.get("provider")); print((d.get("answer") or det.get("message") or "")[:700])'; }
cmd_restart(){ info "Reiniciando $SERVICE"; systemctl --user restart "$SERVICE"; sleep 4; systemctl --user is-active "$SERVICE" && ok "Activo" || { err "No activo"; cmd_logs 40; exit 1; }; curl -fsS -o /dev/null -w "health %{http_code} %{time_total}s\n" "$BASE/health" || warn "health público falló"; }
cmd_logs(){ journalctl --user -u "$SERVICE" -n "${1:-80}" --no-pager; }
cmd_public_check(){ getent ahostsv4 ia.forthtrade.com 2>&1 | awk '{print $1}' | head -1 | sed 's/^/dns ia.forthtrade.com -> /' || true; curl -fsSI --max-time 10 https://ia.forthtrade.com/health 2>&1 | grep -Ei 'HTTP/|x-gateway-version|x-request-id' | head -4 || warn "HTTPS falló"; curl -fsS -o /dev/null -w "readyz %{http_code} %{time_total}s\n" "$BASE/readyz" 2>&1 || true; }

cmd_improve(){ need_py; local k; k="$(load_key)"; info "Reporte mejora (evidencia) key=$(mask "$k")"; hr; cmd_health || true; hr; if [[ -n "$k" ]]; then cmd_audit || true; hr; info "Chat probe"; curl -sS --max-time 45 "$BASE/v1/chat/completions" -H "Authorization: Bearer $k" -H 'Content-Type: application/json' -d '{"model":"auto","messages":[{"role":"user","content":"Responde solo: OK"}],"max_tokens":8,"temperature":0}' | "$PY" -c 'import sys,json; d=json.load(sys.stdin); g=d.get("gateway") or {}; det=d.get("detail") or {}; c=((d.get("choices") or [{}])[0].get("message") or {}).get("content"); print("ok=",bool(c and not det),"selected=",g.get("selected") or det.get("provider"),"tries=",len(g.get("attempts") or det.get("attempts") or []));
if det: print("error=",(det.get("message") or "")[:200])' 2>&1 || true; fi; hr; cat <<'EOF'
Mejoras (con evidencia): agregar claves free-tier válidas en .env; TAVILY/BRAVE/SEARXNG para búsqueda; temperature=0+max_tokens para latencia/caché; monitorear /v1/metrics,/v1/audit; rotar FT_AI_API_KEY si expuesta; HTTPS. FREE_ONLY=gratis/controlado != ilimitado.
EOF
}
cmd_code_test(){
  local h q="${1:-Escribe una función Python `clamp(x, lo, hi)` con type hints y docstring breve. Devuelve solo código.}"; h="$(auth_hdr)"
  info "Code-gen probe (temperature=0, auto; puede fallar por cuotas free)"
  curl -sS --max-time 90 -X POST "$BASE/v1/chat/completions" -H "$h" -H 'Content-Type: application/json' \
    -d "{\"model\":\"auto\",\"temperature\":0,\"max_tokens\":350,\"messages\":[{\"role\":\"user\",\"content\":$(printf '%s' "$q" | "$PY" -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}]}" | \
    "$PY" -c 'import sys,json
try:
 d=json.load(sys.stdin); g=d.get("gateway") or {}; det=d.get("detail") or {}; c=((d.get("choices") or [{}])[0].get("message") or {}).get("content")
 print("ok=",bool(c and not det),"selected=",g.get("selected") or d.get("model"),"tries=",len(g.get("attempts") or det.get("attempts") or []))
 if det: print("error=",(det.get("message") or "")[:280])
 if c: print("---\n"+c[:4000])
except Exception as e: print("probe_error=",e)
'
}

cmd_project_gen(){
  local h q="${1:-Genera mini proyecto Python con ### FILE: main.py y ### FILE: README.md}" name="${2:-tmp-project}"; h="$(auth_hdr)"
  info "Project generation via gateway (FREE_ONLY; rate limits apply; temp deleted by default)"
  curl -sS --max-time 240 -X POST "$BASE/v1/projects/generate" -H "$h" -H 'Content-Type: application/json' \
    -d "{\"name\":$(printf '%s' "$name" | "$PY" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"prompt\":$(printf '%s' "$q" | "$PY" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"model\":\"auto\",\"temperature\":0,\"max_tokens\":1800,\"max_retries\":2,\"retry_delay_s\":55,\"keep_temp\":false}" | \
    "$PY" -c 'import sys,json
try:
 d=json.load(sys.stdin); print("status=",d.get("status"),"ok=",d.get("ok"),"selected=",d.get("selected"),"files_extracted=",d.get("files_extracted"))
 print("files=",json.dumps(d.get("files") or [],ensure_ascii=False))
 if d.get("detail"): print("detail=",json.dumps(d.get("detail"),ensure_ascii=False)[:300])
 if d.get("content_preview"): print("---\n"+(d.get("content_preview") or "")[:2500])
except Exception as e: print("probe_error=",e)
'
}

cmd_all(){ info "TODO-EN-UNO"; cmd_env; hr; cmd_install; hr; cmd_check; hr; cmd_smoke; hr; cmd_status; hr; cmd_health || true; hr; cmd_improve || true; hr; ok "Completo. Revisa WARN/ERR."; }
cmd="${1:-help}"; shift || true
case "$cmd" in help|-h|--help) cmd_help;; all) cmd_all;; env) cmd_env;; install) cmd_install;; check) cmd_check;; smoke) cmd_smoke;; status) cmd_status;; health) cmd_health;; audit) cmd_audit;; search) cmd_search "$@";; decision) cmd_decision "$@";; restart) cmd_restart;; logs) cmd_logs "$@";; public-check) cmd_public_check;; improve) cmd_improve;; *) err "Comando desconocido: $cmd"; cmd_help; exit 1;; esac
