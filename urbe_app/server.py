import os
import time
from collections import defaultdict, deque

from ._loader import export_public, load_root_module

module = load_root_module("urbe_app._legacy_server", "server.py")
export_public(module, globals())


def _split_env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


ALLOWED_ORIGINS = set(_split_env_list("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"))
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "").strip()
if PUBLIC_ORIGIN:
    ALLOWED_ORIGINS.add(PUBLIC_ORIGIN)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Resource-Policy": "same-origin",
}

if os.getenv("ENABLE_HSTS", "false").lower() in {"1", "true", "yes"}:
    SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "120"))
AUTH_RATE_LIMIT_MAX_REQUESTS = int(os.getenv("AUTH_RATE_LIMIT_MAX_REQUESTS", "20"))
_rate_limit_buckets = defaultdict(deque)


def _request_ip(handler):
    forwarded_for = handler.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return handler.client_address[0] if handler.client_address else "unknown"


def _is_rate_limited(handler, path):
    now = time.time()
    ip = _request_ip(handler)
    is_auth_path = path.startswith("/api/auth/")
    limit = AUTH_RATE_LIMIT_MAX_REQUESTS if is_auth_path else RATE_LIMIT_MAX_REQUESTS
    key = f"{ip}:{'auth' if is_auth_path else 'api'}"
    bucket = _rate_limit_buckets[key]

    while bucket and bucket[0] <= now - RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()

    if len(bucket) >= limit:
        return True

    bucket.append(now)
    return False


def get_cors_headers_for(handler):
    origin = handler.headers.get("Origin", "").strip()
    if origin and origin in ALLOWED_ORIGINS:
        allow_origin = origin
    elif not origin:
        allow_origin = ""
    else:
        allow_origin = "null"

    headers = {
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Max-Age": "86400",
        "Vary": "Origin",
    }
    if allow_origin:
        headers["Access-Control-Allow-Origin"] = allow_origin
    return headers


class UrbeHandler(module.UrbeHandler):
    def _security_headers(self):
        return dict(SECURITY_HEADERS)

    def do_OPTIONS(self):
        if self.path.startswith("/api/"):
            self.send_response(204)
            headers = {**get_cors_headers_for(self), **self._security_headers()}
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        for key, value in self._security_headers().items():
            self.send_header(key, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_api(self, method, path, parsed_url):
        if _is_rate_limited(self, path):
            headers = {**get_cors_headers_for(self), **self._security_headers(), "Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)}
            self._send_json(429, {"error": "Muitas requisicoes. Tente novamente em instantes.", "code": "RATE_LIMITED"}, headers)
            return
        return super()._handle_api(method, path, parsed_url)

    def _send_json(self, status, payload, headers=None):
        merged_headers = {**self._security_headers(), **(headers or {})}
        return super()._send_json(status, payload, merged_headers)

    def _send_html(self, status, html_text, headers=None):
        merged_headers = {**self._security_headers(), "Cache-Control": "no-store", **(headers or {})}
        return super()._send_html(status, html_text, merged_headers)

    def _serve_static(self, path):
        file_path = module.safe_public_path(path)
        if not file_path:
            self._send_json(403, {"error": "Acesso negado.", "code": "FORBIDDEN"})
            return
        if not os.path.exists(file_path):
            self._send_json(404, {"error": "Arquivo nao encontrado.", "code": "NOT_FOUND"})
            return

        mime_type, _ = module.mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        with open(file_path, "rb") as fh:
            content = fh.read()

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        for key, value in self._security_headers().items():
            self.send_header(key, value)
        if path in {"/", "", "/index.html"}:
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def run():
    server = module.ThreadingHTTPServer(("0.0.0.0", module.CONFIG.port), UrbeHandler)
    print(f"Urbe disponivel em http://localhost:{module.CONFIG.port}")
    server.serve_forever()


globals()["UrbeHandler"] = UrbeHandler
globals()["run"] = run
