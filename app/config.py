from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = "postgresql+asyncpg://leadgen:leadgen@db:5432/leadgen"
    sync_database_url: str = "postgresql+psycopg2://leadgen:leadgen@db:5432/leadgen"

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # Google Maps Platform (Places API New)
    google_maps_api_key: str = ""

    # Dubai Pulse / DLD
    dubai_pulse_api_key: str = ""
    dubai_pulse_api_secret: str = ""
    dubai_pulse_token_url: str = (
        "https://api.dubaipulse.gov.ae/oauth/client_credential/accesstoken"
    )
    dubai_pulse_api_url: str = "https://api.dubaipulse.gov.ae"

    # OSM Overpass
    osm_overpass_url: str = "https://overpass-api.de/api/interpreter"

    # Crawling / reliability
    crawl_user_agent: str = "LagentryBot/1.0 (+https://lagentry.example/bot)"
    crawl_max_pages_per_domain: int = 40
    crawl_target_pages: int = 8          # focused crawl: homepage + contact pages
    crawl_html_max_bytes: int = 200_000  # cap stored HTML per page (post-strip)
    crawl_delay_min_seconds: int = 5
    crawl_delay_max_seconds: int = 15
    recrawl_days: int = 45
    crawl_max_retries: int = 2

    # Email verification
    paid_verify_enabled: bool = False
    millionverifier_api_key: str = ""
    bouncer_api_key: str = ""
    paid_verify_monthly_cap: int = 2000
    paid_verify_provider: str = "millionverifier"

    # Outreach
    outreach_webhook_url: str = ""

    # Target
    target_country: str = "AE"
    target_niche: str = "real_estate_agency"


@lru_cache
def get_settings() -> Settings:
    return Settings()
