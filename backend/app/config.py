"""Application configuration, sourced entirely from the environment (spec §13.2)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- General ------------------------------------------------------------
    tz: str = Field(default="America/Los_Angeles", alias="TZ")
    environment: str = Field(default="dev", alias="ENVIRONMENT")
    # "json" (default) for structured audit logging (spec §5); "text" for local dev.
    log_format: str = Field(default="json", alias="LOG_FORMAT")
    # Public origin the PWA + webhooks are reached at (spec §12.2).
    public_base_url: str = Field(default="http://localhost:8088", alias="PUBLIC_BASE_URL")

    # --- Internet exposure (spec §12.2 Cloudflare Tunnel) -----------------
    # Comma-separated Host allow-list; empty disables the check (LAN/dev).
    allowed_hosts: str = Field(default="", alias="ALLOWED_HOSTS")
    # Trust CF-Connecting-IP / X-Forwarded-For for the client IP. Only set true
    # when the app genuinely sits behind the tunnel + proxy — otherwise a LAN
    # client spoofs the header to dodge the login rate limit.
    trust_proxy_headers: bool = Field(default=False, alias="TRUST_PROXY_HEADERS")
    # Cloudflare Access: when both are set, the whole /api/v1 surface requires a valid
    # Cf-Access-Jwt-Assertion, and its Google `email` claim is the login identity
    # (spec §12.1). Comma-separated AUD list — one tag per Access application.
    cf_access_team_domain: str = Field(default="", alias="CF_ACCESS_TEAM_DOMAIN")
    cf_access_aud: str = Field(default="", alias="CF_ACCESS_AUD")
    # Accepted `iss` values, comma-separated. Defaults to https://{team_domain}, which is
    # right until the Zero Trust team is renamed: Cloudflare keeps minting tokens under the
    # ORIGINAL team name while serving login and JWKS from the new one, so the two genuinely
    # differ and the old hostname 404s. Read the real value off a rejected token — the
    # cf_access.rejected log line prints it.
    cf_access_issuer: str = Field(default="", alias="CF_ACCESS_ISSUER")

    # --- Database ---------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://chore:chore@localhost:5432/chore",
        alias="DATABASE_URL",
    )

    # --- Media / storage -----------------------------------------------------
    media_root: str = Field(default="/data/media", alias="MEDIA_ROOT")
    media_retention_days: int = Field(default=180, alias="MEDIA_RETENTION_DAYS")
    geo_retention_days: int = Field(default=30, alias="GEO_RETENTION_DAYS")

    # --- Local vision LLM (Phase 4; declared now so config is stable) -------
    llm_vision_base_url: str = Field(
        default="http://llm-vision:8081/v1", alias="LLM_VISION_BASE_URL"
    )
    llm_vision_model: str = Field(default="", alias="LLM_VISION_MODEL")
    llm_vision_api_key: str = Field(default="not-needed", alias="LLM_VISION_API_KEY")
    llm_timeout_s: int = Field(default=120, alias="LLM_TIMEOUT_S")
    llm_max_retries: int = Field(default=1, alias="LLM_MAX_RETRIES")

    # --- Missed-chore settlement (spec §3, §9) -----------------------------
    # A miss is flagged the moment the grace period lapses, but the money moves later: a
    # home server that was down for a few hours catches up in one pass and would otherwise
    # debit a pile of false penalties (spec §16). The delay is the window in which a parent
    # can excuse them, or the kid can appeal, before anything is charged.
    miss_settle_delay_s: int = Field(default=6 * 3600, alias="MISS_SETTLE_DELAY_S")
    # How long after due_at a kid may still contest an occurrence.
    appeal_window_s: int = Field(default=72 * 3600, alias="APPEAL_WINDOW_S")

    # --- Verification banding ----------------------------------------------
    auto_pass_threshold: float = Field(default=0.85, alias="AUTO_PASS_THRESHOLD")
    auto_fail_threshold: float = Field(default=0.35, alias="AUTO_FAIL_THRESHOLD")

    # --- Web Push (Phase 5) ------------------------------------------------
    vapid_public_key: str = Field(default="", alias="VAPID_PUBLIC_KEY")
    vapid_private_key: str = Field(default="", alias="VAPID_PRIVATE_KEY")

    # --- Auth / sessions --------------------------------------------------
    session_secret: str = Field(default="dev-insecure-change-me", alias="SESSION_SECRET")
    admin_session_hours: int = Field(default=12, alias="ADMIN_SESSION_HOURS")
    child_session_days: int = Field(default=90, alias="CHILD_SESSION_DAYS")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")

    @property
    def is_prod(self) -> bool:
        return self.environment.lower() in {"prod", "production"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
