import html
import json
import mimetypes
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .bunny import (
    build_signed_embed_url,
    create_bunny_video,
    fetch_bunny_video,
    lookup_bunny_video,
    public_bunny_video,
)
from .config import load_config
from .errors import AppError
from .payments import create_payment_gateway
from .service import UrbeService
from .store import JsonStore, PostgresStore
from .utils import build_cookie, get_bearer_token, parse_cookies, read_json_bytes, verify_openpix_signature

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(PACKAGE_DIR, os.pardir))
ROOT_DIR = REPO_ROOT if os.path.isdir(os.path.join(REPO_ROOT, "public")) else os.getcwd()
PUBLIC_DIR = os.path.join(ROOT_DIR, "public")
CONFIG = load_config()
STORE = PostgresStore(CONFIG.database_url) if CONFIG.database_url else JsonStore(CONFIG.db_file)
SERVICE = UrbeService(STORE, CONFIG)
PAYMENT_GATEWAY = create_payment_gateway(CONFIG.payments)


def lookup_configured_bunny_video(library_id, video_id):
    return lookup_bunny_video(CONFIG.bunny.api_key, library_id, video_id)

def get_cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Max-Age": "86400",
    }

def watch_token_copy(code):
    if code == "PLAYBACK_USED":
        return "Esta visualizacao unica ja foi usada. O token esta gasto."
    if code == "PLAYBACK_FORBIDDEN":
        return "O token continua em sessao neste navegador. Volte para Minhas cotas e toque em Continuar."
    if code in {
        "PLAYBACK_EXPIRED",
        "BUNNY_EMBED_FAILED",
        "INVALID_BUNNY_IDENTIFIERS",
        "BUNNY_VIDEO_NOT_FOUND",
        "BUNNY_NOT_READY",
        "BUNNY_LOOKUP_FAILED",
    }:
        return "Seu token de visualizacao nao foi gasto. A cota continua pronta para assistir."
    return "Se a sessao Bunny nao chegou a abrir, o token nao foi gasto."


def watch_post_message_script(payload):
    raw = json.dumps(payload, ensure_ascii=True)
    return f"""
    <script>
      (function () {{
        var payload = {raw};
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage(payload, window.location.origin);
          }}
        }} catch (error) {{}}
      }})();
    </script>
    """


