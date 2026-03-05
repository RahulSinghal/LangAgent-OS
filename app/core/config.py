"""Central application configuration loaded from environment / .env file."""

from functools import lru_cache
from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_JWT_DEFAULT = "change-me-in-production"


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

    # ── Security ─────────────────────────────────────────────────
    # JWT_SECRET_KEY must be changed in production.
    # Generate with: openssl rand -hex 32
    JWT_SECRET_KEY: str = _INSECURE_JWT_DEFAULT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    # Set REQUIRE_SECURE_JWT=true to cause startup to fail when the default
    # insecure JWT_SECRET_KEY is still in use.  Defaults to False so local
    # development and CI continue to work without extra configuration.
    REQUIRE_SECURE_JWT: bool = False

    # ── CORS ──────────────────────────────────────────────────────
    # Comma-separated list of allowed origins.
    # Examples:
    #   ALLOWED_ORIGINS=*                             (dev, open)
    #   ALLOWED_ORIGINS=https://app.example.com       (single origin)
    #   ALLOWED_ORIGINS=https://a.com,https://b.com   (multiple)
    # Defaults to wildcard ("*") which is safe for local dev but must be
    # restricted before going to production.
    ALLOWED_ORIGINS: str = "*"

    @computed_field  # type: ignore[misc]
    @property
    def cors_origins(self) -> list[str]:
        """Parse ALLOWED_ORIGINS into a list of origin strings."""
        raw = self.ALLOWED_ORIGINS.strip()
        if not raw or raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    # ── Storage ──────────────────────────────────────────────────
    ARTIFACTS_DIR: str = "./storage/artifacts"
    # Maximum number of on-disk versions to retain per (project, artifact_type).
    # When a new version is rendered, older versions beyond this cap are deleted.
    # Set to 0 to disable cleanup.
    ARTIFACT_MAX_VERSIONS: int = 5

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

    # ── GitHub integration ────────────────────────────────────────
    # Set GITHUB_TOKEN (fine-grained PAT with Contents write scope) to enable
    # "Publish to GitHub" after milestones are approved.  Leave empty to disable.
    GITHUB_TOKEN: str = ""
    # Default org/user under which new repos are created.
    # If empty, falls back to the authenticated user's own account.
    GITHUB_DEFAULT_ORG: str = ""
    # HMAC-SHA256 secret for verifying incoming GitHub webhook payloads.
    # Set this to the same value configured in the GitHub repository webhook settings.
    # Leave empty to disable webhook signature verification (not recommended for prod).
    GITHUB_WEBHOOK_SECRET: str = ""

    # ── Supervisor planning mode ──────────────────────────────────
    # "deterministic" — static _PHASE_PLAN lookup (default, zero LLM cost)
    # "llm"           — LLM generates TaskDAG; falls back to deterministic on error
    SUPERVISOR_MODE: str = "deterministic"

    # ── LLM resilience ────────────────────────────────────────────
    # Retries on RateLimitError with exponential backoff (2s, 4s, 8s, …).
    LLM_MAX_RETRIES: int = 3

    # ── LLM context budget ────────────────────────────────────────
    # Maximum total characters for user_message passed to LLM calls.
    # Long messages are trimmed (keeping start + end) to stay within this limit.
    # Set to 0 to disable trimming.
    LLM_CONTEXT_MAX_CHARS: int = 40_000

    # ── Approval loop safety ───────────────────────────────────────
    # Maximum number of times an artifact can be rejected before the run
    # errors out instead of looping indefinitely.
    MAX_REJECTION_RETRIES: int = 3

    # ── Upload safety ──────────────────────────────────────────────
    # Maximum file size (bytes) accepted by /documents/extract endpoints.
    # Default: 20 MB.  Set to 0 to disable the check.
    MAX_UPLOAD_SIZE_BYTES: int = 20 * 1024 * 1024  # 20 MB

    # ── Input safety ───────────────────────────────────────────────
    # Maximum length (characters) of a single user message fed into the SoT.
    MAX_USER_MESSAGE_LENGTH: int = 10_000

    # ── Testing / Deterministic mode ──────────────────────────────
    USE_MOCK_AGENTS: bool = False

    # ── Validators ────────────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_jwt_secret(self) -> "Settings":
        """Raise at startup if running in production with the default JWT secret.

        Set DEBUG=True in development to bypass this check.  In production,
        always set JWT_SECRET_KEY to a long random string (e.g. `openssl rand -hex 32`).
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)
        if self.JWT_SECRET_KEY == _INSECURE_JWT_DEFAULT:
            if self.REQUIRE_SECURE_JWT:
                raise ValueError(
                    "JWT_SECRET_KEY is set to the default insecure value "
                    f"'{_INSECURE_JWT_DEFAULT}'. "
                    "Set JWT_SECRET_KEY in your .env file. "
                    "Generate one with: openssl rand -hex 32\n"
                    "Set REQUIRE_SECURE_JWT=false to downgrade this to a warning."
                )
            _log.warning(
                "SECURITY WARNING: JWT_SECRET_KEY is set to the default insecure "
                "value '%s'. Set a strong random secret in .env before going to "
                "production (REQUIRE_SECURE_JWT=true to enforce this at startup).",
                _INSECURE_JWT_DEFAULT,
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance. Use this in FastAPI dependencies."""
    return Settings()


# Module-level singleton for convenience imports
settings = get_settings()
