from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

_env = Path(__file__).resolve().parents[1] / ".env"

def _load_env() -> None:
    load_dotenv(_env, override=False)
    load_dotenv(override=False)

_load_env()

def _all_values() -> dict[str, str]:
    vals = {}
    try:
        vals.update({k: v for k, v in dotenv_values(_env).items() if v is not None})
    except Exception:
        pass
    vals.update({k: v for k, v in os.environ.items()})
    return vals

def _get(*names: str) -> str:
    vals = _all_values()
    for n in names:
        v = vals.get(n)
        if v is not None and str(v).strip():
            return str(v).strip().strip("'\"")
    return ""

def _get_bool(name: str, default: bool) -> bool:
    v = _get(name)
    if not v:
        return default
    return v.lower() in ('1','true','yes','on','y')

def _get_int(name: str, default: int) -> int:
    v = _get(name)
    try:
        return int(v) if v else default
    except Exception:
        return default

@dataclass
class SettingsData:
    api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    gemini_api_key: str = ""
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    nvidia_api_key: str = ""
    mistral_api_key: str = ""
    huggingface_api_key: str = ""
    together_api_key: str = ""
    sambanova_api_key: str = ""
    cohere_api_key: str = ""
    cerebras_api_key: str = ""
    deepseek_api_key: str = ""
    moonshot_api_key: str = ""
    kimi_api_key: str = ""
    opencode_api_key: str = ""
    opencode_base_url: str = ""
    openai_compatible_base_url: str = ""
    openai_compatible_api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    cache_max_items: int = 512
    context_compress_enabled: bool = True
    context_max_chars: int = 120000
    context_keep_last_messages: int = 12
    context_message_max_chars: int = 12000
    context_summary_max_chars: int = 4000

def load_settings() -> SettingsData:
    _load_env()
    return SettingsData(
        api_key=_get("API_KEY"),
        groq_api_key=_get("GROQ_API_KEY"),
        openrouter_api_key=_get("OPENROUTER_API_KEY"),
        gemini_api_key=_get("GEMINI_API_KEY","GOOGLE_API_KEY"),
        cloudflare_account_id=_get("CLOUDFLARE_ACCOUNT_ID"),
        cloudflare_api_token=_get("CLOUDFLARE_API_TOKEN","CLOUDFLARE_API_KEY"),
        nvidia_api_key=_get("NVIDIA_API_KEY","NIM_API_KEY"),
        mistral_api_key=_get("MISTRAL_API_KEY"),
        huggingface_api_key=_get("HUGGINGFACE_API_KEY","HUGGING_FACE_API_KEY","HF_TOKEN","HF_API_KEY"),
        together_api_key=_get("TOGETHER_API_KEY"),
        sambanova_api_key=_get("SAMBANOVA_API_KEY"),
        cohere_api_key=_get("COHERE_API_KEY"),
        cerebras_api_key=_get("CEREBRAS_API_KEY"),
        deepseek_api_key=_get("DEEPSEEK_API_KEY"),
        moonshot_api_key=_get("MOONSHOT_API_KEY","KIMI_API_KEY"),
        kimi_api_key=_get("KIMI_API_KEY","MOONSHOT_API_KEY"),
        opencode_api_key=_get("OPENCODE_API_KEY","OPENCODE_ZEN_API_KEY"),
        opencode_base_url=_get("OPENCODE_BASE_URL") or "https://opencode.ai/inference/openai/v1",
        openai_compatible_base_url=_get("OPENAI_COMPATIBLE_BASE_URL","CUSTOM_OPENAI_BASE_URL"),
        openai_compatible_api_key=_get("OPENAI_COMPATIBLE_API_KEY","CUSTOM_OPENAI_API_KEY"),
        host=_get("HOST") or "0.0.0.0",
        port=_get_int("PORT", 8000),
        cache_enabled=_get_bool("CACHE_ENABLED", True),
        cache_ttl_seconds=max(5, _get_int("CACHE_TTL_SECONDS", 300)),
        cache_max_items=max(16, _get_int("CACHE_MAX_ITEMS", 512)),
        context_compress_enabled=_get_bool("CONTEXT_COMPRESS_ENABLED", True),
        context_max_chars=max(4000, _get_int("CONTEXT_MAX_CHARS", 120000)),
        context_keep_last_messages=max(2, _get_int("CONTEXT_KEEP_LAST_MESSAGES", 12)),
        context_message_max_chars=max(1000, _get_int("CONTEXT_MESSAGE_MAX_CHARS", 12000)),
        context_summary_max_chars=max(500, _get_int("CONTEXT_SUMMARY_MAX_CHARS", 4000)),
    )

class _SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(load_settings(), name)
    def reload(self):
        return load_settings()

settings = _SettingsProxy()
