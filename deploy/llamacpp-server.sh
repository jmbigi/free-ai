#!/usr/bin/env bash
# Optional local llama-cpp-python OpenAI-compatible server.
# The gateway provider `local-llamacpp` talks to this endpoint.
# This script does not start/enable anything by itself; the operator decides.
set -euo pipefail

VENV="${LLAMACPP_VENV:-/home/kubuntu/llamacpp-venv}"
MODEL_PATH="${LLAMACPP_MODEL_PATH:-}"
if [[ -z "$MODEL_PATH" ]]; then
  OLLAMA_MODEL="${LLAMACPP_OLLAMA_MODEL:-qwen3-coder-opt:latest}"
  MODEL_PATH="$(ollama show "$OLLAMA_MODEL" --modelfile 2>/dev/null | awk '/^FROM /{print $2; exit}')"
fi
if [[ -z "$MODEL_PATH" || ! -f "$MODEL_PATH" ]]; then
  echo "llamacpp-server: GGUF model not found; set LLAMACPP_MODEL_PATH" >&2
  exit 2
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "llamacpp-server: Python venv not found at $VENV" >&2
  exit 2
fi

exec "$VENV/bin/python" -m llama_cpp.server \
  --model "$MODEL_PATH" \
  --model_alias "${LOCAL_LLAMACPP_MODEL:-qwen3-coder-opt}" \
  --host "${LLAMACPP_HOST:-127.0.0.1}" \
  --port "${LLAMACPP_PORT:-11438}" \
  --n_gpu_layers "${LLAMACPP_N_GPU_LAYERS:-12}" \
  --n_ctx "${LLAMACPP_N_CTX:-16384}" \
  --n_batch "${LLAMACPP_N_BATCH:-512}" \
  --n_ubatch "${LLAMACPP_N_UBATCH:-256}" \
  --n_threads "${LLAMACPP_N_THREADS:-8}" \
  --n_threads_batch "${LLAMACPP_N_THREADS_BATCH:-8}" \
  --offload_kqv "${LLAMACPP_OFFLOAD_KQV:-true}" \
  --flash_attn "${LLAMACPP_FLASH_ATTN:-true}" \
  --type_k "${LLAMACPP_TYPE_K:-8}" \
  --type_v "${LLAMACPP_TYPE_V:-8}" \
  --verbose "${LLAMACPP_VERBOSE:-false}"
