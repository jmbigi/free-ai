#!/usr/bin/env bash
set -euo pipefail

# Free AI Gateway - create / operate / improve helper
# Usage: ./gateway.sh <command>
# Commands: status|health|audit|search-test|smoke|restart|logs|install|improve|help
# Security: never prints full API keys; reads FT_AI_API_KEY/API_KEY from .env or environment.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
UVICORN="$VENV/bin/uvicorn"
SERVICE="free-ai-gateway.service"
BASE="${GATEWAY_BASE_URL:-https://ia.forthtrade.com}"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }

load_key() {
  if [[ -n "${FT_AI_API_KEY:-}" ]]; then printf '%s' "$FT_AI_API_KEY"; return; fi
  if [[ -n "${API_KEY:-}" ]]; then printf '%s' "$API_KEY"; return; fi
  if [[ -f .env ]] && [[ -x "$PY" ]]; then
    "$PY" - <<'PY'
from dotenv import dotenv_values
v=dotenv_values('.env')
print((v.get('FT_AI_API_KEY') or v.get('API_KEY') or '').strip().strip('"\''))
PY
    return
  fi
  if [[ -f .env ]]; then
    awk -F= '/^(FT_AI_API_KEY|API_KEY)=/{gsub(/^[ \t"'"'"']+|[ \t"'"'"']+$/,"",$2); v=$2} END{print v}' .env
  fi
}