def render_watch_error_page(message, code=""):
    safe = html.escape(str(message or "Falha ao abrir reproducao."))
    token_line = html.escape(watch_token_copy(code))
    token_spent = code == "PLAYBACK_USED"
    script = watch_post_message_script(
        {
            "source": "urbe-watch",
            "ok": False,
            "tokenSpent": token_spent,
            "code": code or "",
            "message": str(message or ""),
        }
    )
    return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Urbe | Reproducao</title>
    <style>
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #0b1017;
        color: #f4f7fb;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      }}
      main {{
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 12px;
        padding: 1.1rem 1.2rem;
        max-width: 520px;
      }}
      p {{ margin: 0.35rem 0 0; color: #cfd8e6; line-height: 1.5; }}
      strong {{ color: #ffe8bf; }}
    </style>
  </head>
  <body>
    <main>
      <strong>Player Bunny indisponivel</strong>
      <p>{safe}</p>
      <p>{token_line}</p>
    </main>
    {script}
  </body>
</html>"""

def render_watch_page(title, embed_url):
    safe_title = html.escape(str(title or "Urbe"))
    safe_embed = html.escape(str(embed_url or ""))
    script = watch_post_message_script(
        {
            "source": "urbe-watch",
            "ok": True,
            "tokenSpent": True,
            "code": "PLAYBACK_OPEN",
            "message": "Sessao Bunny aberta. Token usado.",
        }
    )
    return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{safe_title} | Urbe</title>
    <style>
      body {{ margin: 0; background: #000; color: #f7f1e5; font-family: system-ui, sans-serif; }}
      .watch-banner {{
        position: absolute;
        left: 0.8rem;
        top: 0.8rem;
        z-index: 2;
        padding: 0.35rem 0.6rem;
        border-radius: 999px;
        background: rgba(11, 9, 8, 0.72);
        font-size: 0.75rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }}
      iframe {{
        border: 0;
        width: 100vw;
        height: 100vh;
      }}
    </style>
  </head>
  <body>
    <div class="watch-banner">Sessao unica · token usado ao abrir</div>
    <iframe
      src="{safe_embed}"
      title="{safe_title}"
      allow="accelerometer; gyroscope; autoplay; encrypted-media; picture-in-picture"
      allowfullscreen
    ></iframe>
    {script}
  </body>
</html>"""

def safe_public_path(raw_path):
    decoded = urllib.parse.unquote(raw_path)
    normalized = os.path.normpath(decoded)
    normalized = normalized.lstrip("/\\")
    if normalized in {"", "."}:
        normalized = "index.html"

    file_path = os.path.abspath(os.path.join(PUBLIC_DIR, normalized))
    public_abs = os.path.abspath(PUBLIC_DIR)
    if file_path != public_abs and not file_path.startswith(public_abs + os.sep):
        return None

    if os.path.isdir(file_path):
        file_path = os.path.join(file_path, "index.html")
    return file_path

class UrbeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    routes = [
        {"method": "GET", "pattern": re.compile(r"^/api/health$"), "auth": False, "handler": "api_health"},
        {"method": "GET", "pattern": re.compile(r"^/api/payments/config$"), "auth": False, "handler": "api_payments_config"},
        {"method": "POST", "pattern": re.compile(r"^/api/auth/register$"), "auth": False, "handler": "api_auth_register"},
        {"method": "POST", "pattern": re.compile(r"^/api/auth/login$"), "auth": False, "handler": "api_auth_login"},
        {"method": "POST", "pattern": re.compile(r"^/api/auth/logout$"), "auth": True, "handler": "api_auth_logout"},
        {"method": "GET", "pattern": re.compile(r"^/api/auth/me$"), "auth": True, "handler": "api_auth_me"},
        {"method": "GET", "pattern": re.compile(r"^/api/movies$"), "auth": False, "handler": "api_movies_list"},
        {"method": "GET", "pattern": re.compile(r"^/api/movies/([^/]+)$"), "auth": False, "handler": "api_movies_get"},
        {"method": "POST", "pattern": re.compile(r"^/api/movies$"), "auth": True, "handler": "api_movies_create"},
        {"method": "POST", "pattern": re.compile(r"^/api/movies/([^/]+)/buy$"), "auth": True, "handler": "api_movies_buy"},
        {
            "method": "POST",
            "pattern": re.compile(r"^/api/payments/primary/([^/]+)/checkout$"),
            "auth": True,
            "handler": "api_payments_primary_checkout",
        },
        {"method": "GET", "pattern": re.compile(r"^/api/listings$"), "auth": False, "handler": "api_listings_list"},
        {"method": "POST", "pattern": re.compile(r"^/api/shares/([^/]+)/listings$"), "auth": True, "handler": "api_shares_create_listing"},
        {"method": "POST", "pattern": re.compile(r"^/api/listings/([^/]+)/cancel$"), "auth": True, "handler": "api_listings_cancel"},
        {"method": "POST", "pattern": re.compile(r"^/api/listings/([^/]+)/buy$"), "auth": True, "handler": "api_listings_buy"},
        {
            "method": "POST",
            "pattern": re.compile(r"^/api/payments/listings/([^/]+)/checkout$"),
            "auth": True,
            "handler": "api_payments_listing_checkout",
        },
        {
            "method": "POST",
            "pattern": re.compile(r"^/api/payments/orders/([^/]+)/confirm$"),
            "auth": True,
            "handler": "api_payments_order_confirm",
        },
        {
            "method": "POST",
            "pattern": re.compile(r"^/api/payments/orders/([^/]+)/cancel$"),
            "auth": True,
            "handler": "api_payments_order_cancel",
        },
        {"method": "GET", "pattern": re.compile(r"^/api/me/shares$"), "auth": True, "handler": "api_me_shares"},
        {"method": "GET", "pattern": re.compile(r"^/api/me/orders$"), "auth": True, "handler": "api_me_orders"},
        {"method": "GET", "pattern": re.compile(r"^/api/me/transactions$"), "auth": True, "handler": "api_me_transactions"},
        {"method": "GET", "pattern": re.compile(r"^/api/bunny/status$"), "auth": False, "handler": "api_bunny_status"},
        {"method": "POST", "pattern": re.compile(r"^/api/bunny/videos$"), "auth": True, "handler": "api_bunny_create_video"},
        {"method": "POST", "pattern": re.compile(r"^/api/access/consume$"), "auth": True, "handler": "api_access_consume"},
        {"method": "POST", "pattern": re.compile(r"^/api/access/resume$"), "auth": True, "handler": "api_access_resume"},
        # === NOVA ROTA DO WEBHOOK OPENPIX ===
        {
            "method": "POST",
            "pattern": re.compile(r"^/api/payments/webhook/openpix$"),
            "auth": False,
            "handler": "api_payments_openpix_webhook",
        },
    ]

    def log_message(self, format_string, *args):  # noqa: A003
        # Keep output concise for local dev.
        sys.stdout.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format_string % args))

    def do_OPTIONS(self):
        if self.path.startswith("/api/"):
            self.send_response(204)
            for key, value in get_cors_headers().items():
                self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_api(method, path, parsed)
            return

        if path.startswith("/watch/"):
            self._handle_watch(path)
            return

        if method != "GET":
            self._send_json(405, {"error": "Metodo nao permitido.", "code": "METHOD_NOT_ALLOWED"})
            return

        self._serve_static(path)

    def _read_body(self):
        content_length = self.headers.get("Content-Length", "0")
        try:
            size = int(content_length)
        except ValueError:
            raise AppError("Payload invalido.", 400, "INVALID_PAYLOAD")

        if size > 1_000_000:
            raise AppError("Payload muito grande.", 413, "PAYLOAD_TOO_LARGE")

        raw = self.rfile.read(size) if size > 0 else b""
        return read_json_bytes(raw), raw

    def _handle_api(self, method, path, parsed_url):
        cors_headers = get_cors_headers()

        for route in self.routes:
            if route["method"] != method:
                continue
            match = route["pattern"].match(path)
            if not match:
                continue

            try:
                if method in {"POST", "PUT", "PATCH"}:
                    body, raw_body = self._read_body()
                else:
                    body, raw_body = {}, b""
                session_token = None
                user = None
                if route["auth"]:
                    session_token = get_bearer_token(self.headers)
                    user = SERVICE.get_user_by_session(session_token)
                    if not user:
                        raise AppError("Nao autenticado.", 401, "UNAUTHORIZED")

                query_params = urllib.parse.parse_qs(parsed_url.query)
                context = {
                    "body": body,
                    "rawBody": raw_body,
                    "user": user,
                    "sessionToken": session_token,
                    "query": query_params,
                    "headers": self.headers,
                }

                handler_fn = getattr(self, route["handler"])
                status, response_body, extra_headers = handler_fn(context, *match.groups())
                headers = {**cors_headers, **(extra_headers or {})}
                self._send_json(status, response_body, headers)
                return
            except AppError as error:
                self._send_json(error.status, {"error": error.message, "code": error.code}, cors_headers)
                return
            except Exception as error:  # pragma: no cover - defensive path
                print("Unhandled error:", error)
                self._send_json(500, {"error": "Erro interno do servidor.", "code": "INTERNAL_ERROR"}, cors_headers)
                return

        self._send_json(404, {"error": "Rota nao encontrada.", "code": "NOT_FOUND"}, cors_headers)

    def _handle_watch(self, path):
        match = re.match(r"^/watch/([^/]+)$", path)
        clear_cookie = build_cookie("urbe_playback", "", path="/watch", max_age=0, same_site="Strict", http_only=True)

        if not match:
            self._send_html(
                404,
                render_watch_error_page("Link de reproducao invalido.", "PLAYBACK_NOT_FOUND"),
                {"Set-Cookie": clear_cookie},
            )
            return

        playback_token = match.group(1)
        cookies = parse_cookies(self.headers.get("Cookie", ""))
        client_secret = cookies.get("urbe_playback", "")

        try:
            result = SERVICE.open_playback_session(
                playback_token,
                {
                    "clientSecret": client_secret,
                    "ipAddress": self.client_address[0] if self.client_address else "",
                    "userAgent": self.headers.get("User-Agent", ""),
                },
                lambda info: build_signed_embed_url(
                    iframe_host=CONFIG.bunny.iframe_host,
                    library_id=info["libraryId"],
                    video_id=info["videoId"],
                    embed_token_key=CONFIG.bunny.embed_token_key,
                    expires_in_seconds=90,
                    session_tag=info.get("sessionTag", ""),
                ),
                bunny_lookup=lookup_configured_bunny_video,
            )
            page = render_watch_page(result["movie"]["title"], result["playback"]["embedUrl"])
            self._send_html(
                200,
                page,
                {
                    "Cache-Control": "no-store",
                    "Set-Cookie": clear_cookie,
                },
            )
            return
        except AppError as error:
            self._send_html(
                error.status,
                render_watch_error_page(error.message, error.code),
                {
                    "Cache-Control": "no-store",
                    "Set-Cookie": clear_cookie,
                },
            )
            return
        except Exception as error:  # pragma: no cover - defensive path
            print("Unhandled watch error:", error)
            self._send_html(
                500,
                render_watch_error_page("Falha ao abrir reproducao.", "INTERNAL_ERROR"),
                {
                    "Cache-Control": "no-store",
                    "Set-Cookie": clear_cookie,
                },
            )

    def _serve_static(self, path):
        file_path = safe_public_path(path)
        if not file_path:
            self._send_json(403, {"error": "Acesso negado.", "code": "FORBIDDEN"})
            return
        if not os.path.exists(file_path):
            self._send_json(404, {"error": "Arquivo nao encontrado.", "code": "NOT_FOUND"})
            return

        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        with open(file_path, "rb") as fh:
            content = fh.read()

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, status, payload, headers=None):
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def _send_html(self, status, html_text, headers=None):
        body_bytes = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    # API handlers
    def api_health(self, _ctx):
        return 200, {"status": "ok", "service": "urbe"}, {}

    def api_payments_openpix_webhook(self, _ctx):
        body = _ctx["body"]
        raw_body = _ctx.get("rawBody", b"")
        signature = self.headers.get("X-Openpix-Signature")
        secret = CONFIG.payments.openpix.webhook_secret

        if not secret:
            return 500, {"error": "OPENPIX_WEBHOOK_SECRET nao configurado"}, {}

        if not signature or not verify_openpix_signature(raw_body, signature, secret):
            return 401, {"error": "assinatura invalida"}, {}

        event = body.get("event")
        if event == "pix_received":
            correlation_id = body.get("data", {}).get("correlationID")
            if correlation_id:
                try:
                    SERVICE.confirm_order_payment(correlation_id)
                    return 200, {"status": "ok"}, {}
                except Exception as e:
                    print(f"Erro no webhook OpenPix: {e}")
                    return 500, {"error": "falha interna"}, {}
            else:
                return 400, {"error": "correlationID ausente"}, {}
        else:
            return 200, {"status": "ignored"}, {}

    def api_payments_config(self, _ctx):
        return 200, {"payments": SERVICE.get_payment_config()}, {}

    def api_auth_register(self, ctx):
        result = SERVICE.register_user(ctx["body"])
        return 201, result, {}

    def api_auth_login(self, ctx):
        result = SERVICE.login(ctx["body"])
        return 200, result, {}

    def api_auth_logout(self, ctx):
        result = SERVICE.logout(ctx["sessionToken"])
        return 200, result, {}

    def api_auth_me(self, ctx):
        return 200, {"user": ctx["user"]}, {}

    def api_movies_list(self, _ctx):
        return 200, {"movies": SERVICE.list_movies()}, {}

    def api_movies_get(self, _ctx, movie_id):
        return 200, {"movie": SERVICE.get_movie(movie_id)}, {}

    def api_movies_create(self, ctx):
        body = dict(ctx["body"] or {})
        if CONFIG.bunny.api_key:
            video_id = str(body.get("bunnyVideoId") or "").strip()
            library_id = str(body.get("bunnyLibraryId") or CONFIG.bunny.default_library_id or "").strip()
            if video_id and library_id:
                fetch_bunny_video(CONFIG.bunny.api_key, library_id, video_id)
        movie = SERVICE.create_movie(ctx["user"]["id"], body)
        return 201, {"movie": movie}, {}

    def api_movies_buy(self, ctx, movie_id):
        purchase = SERVICE.buy_primary_share(ctx["user"]["id"], movie_id)
        return 201, purchase, {}

    def api_payments_primary_checkout(self, ctx, movie_id):
        result = SERVICE.start_primary_checkout(ctx["user"]["id"], movie_id, PAYMENT_GATEWAY)
        return 201, result, {}

    def api_listings_list(self, ctx):
        movie_id = (ctx["query"].get("movieId") or [None])[0]
        listings = SERVICE.list_market(movie_id)
        return 200, {"listings": listings}, {}

    def api_shares_create_listing(self, ctx, share_id):
        listing = SERVICE.create_listing(ctx["user"]["id"], share_id, ctx["body"].get("priceCents"))
        return 201, {"listing": listing}, {}

    def api_listings_cancel(self, ctx, listing_id):
        listing = SERVICE.cancel_listing(ctx["user"]["id"], listing_id)
        return 200, {"listing": listing}, {}

    def api_listings_buy(self, ctx, listing_id):
        purchase = SERVICE.buy_listing(ctx["user"]["id"], listing_id)
        return 201, purchase, {}

    def api_payments_listing_checkout(self, ctx, listing_id):
        result = SERVICE.start_listing_checkout(ctx["user"]["id"], listing_id, PAYMENT_GATEWAY)
        return 201, result, {}

    def api_payments_order_confirm(self, ctx, order_id):
        session_id = str(ctx["body"].get("sessionId") or "")
        result = SERVICE.confirm_payment_order(ctx["user"]["id"], order_id, session_id, PAYMENT_GATEWAY)
        return 200, result, {}

    def api_payments_order_cancel(self, ctx, order_id):
        result = SERVICE.cancel_payment_order(ctx["user"]["id"], order_id)
        return 200, result, {}

    def api_me_shares(self, ctx):
        return 200, {"shares": SERVICE.get_user_shares(ctx["user"]["id"])}, {}

    def api_me_orders(self, ctx):
        return 200, {"orders": SERVICE.get_user_payment_orders(ctx["user"]["id"])}, {}

    def api_me_transactions(self, ctx):
        return 200, {"transactions": SERVICE.get_user_transactions(ctx["user"]["id"])}, {}

    def api_access_consume(self, ctx):
        payload = SERVICE.consume_access_token(
            ctx["user"]["id"],
            str(ctx["body"].get("token") or ""),
            bunny_lookup=lookup_configured_bunny_video,
        )
        return 200, payload, self._playback_headers(payload)

    def api_access_resume(self, ctx):
        payload = SERVICE.resume_playback(
            ctx["user"]["id"],
            token_value=str(ctx["body"].get("token") or ""),
            share_id=str(ctx["body"].get("shareId") or ""),
        )
        return 200, payload, self._playback_headers(payload)

    def _playback_headers(self, payload):
        playback = payload.get("playback") or {}
        playback_secret = playback.get("clientSecret", "")
        if "clientSecret" in playback:
            del playback["clientSecret"]
        headers = {"Cache-Control": "no-store"}
        if playback_secret:
            headers["Set-Cookie"] = build_cookie(
                "urbe_playback",
                playback_secret,
                path="/watch",
                max_age=CONFIG.playback_session_seconds,
                same_site="Strict",
                http_only=True,
            )
        return headers

    def api_bunny_status(self, _ctx):
        return 200, {"bunny": SERVICE.get_bunny_status()}, {}

    def api_bunny_create_video(self, ctx):
        library_id = str(ctx["body"].get("libraryId") or CONFIG.bunny.default_library_id or "")
        bunny_video = create_bunny_video(
            api_key=CONFIG.bunny.api_key,
            library_id=library_id,
            title=ctx["body"].get("title"),
            collection_id=ctx["body"].get("collectionId"),
            thumbnail_time=ctx["body"].get("thumbnailTime"),
        )
        public_video = public_bunny_video(bunny_video, library_id)
        return 201, {"bunnyVideo": bunny_video, **public_video}, {}


def run():
    server = ThreadingHTTPServer(("0.0.0.0", CONFIG.port), UrbeHandler)
    print(f"Urbe disponivel em http://localhost:{CONFIG.port}")
    server.serve_forever()

if __name__ == "__main__":
    run()
