from __future__ import annotations
import os
from pathlib import Path
from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"
_env = ENV_FILE  # backward compat for auth/app code expecting _env
load_dotenv(ENV_FILE, override=False)


def _read_env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    try:
        data = dotenv_values(ENV_FILE)
        # direct match first
        for k in (name, name.upper(), name.lower()):
            if k in data and data[k] is not None and str(data[k]).strip() != "":
                return str(data[k]).strip()
        aliases = {
            'HUGGINGFACE_API_KEY': ['HUGGING_FACE_API_KEY', 'HF_API_KEY', 'HF_TOKEN'],
            'HUGGING_FACE_API_KEY': ['HUGGINGFACE_API_KEY', 'HF_API_KEY', 'HF_TOKEN'],
            'GROQ_API_KEY': ['GROQ_KEY'],
            'OPENROUTER_API_KEY': ['OPENROUTER_KEY'],
            'GEMINI_API_KEY': ['GOOGLE_API_KEY', 'GOOGLE_AI_STUDIO_KEY'],
            'MOONSHOT_API_KEY': ['KIMI_API_KEY', 'KIMI_K2_API_KEY', 'MOONSHOT_KEY'],
            'KIMI_API_KEY': ['MOONSHOT_API_KEY', 'KIMI_K2_API_KEY'],
            'DEEPSEEK_API_KEY': ['DEEPSEEK_KEY'],
            'OPENCODE_API_KEY': ['OPENCODE_KEY'],
            'CUSTOM_OPENAI_API_KEY': ['OPENAI_COMPATIBLE_API_KEY', 'GENERIC_OPENAI_API_KEY'],
            'CUSTOM_OPENAI_BASE_URL': ['OPENAI_COMPATIBLE_BASE_URL', 'GENERIC_OPENAI_BASE_URL'],
            'CUSTOM_OPENAI_MODELS': ['OPENAI_COMPATIBLE_MODELS', 'GENERIC_OPENAI_MODELS'],
        }
        for alias in aliases.get(name, []):
            for k in (alias, alias.upper(), alias.lower()):
                if k in data and data[k] is not None and str(data[k]).strip() != "":
                    return str(data[k]).strip()
    except Exception as e:
        import logging
        logging.getLogger("free-ai.config").warning("_read_env(%s) alias lookup failed: %s", name, e)
    return default


def _read_bool(name: str, default: bool) -> bool:
    raw = _read_env(name, "1" if default else "0").lower()
    return raw in ("1", "true", "yes", "on")


def _read_int(name: str, default: int) -> int:
    try:
        return int(float(_read_env(name, str(default))))
    except Exception:
        return default


