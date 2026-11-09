#!/bin/bash
KEY="682499c35eaf5e9aa581bc4f60cadec5e4d9f780053e31dfda2e08adfa37e23d"
PROMPT=$(cat /home/kubuntu/free-ai/comparison_test/prompt.txt)

RESPONSE=$(curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"local-ollama/qwen3-coder-opt:latest\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}],\"temperature\":0,\"max_tokens\":2000,\"cache\":false}")

echo "$RESPONSE" | python3 -c "
import json, sys
data = json.load(sys.stdin)
content = data.get('choices',[{}])[0].get('message',{}).get('content','')
gateway = data.get('gateway',{})
print('=== OLLAMA RESPONSE ===')
print(f'Model: {data.get(\"model\")}')
print(f'Gateway model: {gateway.get(\"selected\")}')
print(f'Latency: {gateway.get(\"attempts\",[{}])[-1].get(\"ms\")}ms')
print(f'Finish: {data.get(\"choices\",[{}])[0].get(\"finish_reason\")}')
print(f'Content:')
print(content)
print('=== END OLLAMA ===')
" > /home/kubuntu/free-ai/comparison_test/ollama_response.txt 2>&1
