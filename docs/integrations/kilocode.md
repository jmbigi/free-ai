# KiloCode Integration Guide

## Overview

KiloCode (kilo.ai) is an open-source AI coding agent (MIT license) that supports **OpenAI-compatible endpoints**. The Free AI Gateway is fully compatible with KiloCode's requirements.

## Gateway Compatibility Checklist

| Requirement | Status | Details |
|---|---|---|
| **OpenAI-compatible `/v1/chat/completions`** | ✅ | Full support with streaming SSE |
| **`/v1/models` endpoint** | ✅ | Returns `{"object":"list","data":[...]}` |
| **Multiple auth methods** | ✅ | `Authorization: Bearer`, `api-key`, `x-api-key`, `?key=` |
| **Tool calling** | ✅ | OpenAI `tool_calls` format, supports parallel |
| **Streaming SSE** | ✅ | `stream=true` returns proper SSE chunks |
| **Model aliases** | ✅ | `auto`, `local-ollama/...`, `openrouter/...:free`, etc. |
| **Free-tier models** | ✅ | 23+ free models via `/v1/free` |
| **Local models** | ✅ | Ollama, llama-cpp-python, NCM |

---

## Quick Setup for KiloCode

### 1. Gateway Configuration

Add to your `.env`:
```bash
# Gateway API key (single key for all clients)
API_KEY=your-strong-random-key
FT_AI_API_KEY=your-strong-random-key

# Enable local models (optional)
LOCAL_OLLAMA_ENABLED=1
LOCAL_OLLAMA_MODEL=qwen3-coder-opt:latest
LOCAL_OLLAMA_CTX=16384

# Free-only mode (default)
FREE_ONLY=1
```

### 2. KiloCode Configuration

In KiloCode settings (VS Code / JetBrains / CLI), add a **Custom OpenAI-Compatible Provider**:

```json
{
  "$schema": "https://kilo.ai/schemas/provider.json",
  "model": "auto",
  "provider": {
    "openai-compatible": {
      "options": {
        "baseURL": "https://ia.forthtrade.com/v1",
        "apiKey": "${env:FREE_AI_API_KEY}"
      },
      "models": {
        "auto": {
          "name": "Free AI Gateway (Auto)",
          "tool_call": true,
          "limit": { "context": 128000, "output": 16384 }
        },
        "local-ollama/qwen3-coder-opt:latest": {
          "name": "Local Qwen3-Coder (Ollama)",
          "tool_call": true,
          "limit": { "context": 16384, "output": 4096 }
        },
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free": {
          "name": "Nemotron 3 Ultra (Cloud Free)",
          "tool_call": true,
          "reasoning": true,
          "limit": { "context": 128000, "output": 32768 }
        }
      }
    }
  }
}
```

### 3. CLI Usage

```bash
# Set API key
export FREE_AI_API_KEY=your-key

# Use with KiloCode CLI
kilo -m free-ai-gateway/auto -p "Write a Python function to..."
```

---

## Supported Models for KiloCode

| Model ID | Provider | Tool Calling | Context | Notes |
|---|---|---|---|---|
| `auto` | Gateway (smart routing) | ✅ | 128k | Best free model selected automatically |
| `local-ollama/qwen3-coder-opt:latest` | Ollama (local) | ✅ | 16k | Best local coding model |
| `local-llamacpp/qwen3-coder-opt` | llama-cpp-python (local) | ✅ | 16k | Opt-in, slower |
| `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter (cloud) | ✅ | 128k | Best reasoning, cuotas variables |
| `openrouter/qwen/qwen3-coder:free` | OpenRouter (cloud) | ✅ | 32k | Good coding, cuotas variables |
| `pollinations/openai-fast` | Pollinations (anon) | ✅ | 32k | Anónimo, rate-limited 45s/IP |
| `ncm-instruct/ncm-instruct-725m` | NCM (local) | ❌ | 128 | Experimental, math guard |

---

## Advanced: MCP Integration (Sprint 1)

The gateway exposes an **MCP server** for native KiloCode tool integration:

```bash
# Start MCP server (stdio transport for KiloCode)
python -m app.mcp.server stdio
```

In KiloCode config, add MCP transport:
```json
{
  "mcp": {
    "command": "python",
    "args": ["-m", "app.mcp.server", "stdio"],
    "env": {
      "FREE_AI_API_KEY": "${env:FREE_AI_API_KEY}",
      "MCP_TOOLS_ROOT": "/tmp/mcp-tools"
    }
  }
}
```

This gives KiloCode direct access to:
- `web_search` - Real-time web search
- `code_exec` - Sandboxed Python execution
- `file_read` / `file_write` - Workspace file ops
- `kb_query` - Gateway knowledge base

---

## Verification

Test the gateway with curl:
```bash
# Health check
curl https://ia.forthtrade.com/health

# List models
curl -H "Authorization: Bearer $FREE_AI_API_KEY" https://ia.forthtrade.com/v1/models

# Chat completion
curl -X POST https://ia.forthtrade.com/v1/chat/completions \
  -H "Authorization: Bearer $FREE_AI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello"}],"max_tokens":50}'

# With tool calling
curl -X POST https://ia.forthtrade.com/v1/chat/completions \
  -H "Authorization: Bearer $FREE_AI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"local-ollama/qwen3-coder-opt:latest","messages":[{"role":"user","content":"Use write_file to create test.txt"}],"tools":[{"type":"function","function":{"name":"write_file","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}}]}'
```

---

## Limitations & Honest Notes

1. **Free ≠ Unlimited**: Cloud providers (OpenRouter, Pollinations) have rate limits, daily quotas, and capacity limits.
2. **Local models need hardware**: Ollama/llama-cpp-python require GPU VRAM (8GB+ recommended for 30B models).
3. **NCM-Instruct**: 128-token fixed context, CC BY-NC-SA 4.0 (non-commercial), experimental only.
4. **Nemotron free**: OpenRouter free tier has daily limits (429 `free-models-per-day`) and cooldowns (402 45s/IP).
5. **No vendor lock-in**: Gateway is OpenAI-compatible; switch providers anytime.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `401 Unauthorized` | Check `FREE_AI_API_KEY` matches gateway `.env` |
| `403 Forbidden` | `FREE_ONLY=1` blocks non-free models; use `:free` or local |
| `429 Rate Limited` | Wait or switch provider; gateway has circuit breaker |
| `502 Bad Gateway` | Upstream failed; check `/v1/audit` for provider status |
| Models not appearing in KiloCode | Ensure `/v1/models` returns `object: list` with `data` array |

---

## References

- [KiloCode Documentation](https://kilo.ai/docs)
- [Free AI Gateway README](../README.md)
- [MCP Server Implementation](../app/mcp/server.py)
- [Local Model Setup](../docs/progress/2026-11-09-llamacpp-tools.md)