from __future__ import annotations
from dataclasses import dataclass
from .openai_compat import OpenAICompatProvider
from ..config import settings

def _s():  # refresh-friendly accessor
    return settings

class GroqProvider(OpenAICompatProvider):
    id = "groq"; label = "Groq (free tier when key configured)"
    base_url = "https://api.groq.com/openai/v1"
    @property
    def api_key(self): return settings.groq_api_key
    @api_key.setter
    def api_key(self, v): pass
    default_models = [
        ("llama-3.3-70b-versatile", "llama-3.3-70b-versatile", ["chat","tools"], "Groq free tier; limits vary by model/plan."),
        ("openai/gpt-oss-120b", "openai/gpt-oss-120b", ["chat"], "Groq open-weight model; check account limits."),
        ("openai/gpt-oss-20b", "openai/gpt-oss-20b", ["chat"], "Groq open-weight model; check account limits."),
        ("qwen/qwen3-32b", "qwen/qwen3-32b", ["chat"], "Groq hosted model; check account limits."),
    ]

class OpenRouterProvider(OpenAICompatProvider):
    id = "openrouter"; label = "OpenRouter (key configurada; rutas :free/auto según cuota)"
    base_url = "https://openrouter.ai/api/v1"
    extra_headers = {"HTTP-Referer": "http://localhost:8000", "X-Title": "Free AI Gateway"}
    @property
    def api_key(self): return settings.openrouter_api_key
    @api_key.setter
    def api_key(self, v): pass
    default_models = [
        ("openrouter/free", "openrouter/free", ["chat"], "Routes to available eligible free models; availability/rate limits vary."),
        ("meta-llama/llama-3.3-70b-instruct:free", "meta-llama/llama-3.3-70b-instruct:free", ["chat"], "Free variant when available."),
        ("qwen/qwen3-coder:free", "qwen/qwen3-coder:free", ["chat","tools"], "Free variant when available."),
    ]

class NvidiaProvider(OpenAICompatProvider):
    id = "nvidia"; label = "NVIDIA NIM (free tier when key configured)"
    base_url = "https://integrate.api.nvidia.com/v1"
    @property
    def api_key(self): return settings.nvidia_api_key
    @api_key.setter
    def api_key(self, v): pass
    default_models = [
        ("meta/llama-3.3-70b-instruct", "meta/llama-3.3-70b-instruct", ["chat"], "NVIDIA hosted; availability/limits may change."),
        ("nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3-super-120b-a12b", ["chat"], "NVIDIA Nemotron; availability may change."),
        ("deepseek-ai/deepseek-v3.2", "deepseek-ai/deepseek-v3.2", ["chat","reasoning"], "Hosted via NVIDIA NIM when available."),
    ]

class MistralProvider(OpenAICompatProvider):
    id = "mistral"; label = "Mistral (tier/experiment when key configured)"
    base_url = "https://api.mistral.ai/v1"
    @property
    def api_key(self): return settings.mistral_api_key
    @api_key.setter
    def api_key(self, v): pass
    default_models = [("mistral-small-latest", "mistral-small-latest", ["chat"], "Mistral model; limits depend on account plan.")]

class SambaNovaProvider(OpenAICompatProvider):
    id = "sambanova"; label = "SambaNova (free tier when key configured)"
    base_url = "https://api.sambanova.ai/v1"
    @property
    def api_key(self): return settings.sambanova_api_key
    @api_key.setter
    def api_key(self, v): pass
    default_models = [("Meta-Llama-3.3-70B-Instruct", "Meta-Llama-3.3-70B-Instruct", ["chat"], "Free tier limits apply.")]

class CerebrasProvider(OpenAICompatProvider):
    id = "cerebras"; label = "Cerebras (when key configured)"
    base_url = "https://api.cerebras.ai/v1"
    @property
    def api_key(self): return settings.cerebras_api_key
    @api_key.setter
    def api_key(self, v): pass
    default_models = [("llama-3.3-70b", "llama-3.3-70b", ["chat"], "Requires Cerebras API key; limits/credits apply.")]

class HuggingFaceProvider(OpenAICompatProvider):
    id = "huggingface"; label = "Hugging Face Router (key configurada; requiere créditos/proveedores habilitados)"
    base_url = "https://router.huggingface.co/v1"
    @property
    def api_key(self): return settings.huggingface_api_key
    @api_key.setter
    def api_key(self, v): pass
    default_models = [
        ("openai/gpt-oss-20b", "openai/gpt-oss-20b", ["chat"], "HF router; requiere créditos/proveedores habilitados en la cuenta HF."),
        ("openai/gpt-oss-120b", "openai/gpt-oss-120b", ["chat"], "HF router; requiere créditos/proveedores habilitados en la cuenta HF."),
        ("Qwen/Qwen3-Coder-480B-A35B-Instruct", "Qwen/Qwen3-Coder-480B-A35B-Instruct", ["chat","tools"], "HF router; disponibilidad según cuenta."),
    ]
    def available(self) -> bool:
        return bool(settings.huggingface_api_key and self.base_url)

class TogetherProvider(OpenAICompatProvider):
    id = "together"; label = "Together (when key configured)"
    base_url = "https://api.together.xyz/v1"
    @property
    def api_key(self): return settings.together_api_key
    @api_key.setter
    def api_key(self, v): pass
    default_models = []

class CohereProvider(OpenAICompatProvider):
    id = "cohere"; label = "Cohere compatibility (when key configured)"
    base_url = "https://api.cohere.ai/compatibility/v1"
    @property
    def api_key(self): return settings.cohere_api_key
    @api_key.setter
    def api_key(self, v): pass
    default_models = [("command-r7b-12-2024", "command-r7b-12-2024", ["chat"], "Cohere compatibility endpoint; trial limits apply.")]
