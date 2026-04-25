import copy
import datetime as dt
import hashlib
import hmac
import json
import secrets
import urllib.parse

from .errors import AppError


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


def build_cookie(name, value, path="/", max_age=None, same_site="Strict", http_only=True):
    segments = [
        f"{urllib.parse.quote(str(name))}={urllib.parse.quote(str(value))}",
        f"Path={path}",
        f"SameSite={same_site}",
    ]
    if max_age is not None:
        segments.append(f"Max-Age={max(0, int(max_age))}")
    if http_only:
        segments.append("HttpOnly")
    return "; ".join(segments)


def fill_template(template, values):
    result = str(template or "")
    for key, value in (values or {}).items():
        result = result.replace(f"{{{key}}}", str(value if value is not None else ""))
    return result


def verify_openpix_signature(raw_body, signature, secret):
    if not raw_body or not signature or not secret:
        return False

    raw_signature = str(signature).strip()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    if raw_signature.startswith("sha256="):
        raw_signature = raw_signature.split("=", 1)[1]

    return hmac.compare_digest(raw_signature, expected)
