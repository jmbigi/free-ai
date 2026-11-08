from __future__ import annotations
from .openai_compat import OpenAICompatProvider
from ..config import settings

class _S(OpenAICompatProvider):
    @property
    def api_key(self): return ""
    @api_key.setter
    def api_key(self, v): pass

class GroqProvider(_S):
    id = "groq"; label = "Groq (free tier when key configured)"
    base_url = "https://api.groq.com/openai/v1"
    @property
    def api_key(self): return settings.groq_api_key
    default_models = [
        ("llama-3.3-70b-versatile", "llama-3.3-70b-versatile", ["chat","tools"], "Groq free tier; limits vary by model/plan."),
        ("openai/gpt-oss-120b", "openai/gpt-oss-120b", ["chat"], "Groq open-weight model; check account limits."),
        ("openai/gpt-oss-20b", "openai/gpt-oss-20b", ["chat"], "Groq open-weight model; check account limits."),
        ("qwen/qwen3-32b", "qwen/qwen3-32b", ["chat"], "Groq hosted model; check account limits."),
    ]

class OpenRouterProvider(_S):
    id = "openrouter"; label = "OpenRouter (key configurada; rutas :free/auto según cuota)"
    base_url = "https://openrouter.ai/api/v1"
    extra_headers = {"HTTP-Referer": "http://localhost:8000", "X-Title": "Free AI Gateway"}
    @property
    def api_key(self): return settings.openrouter_api_key

    async def list_models(self):
        base = await super().list_models()
        seen = {m.upstream_model for m in base}
        if not self.available():
            return base
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(f"{self.base_url}/models", headers=self._headers())
                if r.status_code == 200:
                    for m in (r.json().get('data') or []):
                        mid = (m.get('id') or '').strip()
                        if not mid or ':free' not in mid or mid in seen:
                            continue
                        seen.add(mid)
                        caps = ['chat']
                        name = (m.get('name') or mid).lower()
                        if 'coder' in name or 'code' in name or 'tool' in str(m.get('supported_parameters') or []):
                            caps.append('tools')
                        from .base import ModelInfo
                        base.append(ModelInfo(id=f"{self.id}/{mid}", provider=self.id, owned_by=(m.get('owned_by') or self.id), upstream_model=mid, capabilities=caps, note='OpenRouter :free discovered from /models (quota/rate limits/capacity vary).'))
        except Exception as e:
            import logging
            logging.getLogger("free-ai.providers").warning("OpenRouter :free discovery failed: %s", e)
        return base

    default_models = [
        ("openrouter/free", "openrouter/free", ["chat"], "Routes to available eligible free models; availability/rate limits vary."),
        ("meta-llama/llama-3.3-70b-instruct:free", "meta-llama/llama-3.3-70b-instruct:free", ["chat","tools"], "Free variant when available."),
        ("qwen/qwen3-coder:free", "qwen/qwen3-coder:free", ["chat","tools"], "Free variant when available."),
        ("google/gemma-3-27b-it:free", "google/gemma-3-27b-it:free", ["chat","tools"], "Free variant when available."),
        ("google/gemma-4-31b-it:free", "google/gemma-4-31b-it:free", ["chat","tools"], "OpenRouter :free (verified in /models catalog when key configured)."),
        ("google/gemma-4-26b-a4b-it:free", "google/gemma-4-26b-a4b-it:free", ["chat","tools"], "OpenRouter :free (availability/rate limits vary)."),
        ("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", ["chat","reasoning"], "OpenRouter :free; limits vary."),
        ("liquid/lfm-2.5-2.6b:free", "liquid/lfm-2.5-2.6b:free", ["chat"], "OpenRouter :free small model; limits vary."),
    ]

class NvidiaProvider(_S):
    id = "nvidia"; label = "NVIDIA NIM (free tier when key configured)"
    base_url = "https://integrate.api.nvidia.com/v1"
    @property
    def api_key(self): return settings.nvidia_api_key
    default_models = [
        ("meta/llama-3.3-70b-instruct", "meta/llama-3.3-70b-instruct", ["chat"], "NVIDIA hosted; availability/limits may change."),
        ("nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3-super-120b-a12b", ["chat"], "NVIDIA Nemotron; availability may change."),
        ("deepseek-ai/deepseek-v3.2", "deepseek-ai/deepseek-v3.2", ["chat","reasoning"], "Hosted via NVIDIA NIM when available."),
    ]

class MistralProvider(_S):
    id = "mistral"; label = "Mistral (tier/experiment when key configured)"
    base_url = "https://api.mistral.ai/v1"
    @property
    def api_key(self): return settings.mistral_api_key
    default_models = [("mistral-small-latest", "mistral-small-latest", ["chat"], "Mistral model; limits depend on account plan.")]

class SambaNovaProvider(_S):
    id = "sambanova"; label = "SambaNova (free tier when key configured)"
    base_url = "https://api.sambanova.ai/v1"
    @property
    def api_key(self): return settings.sambanova_api_key
    default_models = [("Meta-Llama-3.3-70B-Instruct", "Meta-Llama-3.3-70B-Instruct", ["chat"], "Free tier limits apply.")]

