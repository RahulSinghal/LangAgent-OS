"""Central application configuration loaded from environment / .env file."""

from functools import lru_cache
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────
    APP_NAME: str = "LangGraph AgentOS"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # ── Database ─────────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5434
    POSTGRES_USER: str = "agentosuser"
    POSTGRES_PASSWORD: str = "agentospassword"
    POSTGRES_DB: str = "agentosdb"

    @computed_field  # type: ignore[misc]
    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── LLM ──────────────────────────────────────────────────────
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o"
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    # Gemini (Google) via litellm
    GEMINI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""  # alias (some tools/providers use this name)

    # ── Security (Phase 3) ───────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── Storage ──────────────────────────────────────────────────
    ARTIFACTS_DIR: str = "./storage/artifacts"

    # ── Phase 2: Web tools ────────────────────────────────────────
    # Set TAVILY_API_KEY to enable real web search (https://tavily.com).
    # If empty, web_search falls back to deterministic stub results.
    TAVILY_API_KEY: str = ""
    # Timeout (seconds) for fetch_url via httpx. Falls back to stub if httpx
    # is not installed or FETCH_URL_TIMEOUT is 0.
    FETCH_URL_TIMEOUT: int = 10

    # ── Phase 2: Deep Agent ───────────────────────────────────────
    DEEP_MODE: str = "suggest"  # "off" | "suggest" | "auto"
    # "off"     — DeepWorkAgent never runs automatically
    # "suggest" — DeepWorkAgent runs but results are advisory only (default)
    # "auto"    — DeepWorkAgent output directly applied to SoT

    # ── Eval coverage gate ────────────────────────────────────────
    # Minimum eval coverage % required to approve a milestone.
    # 0.0 = warn only (default). 80.0 = block if < 80% covered.
    MIN_EVAL_COVERAGE_PCT: float = 0.0

    # ── Testing / Deterministic mode ──────────────────────────────
    USE_MOCK_AGENTS: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance. Use this in FastAPI dependencies."""
    return Settings()


# Module-level singleton for convenience imports
settings = get_settings()
