"""Application settings, read from the environment.

No pydantic-settings dependency on purpose: plain stdlib parsing keeps the
container image small and the behaviour obvious.

Startup validation lives here too (see ``validate_fernet_key`` /
``Settings.validate_startup``): the backend must refuse to boot with a clear,
named-variable error instead of a cryptic traceback when a required secret is
missing or malformed. Importing this module never validates — validation is
explicit, called from ``app.main`` (API), ``app.worker`` (worker), and
``entrypoint.sh`` (before migrations run).
"""
from __future__ import annotations

import base64
import os
import sys
from dataclasses import dataclass, field


class ConfigurationError(RuntimeError):
    """Raised when a required environment variable is missing or invalid."""


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


# The JWT secret shipped as a code default. It must NEVER be accepted in
# production; it exists only so local dev/tests boot without extra setup.
_DEV_JWT_PLACEHOLDER = "dev-only-insecure-secret"


def validate_fernet_key(raw: str) -> None:
    """Fail fast unless *raw* is a valid Fernet key.

    Raises ConfigurationError naming FERNET_KEY when the value is missing,
    empty, or not a 32-byte urlsafe-base64-encoded key. The key material
    itself is never echoed back in the error.
    """
    if not raw or not raw.strip():
        raise ConfigurationError(
            "FERNET_KEY is not set. The backend refuses to start without it because "
            "provider credentials cannot be encrypted. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"\n'
            "and set FERNET_KEY to the output."
        )
    key = raw.strip().encode("utf-8")
    try:
        decoded_len: int | None = len(base64.urlsafe_b64decode(key))
    except Exception:
        decoded_len = None
    # Fernet() itself is the authority on validity (32 urlsafe-b64 bytes);
    # the decoded length is only reported so the operator can see *how* the
    # value is wrong without us ever echoing the key material.
    from cryptography.fernet import Fernet  # noqa: PLC0415

    try:
        Fernet(key)
    except Exception as exc:
        detail = (
            f"decodes to {decoded_len} bytes"
            if decoded_len is not None
            else "is not valid urlsafe-base64"
        )
        raise ConfigurationError(
            "FERNET_KEY is invalid: it must be a 32-byte urlsafe-base64-encoded "
            f"Fernet key, but the configured value {detail} "
            f"({type(exc).__name__}). Generate a valid one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ) from exc


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _get(
        "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_cost_doctor"))
    jwt_secret: str = field(default_factory=lambda: _get("JWT_SECRET", "dev-only-insecure-secret"))
    jwt_algorithm: str = field(default_factory=lambda: _get("JWT_ALGORITHM", "HS256"))
    access_token_expire_minutes: int = field(default_factory=lambda: _get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    refresh_token_expire_days: int = field(default_factory=lambda: _get_int("REFRESH_TOKEN_EXPIRE_DAYS", 30))
    fernet_key: str = field(default_factory=lambda: _get("FERNET_KEY", ""))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in _get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()))
    demo_namespace: str = field(default_factory=lambda: _get("DEMO_NAMESPACE", "ai-cost-doctor-demo"))
    environment: str = field(default_factory=lambda: _get("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: _get("LOG_LEVEL", "INFO"))
    # Optional narrative polish for /investigate/explain. Unset by default:
    # the template narrative is always used unless a key is provided.
    narrative_llm_api_key: str = field(default_factory=lambda: _get("NARRATIVE_LLM_API_KEY", ""))
    narrative_llm_model: str = field(default_factory=lambda: _get("NARRATIVE_LLM_MODEL", "gpt-4o-mini"))
    narrative_llm_base_url: str = field(default_factory=lambda: _get("NARRATIVE_LLM_BASE_URL", "https://api.openai.com/v1"))
    # --- Billing (Stripe) ---------------------------------------------------
    # All billing secrets live in env only: never in the DB, logs, or API
    # responses. Prices are created in the Stripe Dashboard; only the Price
    # IDs travel via env so catalog changes don't need a deploy.
    stripe_secret_key: str = field(default_factory=lambda: _get("STRIPE_SECRET_KEY", ""))
    stripe_webhook_secret: str = field(default_factory=lambda: _get("STRIPE_WEBHOOK_SECRET", ""))
    stripe_price_starter: str = field(default_factory=lambda: _get("STRIPE_PRICE_STARTER", ""))
    stripe_price_growth: str = field(default_factory=lambda: _get("STRIPE_PRICE_GROWTH", ""))
    frontend_url: str = field(default_factory=lambda: _get("FRONTEND_URL", "http://localhost:3000"))

    def validate_startup(self) -> None:
        """Fail fast on misconfiguration before the app serves traffic.

        FERNET_KEY is validated in every environment: without a valid key the
        service cannot encrypt provider credentials, so booting would be
        silently broken. The remaining gates only apply when
        ENVIRONMENT=production, so local dev and tests keep working with
        their documented defaults.

        Raises ConfigurationError (names the offending variable) on failure.
        """
        # --- FERNET_KEY: always required, always a valid Fernet key ---------
        validate_fernet_key(self.fernet_key)

        if self.environment != "production":
            if self.jwt_secret == _DEV_JWT_PLACEHOLDER:
                print(
                    "WARNING: JWT_SECRET is the insecure dev placeholder "
                    f"({_DEV_JWT_PLACEHOLDER!r}). Set a real secret before any "
                    "non-local deployment.",
                    file=sys.stderr,
                )
            return

        # --- Production-only gates ------------------------------------------
        if not self.jwt_secret or self.jwt_secret == _DEV_JWT_PLACEHOLDER:
            raise ConfigurationError(
                "JWT_SECRET is not set (or is the dev placeholder) and "
                "ENVIRONMENT=production. Refusing to start: all auth tokens "
                "would be forgeable. Generate one with:\n"
                '  python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        if len(self.jwt_secret) < 32:
            raise ConfigurationError(
                "JWT_SECRET is too short for production use (minimum 32 "
                f"characters, got {len(self.jwt_secret)}). Generate a strong one with:\n"
                '  python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        if not self.database_url.startswith("postgresql"):
            raise ConfigurationError(
                "DATABASE_URL must be a PostgreSQL URL when "
                "ENVIRONMENT=production "
                f"(got scheme {self.database_url.split(':', 1)[0]!r})."
            )
        if "localhost" in self.database_url or "127.0.0.1" in self.database_url:
            print(
                "WARNING: DATABASE_URL points at localhost while "
                "ENVIRONMENT=production. If this is a real deployment, that is "
                "almost certainly wrong.",
                file=sys.stderr,
            )
        if any("localhost" in o or "127.0.0.1" in o for o in self.cors_origins):
            print(
                "WARNING: CORS_ORIGINS still allows localhost while "
                "ENVIRONMENT=production. Set it to the real frontend origin(s) "
                "or browser clients will be blocked.",
                file=sys.stderr,
            )
        if not self.stripe_secret_key or not self.stripe_webhook_secret:
            print(
                "WARNING: STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET are not both "
                "set while ENVIRONMENT=production. Billing endpoints will "
                "fail closed (503) until they are configured.",
                file=sys.stderr,
            )


settings = Settings()


def validate_startup_config() -> None:
    """Validate the process-wide ``settings`` singleton. See
    ``Settings.validate_startup``."""
    settings.validate_startup()