class SettingsProxy:
    @property
    def api_key(self) -> str:
        # Client gateway key: accept common env names for easy integration.
        return _read_env("API_KEY", "") or _read_env("FT_AI_API_KEY", "") or _read_env("FTAI_API_KEY", "") or _read_env("FREE_AI_API_KEY", "") or _read_env("GATEWAY_API_KEY", "")

    @property
    def host(self) -> str:
        return _read_env("HOST", "0.0.0.0")

    @property
    def port(self) -> int:
        return _read_int("PORT", 8000)

    @property
    def request_timeout(self) -> int:
        return _read_int("REQUEST_TIMEOUT", 120)

    @property
    def chat_default_max_tokens(self) -> int:
        return max(1, min(8192, _read_int("CHAT_DEFAULT_MAX_TOKENS", 4000)))

    @property
    def app_name(self) -> str:
        return _read_env("APP_NAME", "Free AI Gateway")

    # Free-only controls
    @property
    def free_only(self) -> bool:
        return _read_bool("FREE_ONLY", True)

    @property
    def allow_paid_models(self) -> bool:
        return _read_bool("ALLOW_PAID_MODELS", False)

    @property
    def verify_free_tier(self) -> bool:
        return _read_bool("VERIFY_FREE_TIER", True)

    @property
    def block_unknown_paid(self) -> bool:
        return _read_bool("BLOCK_UNKNOWN_PAID", True)

    # Cache controls
    @property
    def cache_enabled(self) -> bool:
        return _read_bool("CACHE_ENABLED", True)

    @property
    def cache_ttl_seconds(self) -> int:
        return max(10, _read_int("CACHE_TTL_SECONDS", 300))

    @property
    def cache_max_entries(self) -> int:
        return max(50, _read_int("CACHE_MAX_ENTRIES", 1000))

    @property
    def cache_max_prompt_chars(self) -> int:
        return max(500, _read_int("CACHE_MAX_PROMPT_CHARS", 24000))

    # Context compression
    @property
    def context_compress_enabled(self) -> bool:
        return _read_bool("CONTEXT_COMPRESS_ENABLED", True)

    @property
    def context_max_chars(self) -> int:
        return max(2000, _read_int("CONTEXT_MAX_CHARS", 120000))

    @property
    def context_keep_last_messages(self) -> int:
        return max(2, _read_int("CONTEXT_KEEP_LAST_MESSAGES", 12))

    @property
    def context_message_max_chars(self) -> int:
        return max(500, _read_int("CONTEXT_MESSAGE_MAX_CHARS", 12000))

    @property
    def context_summary_max_chars(self) -> int:
        return max(500, _read_int("CONTEXT_SUMMARY_MAX_CHARS", 4000))

    # Sliding window context (for small-context models like NCM)
    @property
    def sliding_window_enabled(self) -> bool:
        return _read_bool("SLIDING_WINDOW_ENABLED", True)

    @property
    def sliding_window_max_tokens(self) -> int:
        return max(64, _read_int("SLIDING_WINDOW_MAX_TOKENS", 128))

    @property
    def sliding_window_keep_last(self) -> int:
        return max(2, _read_int("SLIDING_WINDOW_KEEP_LAST", 6))

    # Free-tier spacing (Pollinations anonymous enforces ~1 reply/45s/IP).
    @property
    def pollinations_min_interval(self) -> int:
        return max(0, _read_int("POLLINATIONS_MIN_INTERVAL", 46))

    @property
    def free_tier_max_wait(self) -> int:
        return max(1, _read_int("FREE_TIER_MAX_WAIT", 60))

    # Fallback budget / circuit breaker (anti-blocking, anti-loop).
    @property
    def request_budget(self) -> int:
        return max(5, _read_int("REQUEST_BUDGET", 45))

    @property
    def stream_start_budget(self) -> int:
        return max(2, _read_int("STREAM_START_BUDGET", 12))

    @property
    def provider_breaker_threshold(self) -> int:
        return max(1, _read_int("PROVIDER_BREAKER_THRESHOLD", 3))

    @property
    def provider_breaker_cooldown(self) -> int:
        return max(5, _read_int("PROVIDER_BREAKER_COOLDOWN", 60))

    # Local NCM fallback (experimental, opt-in).
    @property
    def ncm_local_enabled(self) -> bool:
        return _read_bool("NCM_LOCAL_ENABLED", False)

    @property
    def ncm_local_base_url(self) -> str:
        return _read_env("NCM_LOCAL_BASE_URL", "http://127.0.0.1:11435/v1").rstrip("/")

    @property
    def ncm_local_model(self) -> str:
        return _read_env("NCM_LOCAL_MODEL", "ncm-instruct-725m")

    # Local Ollama fallback (Qwen3.5-9B or configured local model).
    @property
    def local_ollama_enabled(self) -> bool:
        return _read_bool("LOCAL_OLLAMA_ENABLED", False)

    @property
    def local_ollama_base_url(self) -> str:
        return _read_env("LOCAL_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")

    @property
    def local_ollama_model(self) -> str:
        return _read_env("LOCAL_OLLAMA_MODEL", "qwen3.5:9b-q4_K_M")

    @property
    def local_ollama_min_tokens(self) -> int:
        # Thinking models need room to finish reasoning before the answer.
        return max(128, _read_int("LOCAL_OLLAMA_MIN_TOKENS", 512))

    @property
    def local_ollama_think(self) -> bool:
        # Native Ollama /api/chat honors think=false; the OpenAI shim does not.
        return _read_bool("LOCAL_OLLAMA_THINK", False)

    @property
    def local_ollama_ctx(self) -> int:
        return max(1024, _read_int("LOCAL_OLLAMA_CTX", 8192))

    # Optional llama-cpp-python local backend (OpenAI-compatible server).
    # It is deliberately separate from Ollama: Ollama remains the default local
    # engine; this backend is opt-in and intended for models that fit fully in
    # VRAM or for benchmark comparisons.
    @property
    def local_llamacpp_enabled(self) -> bool:
        return _read_bool("LOCAL_LLAMACPP_ENABLED", False)

    @property
    def local_llamacpp_base_url(self) -> str:
        return _read_env("LOCAL_LLAMACPP_BASE_URL", "http://127.0.0.1:11438/v1").rstrip("/")

    @property
    def local_llamacpp_model(self) -> str:
        return _read_env("LOCAL_LLAMACPP_MODEL", "qwen3-coder-opt")

    @property
    def local_llamacpp_timeout(self) -> int:
        return max(10, _read_int("LOCAL_LLAMACPP_TIMEOUT", 600))

    # Official NCM LM1B-large (unconditional; explicit model only).
    @property
    def ncm_lm1b_enabled(self) -> bool:
        return _read_bool("NCM_LM1B_ENABLED", False)

    @property
    def ncm_lm1b_base_url(self) -> str:
        return _read_env("NCM_LM1B_BASE_URL", "http://127.0.0.1:11436/v1").rstrip("/")

    @property
    def ncm_lm1b_model(self) -> str:
        return _read_env("NCM_LM1B_MODEL", "ncm-lm1b-large")

    # jmbigi/thinker bridge (DeepResearchThinkingLayer + VeracityLayer).
    @property
    def thinker_enabled(self) -> bool:
        return _read_bool("THINKER_ENABLED", False)

    @property
    def thinker_base_url(self) -> str:
        return _read_env("THINKER_BASE_URL", "http://127.0.0.1:11437").rstrip("/")

    @property
    def thinker_timeout(self) -> int:
        return max(5, _read_int("THINKER_TIMEOUT", 300))

    # Optional upstream API keys
    @property
    def groq_api_key(self) -> str:
        return _read_env("GROQ_API_KEY", "")

    @property
    def openrouter_api_key(self) -> str:
        return _read_env("OPENROUTER_API_KEY", "")

    @property
    def openrouter_cache_ttl(self) -> int:
        return max(60, _read_int("OPENROUTER_CACHE_TTL", 3600))

    # Cost tracking (USD per million tokens)
    @property
    def cost_tracking_enabled(self) -> bool:
        return _read_bool("COST_TRACKING_ENABLED", True)

    @property
    def cost_per_million_tokens(self) -> dict[str, float]:
        """Default cost per million tokens per provider (input, output). Override via COST_PER_MILLION_JSON."""
        defaults = {
            "openrouter": 0.0,
            "pollinations": 0.0,
            "nvidia": 0.0,
            "groq": 0.0,
            "huggingface": 0.0,
            "local-ollama": 0.0,
            "local-llamacpp": 0.0,
            "ncm": 0.0,
            "ncm-instruct": 0.0,
            "ncm-lm1b": 0.0,
        }
        import json
        try:
            return {**defaults, **json.loads(_read_env("COST_PER_MILLION_JSON", "{}"))}
        except Exception:
            return defaults

    @property
    def nvidia_api_key(self) -> str:
        return _read_env("NVIDIA_API_KEY", "")

    @property
    def gemini_api_key(self) -> str:
        return _read_env("GEMINI_API_KEY", "")

    @property
    def cloudflare_api_token(self) -> str:
        return _read_env("CLOUDFLARE_API_TOKEN", "")

    @property
    def cloudflare_account_id(self) -> str:
        return _read_env("CLOUDFLARE_ACCOUNT_ID", "")

    @property
    def mistral_api_key(self) -> str:
        return _read_env("MISTRAL_API_KEY", "")

    @property
    def sambanova_api_key(self) -> str:
        return _read_env("SAMBANOVA_API_KEY", "")

    @property
    def cerebras_api_key(self) -> str:
        return _read_env("CEREBRAS_API_KEY", "")

    @property
    def huggingface_api_key(self) -> str:
        return _read_env("HUGGINGFACE_API_KEY", "") or _read_env("HUGGING_FACE_API_KEY", "")

    @property
    def together_api_key(self) -> str:
        return _read_env("TOGETHER_API_KEY", "")

    @property
    def cohere_api_key(self) -> str:
        return _read_env("COHERE_API_KEY", "")

    @property
    def deepseek_api_key(self) -> str:
        return _read_env("DEEPSEEK_API_KEY", "")

    @property
    def moonshot_api_key(self) -> str:
        return _read_env("MOONSHOT_API_KEY", "") or _read_env("KIMI_API_KEY", "")

    @property
    def kimi_api_key(self) -> str:
        return self.moonshot_api_key

    @property
    def opencode_api_key(self) -> str:
        return _read_env("OPENCODE_API_KEY", "")

    @property
    def opencode_base_url(self) -> str:
        return _read_env("OPENCODE_BASE_URL", "")

    @property
    def custom_openai_api_key(self) -> str:
        return _read_env("CUSTOM_OPENAI_API_KEY", "")

    @property
    def custom_openai_base_url(self) -> str:
        return _read_env("CUSTOM_OPENAI_BASE_URL", "")

    @property
    def custom_openai_models(self) -> str:
        return _read_env("CUSTOM_OPENAI_MODELS", "")


    # Backward-compatible aliases used by providers
    @property
    def openai_compatible_api_key(self) -> str:
        return self.custom_openai_api_key
    @property
    def openai_compatible_base_url(self) -> str:
        return self.custom_openai_base_url
    @property
    def openai_compatible_models(self) -> str:
        return self.custom_openai_models
    @property
    def cache_max_items(self) -> int:
        return self.cache_max_entries


    # Optional web search / knowledge providers (free tiers / self-hosted)
    @property
    def tavily_api_key(self) -> str: return _read_env('TAVILY_API_KEY','')
    @property
    def brave_search_api_key(self) -> str: return _read_env('BRAVE_SEARCH_API_KEY','') or _read_env('BRAVE_API_KEY','')
    @property
    def searxng_base_url(self) -> str: return _read_env('SEARXNG_BASE_URL','')
    @property
    def llm7_base_url(self) -> str:
        return _read_env("LLM7_BASE_URL", "https://api.llm7.io/v1").rstrip('/')

    @property
    def llm7_api_key(self) -> str:
        return _read_env("LLM7_API_KEY", "")


    @property
    def public_base_url(self) -> str:
        return _read_env("PUBLIC_BASE_URL", "https://ia.forthtrade.com").rstrip('/')

    # MCP (Model Context Protocol)
    @property
    def mcp_enabled(self) -> bool:
        return _read_bool("MCP_ENABLED", False)

    @property
    def mcp_transport(self) -> str:
        return _read_env("MCP_TRANSPORT", "stdio")

    @property
    def mcp_tools_root(self) -> str:
        return _read_env("MCP_TOOLS_ROOT", "/tmp/mcp-tools")

    # Quantization profiles
    @property
    def quant_profile(self) -> str:
        return _read_env("QUANT_PROFILE", "q4_k_m")

    # Model-specific parameters (JSON string)
    @property
    def model_params_json(self) -> str:
        return _read_env("MODEL_PARAMS_JSON", "{}")

    # OpenTelemetry configuration
    @property
    def otel_enabled(self) -> bool:
        return _read_bool("OTEL_ENABLED", False)

    @property
    def otel_endpoint(self) -> str:
        return _read_env("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    @property
    def otel_protocol(self) -> str:
        return _read_env("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")

    @property
    def otel_service_name(self) -> str:
        return _read_env("OTEL_SERVICE_NAME", "free-ai-gateway")


settings = SettingsProxy()
