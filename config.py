import os
from dataclasses import dataclass


@dataclass
class BunnyConfig:
    api_key: str
    default_library_id: str
    embed_token_key: str
    iframe_host: str


@dataclass
class StripeConfig:
    secret_key: str
    api_base: str


@dataclass
class PaymentsConfig:
    provider: str
    currency: str
    success_url: str
    cancel_url: str
    stripe: StripeConfig


@dataclass
class Config:
    port: int
    db_file: str
    session_duration_days: int
    checkout_reservation_minutes: int
    playback_session_seconds: int
    bunny: BunnyConfig
    payments: PaymentsConfig


def load_config():
    root_dir = os.getcwd()
    stripe_secret = os.getenv("STRIPE_SECRET_KEY", "")
    payments_provider = os.getenv("PAYMENTS_PROVIDER", "stripe" if stripe_secret else "mock")
    payments_currency = os.getenv("PAYMENTS_CURRENCY", "BRL").upper()

    return Config(
        port=int(os.getenv("PORT", "3000")),
        db_file=os.getenv("DB_FILE", os.path.join(root_dir, "data", "urbe-db.json")),
        session_duration_days=int(os.getenv("SESSION_DURATION_DAYS", "30")),
        checkout_reservation_minutes=int(os.getenv("CHECKOUT_RESERVATION_MINUTES", "15")),
        playback_session_seconds=int(os.getenv("PLAYBACK_SESSION_SECONDS", "120")),
        bunny=BunnyConfig(
            api_key=os.getenv("BUNNY_STREAM_API_KEY", ""),
            default_library_id=os.getenv("BUNNY_STREAM_LIBRARY_ID", ""),
            embed_token_key=os.getenv("BUNNY_STREAM_EMBED_TOKEN_KEY", ""),
            iframe_host=os.getenv("BUNNY_IFRAME_HOST", "https://iframe.mediadelivery.net"),
        ),
        payments=PaymentsConfig(
            provider=payments_provider.lower(),
            currency=payments_currency,
            success_url=os.getenv(
                "PAYMENTS_CHECKOUT_SUCCESS_URL",
                "http://localhost:3000/?checkout=success&orderId={ORDER_ID}&session_id={CHECKOUT_SESSION_ID}",
            ),
            cancel_url=os.getenv(
                "PAYMENTS_CHECKOUT_CANCEL_URL",
                "http://localhost:3000/?checkout=cancel&orderId={ORDER_ID}&session_id={CHECKOUT_SESSION_ID}",
            ),
            stripe=StripeConfig(
                secret_key=stripe_secret,
                api_base=os.getenv("STRIPE_API_BASE", "https://api.stripe.com/v1"),
            ),
        ),
    )