mask() { local s="$1"; [[ ${#s} -le 8 ]] && echo '(set)' || echo "${s:0:4}...${s: -4}"; }

need_venv() { [[ -x "$PY" ]] || { red "Missing $PY. Run: ./gateway.sh install"; exit 1; }; }

cmd_help() {
  cat <<EOF
Free AI Gateway helper ($ROOT)
Base: $BASE

Commands:
  status       Service status + local/public probes
  health       GET /health and /readyz (public)
  audit        GET /v1/audit (auth; needs FT_AI_API_KEY/API_KEY)
  smoke        Run local smoke tests
  search-test  Test /v1/search (auth)
  restart      systemctl --user restart $SERVICE
  logs         Show recent service logs
  install      Create/update .venv and install requirements
  check        py_compile + import sanity + smoke
  improve      Evidence-based improvement report (free/quota/routing/quality)
  env-example  Show key env vars (no secret values)

Client usage:
  export FT_AI_API_KEY=...   # gateway client key (not upstream)
  curl -sS $BASE/v1/chat/completions -H "Authorization: Bearer \$FT_AI_API_KEY" -H 'Content-Type: application/json' \\
    -d '{"model":"auto","messages":[{"role":"user","content":"Hola"}],"max_tokens":64,"temperature":0}'

Notes: FREE_ONLY active = gratis/controlado, no ilimitado (cuotas/rate limits/capacidad). Rotar clave si se expuso.
EOF
}

cmd_install() {
  info "Installing/updating environment"
  if [[ ! -d "$VENV" ]]; then python3 -m venv "$VENV"; fi
  "$PIP" install --upgrade pip >/dev/null
  "$PIP" install -r requirements.txt
  green "Install OK"
}

cmd_check() {
  need_venv
  info "py_compile"
  "$PY" -m py_compile app/*.py app/providers/*.py
  info "import"
  "$PY" -c "import app.main,app.router,app.search,app.knowledge; print('import ok')"
  info "smoke"
  "$PY" tests_smoke.py
  green "Check OK"
}

cmd_smoke() { need_venv; "$PY" tests_smoke.py; }

cmd_status() {
  info "systemd --user service"
  systemctl --user status "$SERVICE" --no-pager -l 2>&1 | sed -n '1,14p' || true
  echo
  info "local"
  curl -fsS -o /dev/null -w '127.0.0.1:8000/health %{http_code} %{time_total}s\n' http://127.0.0.1:8000/health 2>&1 || true
  info "public"
  curl -fsS -o /dev/null -w "$BASE/health %{http_code} %{time_total}s\n" "$BASE/health" 2>&1 || true
  curl -fsS -o /dev/null -w "$BASE/readyz %{http_code} %{time_total}s\n" "$BASE/readyz" 2>&1 || true
}

cmd_health() {
  curl -fsS "$BASE/health" | "$PY" -m json.tool 2>/dev/null || curl -fsS "$BASE/health"
}

cmd_restart() {
  info "Restarting $SERVICE"
  systemctl --user restart "$SERVICE"
  sleep 3
  systemctl --user is-active "$SERVICE"
  curl -fsS -o /dev/null -w "health %{http_code} %{time_total}s\n" "$BASE/health"
}

cmd_logs() {
  journalctl --user -u "$SERVICE" -n "${1:-80}" --no-pager
}

auth_header() {
  local key; key="$(load_key)"
  [[ -n "$key" ]] || { red "Set FT_AI_API_KEY/API_KEY in env or .env"; exit 1; }
  printf 'Authorization: Bearer %s' "$key"
}

cmd_audit() {
  local hdr; hdr="$(auth_header)"
  curl -fsS "$BASE/v1/audit" -H "$hdr" | "$PY" -m json.tool 2>/dev/null || curl -fsS "$BASE/v1/audit" -H "$hdr"
}

cmd_search_test() {
  local hdr q; hdr="$(auth_header)"; q="${1:-OpenAI tool calling compatibility}"
  curl -fsS -X POST "$BASE/v1/search" -H "$hdr" -H 'Content-Type: application/json' \
    -d "{\"query\":$(printf '%s' "$q" | "$PY" -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"max_results\":3}" | \
    "$PY" -c 'import sys,json; d=json.load(sys.stdin); print("provider=",d.get("provider"),"count=",len(d.get("results") or []),"err=",d.get("error","")); [print("-",r.get("title","")[:90]) for r in (d.get("results") or [])[:3]]'
}

cmd_improve() {
  need_venv
  info "Evidence-based improvement report"
  local key hdr
  key="$(load_key)"
  echo "gateway key: $( [[ -n "$key" ]] && mask "$key" || echo MISSING )"
  echo "base: $BASE"
  echo
  info "Live health"
  curl -fsS "$BASE/health" | "$PY" -c '
import sys,json
d=json.load(sys.stdin)
print("version=",d.get("version"),"status=",d.get("status"),"active=",d.get("active_providers"))
print("cache=",d.get("cache",{}).get("items"),"/",d.get("cache",{}).get("max_items"))
m=d.get("metrics") or {}; print("req=",m.get("requests_total"),"avg_ms=",m.get("avg_latency_ms"),"p95_ms=",m.get("p95_latency_ms"))
' 2>&1 || true
  echo
  if [[ -n "$key" ]]; then
    info "Audit (free/control/routing)"
    curl -fsS "$BASE/v1/audit" -H "Authorization: Bearer $key" | "$PY" -c '
import sys,json
d=json.load(sys.stdin)
f=d.get("free_audit") or {}; e=d.get("efficiency") or {}; i=d.get("intelligence") or {}
print("FREE verdict=",f.get("verdict"),"clearly_free_models=",f.get("clearly_free_models_count"))
print("catalog_ttl=",e.get("catalog_cache_ttl_s"),"cooldowns=",i.get("cooldowns_active"))
print("note:",(f.get("honest_note") or "")[:180])
' 2>&1 || true
    echo
    info "Chat probe (auto, low latency)"
    curl -sS --max-time 45 "$BASE/v1/chat/completions" -H "Authorization: Bearer $key" -H 'Content-Type: application/json' \
      -d '{"model":"auto","messages":[{"role":"user","content":"Responde solo: OK"}],"max_tokens":8,"temperature":0}' | "$PY" -c '
import sys,json
d=json.load(sys.stdin); g=d.get("gateway") or {}; det=d.get("detail") or {}; at=g.get("attempts") or det.get("attempts") or []
c=((d.get("choices") or [{}])[0].get("message") or {}).get("content")
print("ok=",(bool(c) and not det), "provider=",g.get("selected") or det.get("provider"), "tries=",len(at), "cache=", (g.get("cache") or {}).get("hit"))
if det: print("error:",str(det.get("message",""))[:220])
' 2>&1 || true
  fi
  echo
  info "Recommended improvements (apply with evidence)"
  cat <<'EOF'
- Quality/availability: add valid free-tier upstream keys in .env (OpenRouter :free quota, Groq/Gemini/Cloudflare/Mistral/NVIDIA/SambaNova/Cerebras/HF as available) and verify /v1/providers,/v1/audit.
- Search quality: set TAVILY_API_KEY and/or BRAVE_SEARCH_API_KEY and/or SEARXNG_BASE_URL (self-hosted JSON) for better evidence than DDG scraping; DDG is best-effort/rate-limited.
- Latency: keep temperature=0 for cacheable prompts, set max_tokens, use /health for probes, /readyz for liveness; avoid hammering free tiers (Pollinations ~45s/IP anon).
- Tools/agents: test target client tool flows; add per-provider tool capability flags and JSON schema repair only when evidence shows failures.
- Reliability: monitor /v1/metrics (auth), /v1/audit, x-request-id; rotate FT_AI_API_KEY if exposed; keep HTTPS.
- FREE_ONLY: gratis/controlado != ilimitado. Upstreams impose quotas/rate limits/credits/capacity; report real state.
EOF
}

cmd_env_example() {
  cat <<'EOF'
# Gateway client key (recommended name)
FT_AI_API_KEY=...
# Free-only control
FREE_ONLY=1
ALLOW_PAID_MODELS=0
# Optional search quality (free tiers/self-hosted)
TAVILY_API_KEY=
BRAVE_SEARCH_API_KEY=
SEARXNG_BASE_URL=
# Optional upstream providers (see .env.example)
OPENROUTER_API_KEY=
HUGGINGFACE_API_KEY=
GROQ_API_KEY=
EOF
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  help|-h|--help) cmd_help ;;
  install) cmd_install ;;
  check) cmd_check ;;
  smoke) cmd_smoke ;;
  status) cmd_status ;;
  health) cmd_health ;;
  restart) cmd_restart ;;
  logs) cmd_logs "$@" ;;
  audit) cmd_audit ;;
  search-test) cmd_search_test "$@" ;;
  improve) cmd_improve ;;
  env-example) cmd_env_example ;;
  *) red "Unknown command: $cmd"; cmd_help; exit 1 ;;
esac
