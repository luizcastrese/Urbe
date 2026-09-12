import os
from dataclasses import dataclass

from .utils import load_local_env


def env_flag(name, default=False):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name):
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def detect_production():
    env_name = os.getenv("URBE_ENV", "").strip().lower()
    if env_name in {"production", "prod"}:
        return True
    if env_name in {"development", "dev", "test", "local"}:
        return False
    return bool(os.getenv("FLY_APP_NAME") or os.getenv("FLY_ALLOC_ID"))


@dataclass
class BunnyConfig:
    api_key: str
    default_library_id: str
    embed_token_key: str
    iframe_host: str


@dataclass
class OpenPixConfig:
    app_id: str
    api_base: str = "https://api.openpix.com.br/api/v1"
    split_pix_key: str = ""
    split_percent: int = 10
    webhook_secret: str = ""


@dataclass
class PaymentsConfig:
    provider: str
    currency: str
    success_url: str
    cancel_url: str
    openpix: OpenPixConfig


@dataclass
class Config:
    port: int
    db_file: str
    database_url: str
    session_duration_days: int
    checkout_reservation_minutes: int
    playback_session_seconds: int
    bunny: BunnyConfig
    payments: PaymentsConfig
    is_production: bool = False
    app_origins: tuple = ("http://localhost:3000",)
    cookie_secure: bool = False
    open_publish: bool = True
    producer_emails: tuple = ()
    producer_invite: str = ""
    require_signed_embed: bool = False
    require_bunny_lookup: bool = False
    allow_free_buy: bool = True
    auth_rate_limit: int = 20
    auth_rate_window_seconds: int = 900


def load_config():
    load_local_env()
    root_dir = os.getcwd()
    is_production = detect_production()
    database_url = os.getenv("DATABASE_URL", "").strip()
    openpix_app_id = os.getenv("OPENPIX_APP_ID", "")
    payments_provider = os.getenv("PAYMENTS_PROVIDER", "openpix" if openpix_app_id else "mock")
    payments_currency = os.getenv("PAYMENTS_CURRENCY", "BRL").upper()
    openpix_split_pix_key = os.getenv("OPENPIX_SPLIT_PIX_KEY", "").strip()
    openpix_webhook_secret = os.getenv("OPENPIX_WEBHOOK_SECRET", "").strip()
    bunny_api_key = os.getenv("BUNNY_STREAM_API_KEY", "")
    embed_token_key = os.getenv("BUNNY_STREAM_EMBED_TOKEN_KEY", "")

    split_percent_raw = os.getenv("OPENPIX_SPLIT_PERCENT", "10")
    try:
        split_percent = int(split_percent_raw)
    except ValueError:
        split_percent = 10

    if split_percent < 0:
        split_percent = 0
    if split_percent > 100:
        split_percent = 100

    origins = env_csv("PUBLIC_APP_ORIGIN") or ("http://localhost:3000",)
    provider = payments_provider.lower()

    return Config(
        port=int(os.getenv("PORT", "3000")),
        db_file=os.getenv("DB_FILE", os.path.join(root_dir, "data", "urbe-db.json")),
        database_url=database_url,
        session_duration_days=int(os.getenv("SESSION_DURATION_DAYS", "30")),
        checkout_reservation_minutes=int(os.getenv("CHECKOUT_RESERVATION_MINUTES", "15")),
        playback_session_seconds=int(os.getenv("PLAYBACK_SESSION_SECONDS", "120")),
        bunny=BunnyConfig(
            api_key=bunny_api_key,
            default_library_id=os.getenv("BUNNY_STREAM_LIBRARY_ID", ""),
            embed_token_key=embed_token_key,
            iframe_host=os.getenv("BUNNY_IFRAME_HOST", "https://iframe.mediadelivery.net"),
        ),
        payments=PaymentsConfig(
            provider=provider,
            currency=payments_currency,
            success_url=os.getenv(
                "PAYMENTS_CHECKOUT_SUCCESS_URL",
                "http://localhost:3000/?checkout=success&orderId={ORDER_ID}",
            ),
            cancel_url=os.getenv(
                "PAYMENTS_CHECKOUT_CANCEL_URL",
                "http://localhost:3000/?checkout=cancel&orderId={ORDER_ID}",
            ),
            openpix=OpenPixConfig(
                app_id=openpix_app_id,
                split_pix_key=openpix_split_pix_key,
                split_percent=split_percent,
                webhook_secret=openpix_webhook_secret,
            ),
        ),
        is_production=is_production,
        app_origins=origins,
        cookie_secure=env_flag("URBE_COOKIE_SECURE", is_production),
        open_publish=env_flag("URBE_OPEN_PUBLISH", not is_production),
        producer_emails=tuple(item.lower() for item in env_csv("URBE_PRODUCER_EMAILS")),
        producer_invite=os.getenv("URBE_PRODUCER_INVITE", "").strip(),
        require_signed_embed=env_flag("URBE_REQUIRE_SIGNED_EMBED", is_production),
        require_bunny_lookup=bool(bunny_api_key),
        allow_free_buy=provider == "mock" and not is_production,
    )


def production_gaps(config):
    gaps = []
    if config.payments.provider == "mock":
        gaps.append("PAYMENTS_PROVIDER nao pode ser mock")
    if config.payments.provider == "openpix" and not config.payments.openpix.app_id:
        gaps.append("OPENPIX_APP_ID")
    if not config.payments.openpix.webhook_secret:
        gaps.append("OPENPIX_WEBHOOK_SECRET")
    if not config.database_url:
        gaps.append("DATABASE_URL")
    if not config.bunny.api_key:
        gaps.append("BUNNY_STREAM_API_KEY")
    if not config.bunny.default_library_id:
        gaps.append("BUNNY_STREAM_LIBRARY_ID")
    if not config.bunny.embed_token_key:
        gaps.append("BUNNY_STREAM_EMBED_TOKEN_KEY")
    if not config.app_origins:
        gaps.append("PUBLIC_APP_ORIGIN")
    return gaps


def assert_runtime_ready(config):
    if not config.is_production:
        return
    gaps = production_gaps(config)
    if gaps:
        raise SystemExit("Produção incompleta: " + "; ".join(gaps))