class CerebrasProvider(_S):
    id = "cerebras"; label = "Cerebras (when key configured)"
    base_url = "https://api.cerebras.ai/v1"
    @property
    def api_key(self): return settings.cerebras_api_key
    default_models = [("llama-3.3-70b", "llama-3.3-70b", ["chat"], "Requires Cerebras API key; limits/credits apply.")]

class HuggingFaceProvider(_S):
    id = "huggingface"; label = "Hugging Face Router (key configurada; requiere créditos/proveedores habilitados)"
    base_url = "https://router.huggingface.co/v1"
    @property
    def api_key(self): return settings.huggingface_api_key
    default_models = [
        ("openai/gpt-oss-20b", "openai/gpt-oss-20b", ["chat"], "HF router; requiere créditos/proveedores habilitados en la cuenta HF."),
        ("openai/gpt-oss-120b", "openai/gpt-oss-120b", ["chat"], "HF router; requiere créditos/proveedores habilitados en la cuenta HF."),
        ("Qwen/Qwen3-Coder-480B-A35B-Instruct", "Qwen/Qwen3-Coder-480B-A35B-Instruct", ["chat","tools"], "HF router; disponibilidad según cuenta."),
    ]

class TogetherProvider(_S):
    id = "together"; label = "Together (when key configured)"
    base_url = "https://api.together.xyz/v1"
    @property
    def api_key(self): return settings.together_api_key
    default_models = []

class CohereProvider(_S):
    id = "cohere"; label = "Cohere compatibility (when key configured)"
    base_url = "https://api.cohere.ai/compatibility/v1"
    @property
    def api_key(self): return settings.cohere_api_key
    default_models = [("command-r7b-12-2024", "command-r7b-12-2024", ["chat"], "Cohere compatibility endpoint; trial limits apply.")]

class DeepSeekProvider(_S):
    id = "deepseek"; label = "DeepSeek official API (when key configured; pay-as-you-go/credits)"
    base_url = "https://api.deepseek.com"
    @property
    def api_key(self): return settings.deepseek_api_key
    default_models = [
        ("deepseek-flash", "deepseek-flash", ["chat","reasoning"], "DeepSeek official model; requires DeepSeek API key/balance."),
        ("deepseek-v4-pro", "deepseek-v4-pro", ["chat","reasoning"], "DeepSeek official model; requires DeepSeek API key/balance."),
    ]

class MoonshotProvider(_S):
    id = "moonshot"; label = "Moonshot/Kimi Open Platform (OpenAI-compatible; when key configured)"
    base_url = "https://api.moonshot.ai/v1"
    extra_headers = {}
    @property
    def api_key(self): return settings.moonshot_api_key or settings.kimi_api_key
    default_models = [
        ("kimi-k3.1-pro", "kimi-k3.1-pro", ["chat"], "Moonshot/Kimi Open Platform model; account access/quota applies."),
        ("kimi-k2.5", "kimi-k2.5", ["chat"], "Moonshot/Kimi model id (availability depends on account)."),
    ]

class OpenCodeProvider(_S):
    id = "opencode"; label = "OpenCode inference (when key configured; free/paid availability may vary)"
    @property
    def base_url(self): return settings.opencode_base_url or "https://opencode.ai/inference/openai/v1"
    @property
    def api_key(self): return settings.opencode_api_key
    default_models = [
        ("big-pickle", "big-pickle", ["chat"], "OpenCode model; access/limits depend on OpenCode account/product and may rotate."),
        ("deepseek-v4.1-flash-free", "deepseek-v4.1-flash-free", ["chat"], "OpenCode free-tier model when available; may be app/region/rotation limited."),
        ("glm-5.3-flash-free", "glm-5.3-flash-free", ["chat"], "OpenCode free-tier model when available; may rotate."),
    ]

class GenericOpenAIProvider(_S):
    id = "openai-compatible"; label = "Custom OpenAI-compatible upstream (BASE_URL+API_KEY)"
    @property
    def base_url(self): return settings.openai_compatible_base_url
    @property
    def api_key(self): return settings.openai_compatible_api_key
    default_models = [
        ("default", "gpt-4o-mini", ["chat"], "Pass a concrete model id as openai-compatible/<model> when using a custom upstream."),
    ]


class LLM7Provider(_S):
    """LLM7.io - key optional (best-effort). Free availability/rate limits/model rotation vary; verify before relying."""
    id = "llm7"; label = "LLM7 (key opcional; best-effort, disponibilidad/capacidad free varía)"
    @property
    def base_url(self): return getattr(settings,'llm7_base_url',None) or 'https://api.llm7.io/v1'
    @property
    def api_key(self): return getattr(settings,'llm7_api_key','') or 'unused'
    def available(self): return True  # key optional; actual availability verified per request
    default_models = [
        ("default", "default", ["chat"], "LLM7 default route; availability/rate limits vary."),
    ]
    async def list_models(self):
        # try discover; keep conservative
        try:
            base = await super().list_models()
            if base: return base
        except Exception as e:
            import logging
            logging.getLogger("free-ai.providers").warning("LLM7 list_models failed: %s", e)
        return [__import__('app.providers.base',fromlist=['ModelInfo']).ModelInfo(id=f"{self.id}/default", provider=self.id, owned_by=self.id, upstream_model="default", capabilities=["chat"], note="LLM7 key-optional endpoint; model availability/rate limits may vary.")]
