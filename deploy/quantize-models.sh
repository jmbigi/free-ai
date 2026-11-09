#!/usr/bin/env bash
# Quantization pipeline for local models.
# Usage: ./deploy/quantize-models.sh <model_path> <target_quant> [output_dir]
# Target quants: q4_k_m, q3_k_m, q2_k, int4, int8, q8_0

set -euo pipefail

MODEL_PATH="${1:-}"
TARGET_Q="${2:-q4_k_m}"
OUTPUT_DIR="${3:-/home/kubuntu/models/quantized}"

if [[ -z "$MODEL_PATH" || ! -f "$MODEL_PATH" ]]; then
  echo "Usage: $0 <model.gguf> <target_quant> [output_dir]" >&2
  echo "Targets: q4_k_m (default), q3_k_m, q2_k, q8_0, int4, int8" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

LLAMA_QUANTIZE="/home/kubuntu/llamacpp-venv/bin/llama-quantize"
if [[ ! -x "$LLAMA_QUANTIZE" ]]; then
  # Try to find llama-quantize in llama.cpp build
  LLAMA_QUANTIZE="$(find /home/kubuntu -name llama-quantize -type f -executable 2>/dev/null | head -1)"
fi

if [[ ! -x "$LLAMA_QUANTIZE" ]]; then
  echo "llama-quantize not found. Install llama.cpp or use llama-cpp-python venv." >&2
  exit 1
fi

BASENAME="$(basename "$MODEL_PATH" .gguf)"
OUTPUT="${OUTPUT_DIR}/${BASENAME}.${TARGET_Q}.gguf"

echo "Quantizing $MODEL_PATH -> $OUTPUT (target: $TARGET_Q)"

case "$TARGET_Q" in
  q4_k_m|q3_k_m|q2_k|q8_0|q5_k_m|q6_k)
    "$LLAMA_QUANTIZE" "$MODEL_PATH" "$OUTPUT" "$TARGET_Q"
    ;;
  int4|int8)
    # INT quantization via llama.cpp (requires recent build with k-quant support)
    "$LLAMA_QUANTIZE" "$MODEL_PATH" "$OUTPUT" "IQ${TARGET_Q#int}_S"
    ;;
  *)
    echo "Unknown quantization: $TARGET_Q" >&2
    exit 1
    ;;
esac

echo "Done: $OUTPUT"
ls -lh "$OUTPUT"