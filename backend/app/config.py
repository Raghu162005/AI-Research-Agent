import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable '{name}'. "
            "Copy .env.example to .env and fill it in."
        )
    return value


def env_str(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def env_int(name: str, default: int) -> int:
    try:
        return int(env_str(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(env_str(name, str(default)))
    except ValueError:
        return default


def env_is_set(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    groq_model: str
    llm_temperature: float
    tavily_api_key: str
    max_subtopics: int
    max_queries: int
    results_per_query: int
    max_snippet_chars: int
    max_prompt_chars: int
    max_concurrent_jobs: int
    llm_max_retries: int
    llm_retry_base_delay: float
    llm_retry_max_delay: float
    search_depth: str
    cors_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        model = env_str("GROQ_MODEL", "openai/gpt-oss-120b")
        return cls(
            groq_api_key=require_env("GROQ_API_KEY"),
            groq_model=model,
            llm_temperature=_resolve_temperature(model),
            tavily_api_key=require_env("TAVILY_API_KEY"),
            max_subtopics=env_int("MAX_SUBTOPICS", 4),
            max_queries=env_int("MAX_QUERIES", 5),
            results_per_query=env_int("RESULTS_PER_QUERY", 4),
            max_snippet_chars=env_int("MAX_SNIPPET_CHARS", 1200),
            max_prompt_chars=env_int("MAX_PROMPT_CHARS", 14000),
            max_concurrent_jobs=env_int("MAX_CONCURRENT_JOBS", 1),
            llm_max_retries=env_int("LLM_MAX_RETRIES", 5),
            llm_retry_base_delay=env_float("LLM_RETRY_BASE_DELAY", 2.0),
            llm_retry_max_delay=env_float("LLM_RETRY_MAX_DELAY", 45.0),
            search_depth=env_str("TAVILY_SEARCH_DEPTH", "advanced"),
            cors_origins=tuple(
                origin.strip()
                for origin in env_str(
                    "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
                ).split(",")
                if origin.strip()
            ),
        )


def _resolve_temperature(model: str) -> float:
    if env_is_set("GROQ_TEMPERATURE"):
        return env_float("GROQ_TEMPERATURE", 0.2)
    if "gpt-oss" in model:
        return 1.0
    return 0.2


_cached: Settings | None = None


def get_settings() -> Settings:
    global _cached
    if _cached is None:
        _cached = Settings.from_env()
    return _cached
