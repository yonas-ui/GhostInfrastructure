import os


class Settings:
    """Runtime configuration, read from environment variables."""

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./ghost.db")
    # Empty REDIS_URL disables Redis pub/sub (WebSocket events then stay in-process).
    redis_url: str = os.getenv("REDIS_URL", "")
    secret_key: str = os.getenv("SECRET_KEY", "dev-only-secret-change-me-in-production-0123456789")
    token_ttl_minutes: int = int(os.getenv("TOKEN_TTL_MINUTES", "720"))
    health_timeout: float = float(os.getenv("HEALTH_TIMEOUT_SECONDS", "5"))
    health_interval: int = int(os.getenv("HEALTH_INTERVAL_SECONDS", "30"))
    slow_ms: int = int(os.getenv("HEALTH_SLOW_MS", "1500"))
    health_retention_days: int = int(os.getenv("HEALTH_RETENTION_DAYS", "7"))
    stale_days: int = int(os.getenv("GHOST_STALE_DAYS", "90"))
    cors_origins: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
        ).split(",")
        if o.strip()
    ]
    seed_demo: bool = os.getenv("SEED_DEMO", "true").lower() in ("1", "true", "yes")


settings = Settings()
