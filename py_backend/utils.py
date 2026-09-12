import base64
import copy
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.parse

from .errors import AppError

OPENPIX_PAID_EVENTS = frozenset(
    {
        "pix_received",
        "charge_completed",
        "transaction_received",
        "openpix:charge_completed",
        "openpix:transaction_received",
        "openpix:charge_completed_not_same_customer_payer",
        "openpix:movement_confirmed",
    }
)

OPENPIX_EXPIRED_EVENTS = frozenset(
    {
        "charge_expired",
        "openpix:charge_expired",
    }
)


def now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def random_token(prefix="urb"):
    return f"{prefix}_{secrets.token_hex(24)}"


def deep_clone(value):
    return copy.deepcopy(value)


def hash_password(password):
    if not password or len(password) < 6:
        raise AppError("A senha precisa ter ao menos 6 caracteres.", 400, "INVALID_PASSWORD")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000, dklen=64)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password, password_hash):
    parts = str(password_hash or "").split(":")
    if len(parts) != 2:
        return False

    salt_hex, saved_hex = parts
    if not salt_hex or not saved_hex:
        return False

    try:
        salt = bytes.fromhex(salt_hex)
        saved = bytes.fromhex(saved_hex)
    except ValueError:
        return False

    digest = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, 200000, dklen=64)
    return hmac.compare_digest(digest, saved)


def ensure_positive_int(value, field_name):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise AppError(f"{field_name} precisa ser um inteiro positivo.", 400, "VALIDATION_ERROR")

    if parsed <= 0:
        raise AppError(f"{field_name} precisa ser um inteiro positivo.", 400, "VALIDATION_ERROR")

    return parsed


def read_json_bytes(raw_bytes):
    if not raw_bytes:
        return {}

    try:
        return json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError:
        raise AppError("JSON invalido.", 400, "INVALID_JSON")


def get_session_token(headers):
    bearer = get_bearer_token(headers)
    if bearer:
        return bearer
    cookies = parse_cookies(headers.get("Cookie") if headers else "")
    return cookies.get("urbe_auth") or None


def get_bearer_token(headers):
    auth_header = headers.get("Authorization", "")
    parts = auth_header.split(" ", 1)
    if len(parts) != 2:
        return None

    scheme, value = parts
    if scheme != "Bearer" or not value:
        return None

    return value


def parse_cookies(cookie_header):
    raw = str(cookie_header or "")
    cookies = {}
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        cookies[urllib.parse.unquote(key.strip())] = urllib.parse.unquote(value.strip())
    return cookies


def build_cookie(name, value, path="/", max_age=None, same_site="Strict", http_only=True, secure=False):
    segments = [
        f"{urllib.parse.quote(str(name))}={urllib.parse.quote(str(value))}",
        f"Path={path}",
        f"SameSite={same_site}",
    ]
    if max_age is not None:
        segments.append(f"Max-Age={max(0, int(max_age))}")
    if http_only:
        segments.append("HttpOnly")
    if secure:
        segments.append("Secure")
    return "; ".join(segments)


class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._hits = {}

    def allow(self, key, limit, window_seconds):
        now = time.time()
        window = max(1, int(window_seconds or 1))
        cap = max(1, int(limit or 1))
        with self._lock:
            stamps = [stamp for stamp in self._hits.get(key, []) if now - stamp < window]
            if len(stamps) >= cap:
                self._hits[key] = stamps
                return False
            stamps.append(now)
            self._hits[key] = stamps
            return True


def fill_template(template, values):
    result = str(template or "")
    for key, value in (values or {}).items():
        result = result.replace(f"{{{key}}}", str(value if value is not None else ""))
    return result


def load_env_file(path):
    if not path or not os.path.isfile(path):
        return False

    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key.startswith("#"):
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ.setdefault(key, value)
    return True


def load_local_env():
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, os.pardir))
    for candidate in (os.path.join(os.getcwd(), ".env"), os.path.join(repo_root, ".env")):
        if load_env_file(candidate):
            return candidate
    return None


def normalize_openpix_event(event):
    return str(event or "").strip().lower()


def extract_openpix_event(body):
    if not isinstance(body, dict):
        return ""
    return str(body.get("event") or body.get("evento") or "").strip()


def extract_openpix_correlation_id(body):
    if not isinstance(body, dict):
        return ""

    charge = body.get("charge") if isinstance(body.get("charge"), dict) else {}
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    pix = body.get("pix") if isinstance(body.get("pix"), dict) else {}
    pix_charge = pix.get("charge") if isinstance(pix.get("charge"), dict) else {}

    return str(
        body.get("correlationID")
        or charge.get("correlationID")
        or data.get("correlationID")
        or pix_charge.get("correlationID")
        or ""
    ).strip()


def is_openpix_paid_event(event, body=None):
    normalized = normalize_openpix_event(event)
    if normalized in OPENPIX_PAID_EVENTS:
        return True
    if not isinstance(body, dict):
        return False
    charge = body.get("charge") if isinstance(body.get("charge"), dict) else {}
    status = str(charge.get("status") or "").strip().upper()
    return not normalized and status in {"COMPLETED", "COMPLETE", "CONCLUDED", "PAID"}


def is_openpix_expired_event(event):
    return normalize_openpix_event(event) in OPENPIX_EXPIRED_EVENTS


def openpix_signature_from_headers(headers):
    if not headers:
        return ""
    for name in (
        "X-OpenPix-Signature",
        "X-Openpix-Signature",
        "x-openpix-signature",
        "X-Webhook-Signature",
        "x-webhook-signature",
    ):
        value = headers.get(name)
        if value:
            return str(value).strip()
    return ""


def verify_openpix_signature(raw_body, signature, secret):
    if not raw_body or not signature or not secret:
        return False

    raw_signature = str(signature).strip()
    if raw_signature.startswith("sha256="):
        raw_signature = raw_signature.split("=", 1)[1]

    digest = hmac.new(str(secret).encode("utf-8"), raw_body, hashlib.sha256)
    expected_hex = digest.hexdigest()
    expected_b64 = base64.b64encode(digest.digest()).decode("ascii")

    for expected in (expected_hex, expected_hex.upper(), expected_b64):
        if len(raw_signature) != len(expected):
            continue
        if hmac.compare_digest(raw_signature, expected):
            return True
    return False
