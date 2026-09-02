import datetime as dt
import re
from copy import deepcopy
from urllib.parse import urlparse

from .errors import AppError
from .utils import ensure_positive_int, hash_password, now_iso, random_token, verify_password


ALLOWED_MOVIE_GENRES = [
    "Drama",
    "Comedia",
    "Acao",
    "Suspense",
    "Terror",
    "Romance",
    "Ficcao Cientifica",
    "Documentario",
    "Animacao",
    "Aventura",
    "Fantasia",
]

def clone(value):
    return deepcopy(value)

def parse_date_ms(value):
    if not value:
        return 0
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return int(dt.datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return 0

def utc_now_ms():
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)

def normalize_email(email):
    return str(email or "").strip().lower()

def normalize_lookup_key(value):
    text = str(value or "").strip().lower()
    replacements = {
        "á": "a",
        "à": "a",
        "â": "a",
        "ã": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for from_char, to_char in replacements.items():
        text = text.replace(from_char, to_char)
    text = re.sub(r"\s+", " ", text)
    return text

def normalize_movie_genre(value):
    key = normalize_lookup_key(value)
    if not key:
        return None
    for genre in ALLOWED_MOVIE_GENRES:
        if normalize_lookup_key(genre) == key:
            return genre
    return None

def normalize_movie_cast(value):
    if isinstance(value, list):
        entries = value
    else:
        entries = str(value or "").split(",")

    cleaned = []
    seen = set()
    for entry in entries:
        actor = str(entry or "").strip()
        if not actor:
            continue
        if actor in seen:
            continue
        cleaned.append(actor)
        seen.add(actor)
        if len(cleaned) >= 20:
            break
    return cleaned

def normalize_movie_release_year(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    max_year = dt.datetime.utcnow().year + 2
    if parsed < 1888 or parsed > max_year:
        return None
    return parsed

def normalize_movie_duration_minutes(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    if parsed < 1 or parsed > 600:
        return None
    return parsed

def normalize_movie_http_url(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return raw

def normalize_movie_cover_image_url(value):
    return normalize_movie_http_url(value)

def normalize_movie_trailer_url(value):
    return normalize_movie_http_url(value)

def sanitize_user(user):
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "createdAt": user["createdAt"],
    }

def next_id(db, key, prefix):
    if key not in db["counters"]:
        db["counters"][key] = 0
    db["counters"][key] += 1
    return f"{prefix}_{db['counters'][key]}"

def compute_movie_stats(db, movie_id):
    shares = [share for share in db["shares"] if share["movieId"] == movie_id]
    active_listings = [listing for listing in db["listings"] if listing["movieId"] == movie_id and listing["status"] == "active"]

    floor_listing_cents = None
    if active_listings:
        floor_listing_cents = min(int(item["priceCents"]) for item in active_listings)

    primary_available = len([share for share in shares if share["state"] == "available"])
    reserved_primary = len([share for share in shares if share["state"] == "reserved"])
    listed = len([share for share in shares if share["state"] == "listed"])
    consumed = len([share for share in shares if share["state"] == "consumed"])
    owned = len([share for share in shares if share["state"] == "owned"])

    return {
        "primaryAvailable": primary_available,
        "reservedPrimary": reserved_primary,
        "listed": listed,
        "consumed": consumed,
        "owned": owned,
        "sold": owned + listed + consumed,
        "floorListingCents": floor_listing_cents,
        "floorListing": None if floor_listing_cents is None else floor_listing_cents / 100,
    }

def to_public_movie(movie, producer, stats):
    return {
        "id": movie["id"],
        "title": movie["title"],
        "description": movie.get("description"),
        "director": str(movie.get("director") or "").strip() or None,
        "coverImageUrl": normalize_movie_cover_image_url(movie.get("coverImageUrl")),
        "genre": normalize_movie_genre(movie.get("genre")),
        "durationMinutes": normalize_movie_duration_minutes(movie.get("durationMinutes")),
        "releaseYear": normalize_movie_release_year(movie.get("releaseYear")),
        "trailerUrl": normalize_movie_trailer_url(movie.get("trailerUrl")),
        "cast": normalize_movie_cast(movie.get("cast")),
        "priceCents": movie["priceCents"],
        "price": movie["priceCents"] / 100,
        "totalShares": movie["totalShares"],
        "bunnyVideoId": movie["bunnyVideoId"],
        "bunnyLibraryId": movie["bunnyLibraryId"],
        "status": movie["status"],
        "createdAt": movie["createdAt"],
        "producer": sanitize_user(producer) if producer else None,
        "stats": stats,
    }

def compact_movie_for_listing(movie):
    return {
        "id": movie["id"],
        "title": movie["title"],
        "director": str(movie.get("director") or "").strip() or None,
        "coverImageUrl": normalize_movie_cover_image_url(movie.get("coverImageUrl")),
        "genre": normalize_movie_genre(movie.get("genre")),
        "durationMinutes": normalize_movie_duration_minutes(movie.get("durationMinutes")),
        "releaseYear": normalize_movie_release_year(movie.get("releaseYear")),
        "trailerUrl": normalize_movie_trailer_url(movie.get("trailerUrl")),
        "cast": normalize_movie_cast(movie.get("cast")),
        "bunnyVideoId": movie["bunnyVideoId"],
        "bunnyLibraryId": movie["bunnyLibraryId"],
    }


def public_access_token(token):
    if not token:
        return None
    payload = {
        "id": token.get("id"),
        "status": token.get("status"),
        "reason": token.get("reason"),
        "issuedAt": token.get("issuedAt"),
        "usedAt": token.get("usedAt"),
        "revokedAt": token.get("revokedAt"),
    }
    if token.get("status") in {"active", "redeeming"}:
        payload["token"] = token.get("token")
    return payload


TOKEN_ORIGIN_COPY = {
    "resale": "Emitido na revenda.",
    "primary_purchase": "Emitido na compra original.",
}


def remaining_seconds(iso_value):
    ms = parse_date_ms(iso_value) - utc_now_ms()
    return max(0, int(ms / 1000))


def describe_token_state(share, token, listing, pending_playback, movie):
    bunny_ready = bool((movie or {}).get("bunnyVideoId") and (movie or {}).get("bunnyLibraryId"))
    token_status = (token or {}).get("status")
    listing_status = (listing or {}).get("status")
    share_state = (share or {}).get("state")
    origin = TOKEN_ORIGIN_COPY.get((token or {}).get("reason"), "")

    if listing_status == "reserved":
        code = "checkout_reserved"
    elif share_state == "listed":
        code = "held_for_sale"
    elif token_status == "redeeming" or pending_playback:
        code = "opening_player"
    elif share_state == "owned" and token_status == "active":
        code = "ready"
    elif share_state == "consumed" or token_status == "used":
        code = "used"
    elif token_status == "revoked":
        code = "revoked"
    elif share_state == "reserved":
        code = "checkout_reserved"
    else:
        code = "missing"

    stories = {
        "ready": {
            "label": "Pronta para assistir",
            "tokenLabel": "Token ativo",
            "detail": " ".join(
                part
                for part in (
                    "1 visualizacao restante.",
                    origin,
                    "O token so e gasto se a sessao Bunny abrir.",
                )
                if part
            ),
            "steps": [
                {"id": "issued", "label": "Token emitido", "state": "done"},
                {"id": "ready", "label": "Aguardando assistir", "state": "current"},
                {"id": "bunny", "label": "Sessao Bunny", "state": "todo"},
            ],
        },
        "opening_player": {
            "label": "Abrindo player",
            "tokenLabel": "Token em uso",
            "detail": "Sessao Bunny em andamento. Se o player nao abrir, o token volta a ficar ativo.",
            "steps": [
                {"id": "issued", "label": "Token emitido", "state": "done"},
                {"id": "ready", "label": "Aguardando assistir", "state": "done"},
                {"id": "bunny", "label": "Sessao Bunny", "state": "current"},
            ],
        },
        "held_for_sale": {
            "label": "A venda",
            "tokenLabel": "Token em espera",
            "detail": "O token continua valido, mas assistir fica bloqueado enquanto a cota esta no mercado. Se vender, este token e revogado e o comprador recebe um novo.",
            "steps": [
                {"id": "issued", "label": "Token emitido", "state": "done"},
                {"id": "held", "label": "Em espera no mercado", "state": "current"},
                {"id": "bunny", "label": "Sessao Bunny", "state": "blocked"},
            ],
        },
        "checkout_reserved": {
            "label": "Checkout em andamento",
            "tokenLabel": "Token reservado",
            "detail": "A cota esta presa em um pagamento. Se o checkout expirar, ela volta para voce.",
            "steps": [
                {"id": "issued", "label": "Token emitido", "state": "done"},
                {"id": "held", "label": "Reservada no checkout", "state": "current"},
                {"id": "bunny", "label": "Sessao Bunny", "state": "blocked"},
            ],
        },
        "used": {
            "label": "Assistida",
            "tokenLabel": "Token usado",
            "detail": "A visualizacao unica ja foi liberada no Bunny. Esta cota nao volta ao mercado.",
            "steps": [
                {"id": "issued", "label": "Token emitido", "state": "done"},
                {"id": "ready", "label": "Aguardando assistir", "state": "done"},
                {"id": "bunny", "label": "Sessao Bunny", "state": "done"},
            ],
        },
        "revoked": {
            "label": "Token revogado",
            "tokenLabel": "Revogado na revenda",
            "detail": "O token antigo morreu na transferencia. O comprador recebeu um token novo.",
            "steps": [
                {"id": "issued", "label": "Token emitido", "state": "done"},
                {"id": "revoked", "label": "Revogado na transferencia", "state": "done"},
                {"id": "bunny", "label": "Sessao Bunny", "state": "blocked"},
            ],
        },
        "missing": {
            "label": "Sem token",
            "tokenLabel": "Token ausente",
            "detail": "Esta cota nao tem um token ativo para o player.",
            "steps": [
                {"id": "issued", "label": "Token emitido", "state": "todo"},
                {"id": "ready", "label": "Aguardando assistir", "state": "todo"},
                {"id": "bunny", "label": "Sessao Bunny", "state": "todo"},
            ],
        },
    }
    story = stories.get(code) or stories["missing"]
    can_watch = code == "ready" and bunny_ready
    can_resume = code == "opening_player"
    can_list = code == "ready"
    if code == "ready" and not bunny_ready:
        story = {
            **story,
            "detail": "O token esta ativo, mas o filme nao tem player Bunny. Assistir fica bloqueado para nao gastar a visualizacao.",
            "steps": [
                {"id": "issued", "label": "Token emitido", "state": "done"},
                {"id": "ready", "label": "Aguardando player Bunny", "state": "current"},
                {"id": "bunny", "label": "Sessao Bunny", "state": "blocked"},
            ],
        }

    playback_expires_at = (pending_playback or {}).get("expiresAt")
    return {
        "code": code,
        "label": story["label"],
        "tokenLabel": story["tokenLabel"],
        "detail": story["detail"],
        "steps": story["steps"],
        "bunnyReady": bunny_ready,
        "tokenStatus": token_status,
        "shareState": share_state,
        "remainingViews": 1 if code in {"ready", "opening_player", "held_for_sale", "checkout_reserved"} else 0,
        "canWatch": can_watch,
        "canResume": can_resume,
        "canList": can_list,
        "playbackExpiresAt": playback_expires_at,
        "playbackRemainingSeconds": remaining_seconds(playback_expires_at) if playback_expires_at else 0,
    }


def to_public_checkout(checkout):
    if not checkout:
        return None

    payload = {
        "provider": checkout.get("provider"),
        "sessionId": checkout.get("sessionId"),
        "checkoutUrl": checkout.get("checkoutUrl"),
        "paymentStatus": checkout.get("paymentStatus"),
        "status": checkout.get("status"),
        "paid": checkout.get("paid") is True,
    }
    if checkout.get("pixCopiaECola"):
        payload["pixCopiaECola"] = checkout.get("pixCopiaECola")
    qr_code = checkout.get("qrCodeBase64") or checkout.get("qrCodeImage")
    if qr_code:
        payload["qrCodeBase64"] = qr_code
    if checkout.get("expiresIn") is not None:
        payload["expiresIn"] = checkout.get("expiresIn")
    return payload


def iso_after(*, days=0, minutes=0, seconds=0):
    stamp = dt.datetime.utcnow() + dt.timedelta(days=days, minutes=minutes, seconds=seconds)
    return stamp.replace(microsecond=0).isoformat() + "Z"


class UrbeService:
    def __init__(self, store, config):
        self.store = store
        self.config = config

    def register_user(self, payload):
        normalized_email = normalize_email(payload.get("email"))
        normalized_name = str(payload.get("name") or "").strip()

        if not normalized_name:
            raise AppError("Nome e obrigatorio.", 400, "VALIDATION_ERROR")
        if not normalized_email or "@" not in normalized_email:
            raise AppError("E-mail invalido.", 400, "VALIDATION_ERROR")

        def tx(db):
            self._cleanup_expired_reservations(db)
            existing = next((user for user in db["users"] if user["email"] == normalized_email), None)
            if existing:
                raise AppError("Ja existe usuario com este e-mail.", 409, "EMAIL_IN_USE")

            now = now_iso()
            user = {
                "id": next_id(db, "user", "usr"),
                "name": normalized_name,
                "email": normalized_email,
                "role": "member",
                "passwordHash": hash_password(payload.get("password")),
                "createdAt": now,
            }
            db["users"].append(user)

            session = self._create_session(db, user["id"], now)
            return {
                "user": sanitize_user(user),
                "sessionToken": session["token"],
                "expiresAt": session["expiresAt"],
            }

        return self.store.transaction(tx)

    def login(self, payload):
        normalized_email = normalize_email(payload.get("email"))

        def tx(db):
            self._cleanup_expired_reservations(db)
            user = next((item for item in db["users"] if item["email"] == normalized_email), None)
            if not user or not verify_password(payload.get("password") or "", user.get("passwordHash")):
                raise AppError("Credenciais invalidas.", 401, "INVALID_CREDENTIALS")

            session = self._create_session(db, user["id"], now_iso())
            return {
                "user": sanitize_user(user),
                "sessionToken": session["token"],
                "expiresAt": session["expiresAt"],
            }

        return self.store.transaction(tx)

    def logout(self, session_token):
        if not session_token:
            return {"ok": True}

        def tx(db):
            self._cleanup_expired_reservations(db)
            db["sessions"] = [session for session in db["sessions"] if session["token"] != session_token]
            return {"ok": True}

        self.store.transaction(tx)
        return {"ok": True}

    def get_user_by_session(self, session_token):
        if not session_token:
            return None

        def tx(db):
            self._cleanup_expired_reservations(db)
            return clone(db)

        db = self.store.transaction(tx)
        session = next((item for item in db["sessions"] if item["token"] == session_token), None)
        if not session:
            return None

        if parse_date_ms(session.get("expiresAt")) <= utc_now_ms():
            return None

        user = next((item for item in db["users"] if item["id"] == session["userId"]), None)
        if not user:
            return None

        return sanitize_user(user)

    def list_movies(self):
        def tx(db):
            self._cleanup_expired_reservations(db)
            items = []
            for movie in db["movies"]:
                producer = next((user for user in db["users"] if user["id"] == movie["producerId"]), None)
                stats = compute_movie_stats(db, movie["id"])
                items.append(to_public_movie(movie, producer, stats))
            items.sort(key=lambda item: parse_date_ms(item.get("createdAt")), reverse=True)
            return items

        return self.store.transaction(tx)

    def get_movie(self, movie_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            movie = next((item for item in db["movies"] if item["id"] == movie_id), None)
            if not movie:
                raise AppError("Filme nao encontrado.", 404, "MOVIE_NOT_FOUND")
            producer = next((user for user in db["users"] if user["id"] == movie["producerId"]), None)
            stats = compute_movie_stats(db, movie["id"])
            listings = self._listings_for_movie(db, movie["id"])
            return {
                **to_public_movie(movie, producer, stats),
                "listings": listings,
            }

        return self.store.transaction(tx)

    def create_movie(self, user_id, payload):
        title = str(payload.get("title") or "").strip()
        description = str(payload.get("description") or "").strip()
        director = str(payload.get("director") or "").strip()
        cover_image_url_raw = str(payload.get("coverImageUrl") or "").strip()
        cover_image_url = normalize_movie_cover_image_url(cover_image_url_raw)
        genre = normalize_movie_genre(payload.get("genre"))
        duration_minutes = normalize_movie_duration_minutes(payload.get("durationMinutes"))
        release_year = normalize_movie_release_year(payload.get("releaseYear"))
        trailer_url_raw = str(payload.get("trailerUrl") or "").strip()
        trailer_url = normalize_movie_trailer_url(trailer_url_raw)
        cast = normalize_movie_cast(payload.get("cast"))
        bunny_video_id = str(payload.get("bunnyVideoId") or "").strip()
        bunny_library_id = str(
            payload.get("bunnyLibraryId") or self.config.bunny.default_library_id or ""
        ).strip()

        if not title:
            raise AppError("Titulo e obrigatorio.", 400, "VALIDATION_ERROR")
        if len(director) > 120:
            raise AppError("Diretor muito longo (maximo 120 caracteres).", 400, "VALIDATION_ERROR")
        if not genre:
            allowed = ", ".join(ALLOWED_MOVIE_GENRES)
            raise AppError(f"Genero invalido. Use um dos valores permitidos: {allowed}.", 400, "VALIDATION_ERROR")
        if not duration_minutes:
            raise AppError("Duracao invalida. Informe um valor entre 1 e 600 minutos.", 400, "VALIDATION_ERROR")
        if cover_image_url_raw and not cover_image_url:
            raise AppError("Capa invalida. Use uma URL http(s).", 400, "VALIDATION_ERROR")
        release_year_raw = payload.get("releaseYear")
        if release_year_raw not in (None, "") and release_year is None:
            raise AppError("Ano invalido. Informe um ano entre 1888 e o atual.", 400, "VALIDATION_ERROR")
        if trailer_url_raw and not trailer_url:
            raise AppError("Trailer invalido. Use uma URL http(s).", 400, "VALIDATION_ERROR")
        if any(len(actor) > 80 for actor in cast):
            raise AppError("Nome de ator muito longo (maximo 80 caracteres).", 400, "VALIDATION_ERROR")
        if not bunny_video_id:
            raise AppError("bunnyVideoId e obrigatorio.", 400, "VALIDATION_ERROR")
        if not bunny_library_id:
            raise AppError(
                "bunnyLibraryId e obrigatorio ou defina BUNNY_STREAM_LIBRARY_ID.",
                400,
                "VALIDATION_ERROR",
            )

        total_shares = ensure_positive_int(payload.get("totalShares"), "totalShares")
        price_cents = ensure_positive_int(payload.get("priceCents"), "priceCents")
        if total_shares > 100000:
            raise AppError("totalShares muito alto para esta versao (maximo 100000).", 400, "VALIDATION_ERROR")

        def tx(db):
            self._cleanup_expired_reservations(db)
            user = next((item for item in db["users"] if item["id"] == user_id), None)
            if not user:
                raise AppError("Usuario nao encontrado.", 404, "USER_NOT_FOUND")

            now = now_iso()
            movie = {
                "id": next_id(db, "movie", "mov"),
                "producerId": user["id"],
                "title": title,
                "description": description,
                "director": director or None,
                "coverImageUrl": cover_image_url,
                "genre": genre,
                "durationMinutes": duration_minutes,
                "releaseYear": release_year,
                "trailerUrl": trailer_url,
                "cast": cast,
                "priceCents": price_cents,
                "totalShares": total_shares,
                "bunnyVideoId": bunny_video_id,
                "bunnyLibraryId": bunny_library_id,
                "status": "active",
                "createdAt": now,
            }
            db["movies"].append(movie)

            for _ in range(total_shares):
                db["shares"].append(
                    {
                        "id": next_id(db, "share", "shr"),
                        "movieId": movie["id"],
                        "ownerId": None,
                        "state": "available",
                        "lastPriceCents": price_cents,
                        "createdAt": now,
                        "updatedAt": now,
                        "consumedAt": None,
                        "reservedByOrderId": None,
                        "reservationExpiresAt": None,
                    }
                )

            producer = sanitize_user(user)
            stats = compute_movie_stats(db, movie["id"])
            return to_public_movie(movie, producer, stats)

        return self.store.transaction(tx)

    def get_payment_config(self):
        return {
            "provider": self.config.payments.provider,
            "currency": self.config.payments.currency,
            "checkoutReservationMinutes": self.config.checkout_reservation_minutes,
        }

    def get_bunny_status(self):
        bunny = self.config.bunny
        library_id = str(bunny.default_library_id or "").strip()
        api_key = str(bunny.api_key or "").strip()
        return {
            "hasLibrary": bool(library_id),
            "canCreate": bool(api_key and library_id),
            "canValidate": bool(api_key and library_id),
            "signedEmbeds": bool(str(bunny.embed_token_key or "").strip()),
            "defaultLibraryId": library_id or None,
            "iframeHost": bunny.iframe_host,
            "playbackSessionSeconds": int(self.config.playback_session_seconds or 120),
        }

    def get_user_payment_orders(self, user_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            orders = [self._public_order(order) for order in db["paymentOrders"] if order["buyerId"] == user_id]
            orders.sort(key=lambda item: parse_date_ms(item.get("createdAt")), reverse=True)
            return orders

        return self.store.transaction(tx)

    def start_primary_checkout(self, user_id, movie_id, payment_gateway):
        def prepare(db):
            self._cleanup_expired_reservations(db)

            buyer = next((item for item in db["users"] if item["id"] == user_id), None)
            if not buyer:
                raise AppError("Usuario comprador nao encontrado.", 404, "USER_NOT_FOUND")

            movie = next((item for item in db["movies"] if item["id"] == movie_id), None)
            if not movie or movie["status"] != "active":
                raise AppError("Filme indisponivel.", 404, "MOVIE_UNAVAILABLE")

            share = next(
                (
                    item
                    for item in db["shares"]
                    if item["movieId"] == movie_id and item["state"] == "available"
                ),
                None,
            )
            if not share:
                raise AppError("Nao ha cotas primarias disponiveis para este filme.", 409, "PRIMARY_SOLD_OUT")

            order = self._create_payment_order(
                db,
                {
                    "type": "primary",
                    "buyerId": buyer["id"],
                    "sellerId": movie["producerId"],
                    "movieId": movie["id"],
                    "shareId": share["id"],
                    "listingId": None,
                    "amountCents": movie["priceCents"],
                    "currency": self.config.payments.currency,
                    "provider": payment_gateway.provider,
                },
            )

            share["state"] = "reserved"
            share["reservedByOrderId"] = order["id"]
            share["reservationExpiresAt"] = order["expiresAt"]
            share["updatedAt"] = now_iso()

            return {
                "order": clone(order),
                "buyer": sanitize_user(buyer),
                "movie": clone(movie),
            }

        prepared = self.store.transaction(prepare)
        try:
            checkout = payment_gateway.create_checkout_session(
                order=prepared["order"],
                description=f"Cota primaria - {prepared['movie']['title']}",
                buyer=prepared["buyer"],
                success_url=self.config.payments.success_url,
                cancel_url=self.config.payments.cancel_url,
            )
        except Exception as error:
            def fail_tx(db):
                order = next((item for item in db["paymentOrders"] if item["id"] == prepared["order"]["id"]), None)
                if order and order["status"] == "pending":
                    self._release_order_reservation(db, order, now_iso())
                    order["status"] = "failed"
                    order["failureReason"] = str(error)
                    order["updatedAt"] = now_iso()
                return None

            self.store.transaction(fail_tx)
            if isinstance(error, AppError):
                raise
            raise AppError(str(error), 500, "CHECKOUT_INIT_FAILED")

        def finalize_tx(db):
            self._cleanup_expired_reservations(db)
            order = next((item for item in db["paymentOrders"] if item["id"] == prepared["order"]["id"]), None)
            if not order:
                raise AppError("Ordem de pagamento nao encontrada.", 404, "ORDER_NOT_FOUND")

            if order["status"] != "pending":
                return {
                    "order": self._public_order(order),
                    "checkout": to_public_checkout(checkout),
                    "purchase": None,
                }

            order["provider"] = checkout.get("provider") or order.get("provider")
            order["providerSessionId"] = checkout.get("sessionId") or order.get("providerSessionId")
            order["providerCheckoutUrl"] = checkout.get("checkoutUrl")
            order["providerPaymentStatus"] = checkout.get("paymentStatus") or "pending"
            order["providerRaw"] = checkout.get("raw")
            order["updatedAt"] = now_iso()

            if not checkout.get("paid"):
                return {
                    "order": self._public_order(order),
                    "checkout": to_public_checkout(checkout),
                    "purchase": None,
                }

            self._assert_paid_amount_matches_order(order, checkout)
            purchase = self._finalize_paid_order(db, order, checkout)
            return {
                "order": self._public_order(order),
                "checkout": to_public_checkout(checkout),
                "purchase": purchase,
            }

        return self.store.transaction(finalize_tx)

    def start_listing_checkout(self, user_id, listing_id, payment_gateway):
        def prepare(db):
            self._cleanup_expired_reservations(db)
            buyer = next((item for item in db["users"] if item["id"] == user_id), None)
            if not buyer:
                raise AppError("Comprador nao encontrado.", 404, "USER_NOT_FOUND")

            listing = next((item for item in db["listings"] if item["id"] == listing_id), None)
            if not listing or listing["status"] != "active":
                raise AppError("Anuncio indisponivel.", 404, "LISTING_UNAVAILABLE")
            if listing["sellerId"] == buyer["id"]:
                raise AppError("Voce nao pode comprar sua propria cota.", 409, "SELF_PURCHASE")

            share = next((item for item in db["shares"] if item["id"] == listing["shareId"]), None)
            if not share:
                raise AppError("Cota do anuncio nao encontrada.", 404, "SHARE_NOT_FOUND")
            if share["state"] != "listed" or share["ownerId"] != listing["sellerId"]:
                raise AppError("A cota nao esta em estado valido para transferencia.", 409, "INVALID_SHARE_STATE")

            movie = next((item for item in db["movies"] if item["id"] == listing["movieId"]), None)
            if not movie or movie["status"] != "active":
                raise AppError("Filme indisponivel.", 409, "MOVIE_UNAVAILABLE")

            order = self._create_payment_order(
                db,
                {
                    "type": "secondary",
                    "buyerId": buyer["id"],
                    "sellerId": listing["sellerId"],
                    "movieId": movie["id"],
                    "shareId": share["id"],
                    "listingId": listing["id"],
                    "amountCents": listing["priceCents"],
                    "currency": self.config.payments.currency,
                    "provider": payment_gateway.provider,
                },
            )

            listing["status"] = "reserved"
            listing["reservedByOrderId"] = order["id"]
            listing["reservationExpiresAt"] = order["expiresAt"]

            return {
                "order": clone(order),
                "buyer": sanitize_user(buyer),
                "movie": clone(movie),
            }

        prepared = self.store.transaction(prepare)

        try:
            checkout = payment_gateway.create_checkout_session(
                order=prepared["order"],
                description=f"Revenda de cota - {prepared['movie']['title']}",
                buyer=prepared["buyer"],
                success_url=self.config.payments.success_url,
                cancel_url=self.config.payments.cancel_url,
            )
        except Exception as error:
            def fail_tx(db):
                order = next((item for item in db["paymentOrders"] if item["id"] == prepared["order"]["id"]), None)
                if order and order["status"] == "pending":
                    self._release_order_reservation(db, order, now_iso())
                    order["status"] = "failed"
                    order["failureReason"] = str(error)
                    order["updatedAt"] = now_iso()
                return None

            self.store.transaction(fail_tx)
            if isinstance(error, AppError):
                raise
            raise AppError(str(error), 500, "CHECKOUT_INIT_FAILED")

        def finalize_tx(db):
            self._cleanup_expired_reservations(db)
            order = next((item for item in db["paymentOrders"] if item["id"] == prepared["order"]["id"]), None)
            if not order:
                raise AppError("Ordem de pagamento nao encontrada.", 404, "ORDER_NOT_FOUND")

            if order["status"] != "pending":
                return {
                    "order": self._public_order(order),
                    "checkout": to_public_checkout(checkout),
                    "purchase": None,
                }

            order["provider"] = checkout.get("provider") or order.get("provider")
            order["providerSessionId"] = checkout.get("sessionId") or order.get("providerSessionId")
            order["providerCheckoutUrl"] = checkout.get("checkoutUrl")
            order["providerPaymentStatus"] = checkout.get("paymentStatus") or "pending"
            order["providerRaw"] = checkout.get("raw")
            order["updatedAt"] = now_iso()

            if not checkout.get("paid"):
                return {
                    "order": self._public_order(order),
                    "checkout": to_public_checkout(checkout),
                    "purchase": None,
                }

            self._assert_paid_amount_matches_order(order, checkout)
            purchase = self._finalize_paid_order(db, order, checkout)
            return {
                "order": self._public_order(order),
                "checkout": to_public_checkout(checkout),
                "purchase": purchase,
            }

        return self.store.transaction(finalize_tx)

    def confirm_payment_order(self, user_id, order_id, session_id, payment_gateway):
        def read_order_tx(db):
            self._cleanup_expired_reservations(db)
            order = next((item for item in db["paymentOrders"] if item["id"] == order_id), None)
            if not order:
                raise AppError("Ordem de pagamento nao encontrada.", 404, "ORDER_NOT_FOUND")
            if order["buyerId"] != user_id:
                raise AppError("Voce nao pode confirmar esta ordem.", 403, "FORBIDDEN")
            return clone(order)

        current_order = self.store.transaction(read_order_tx)
        if current_order["status"] == "paid":
            return {
                "order": self._public_order(current_order),
                "purchase": None,
                "alreadyPaid": True,
            }
        if current_order["status"] != "pending":
            raise AppError("Somente ordens pendentes podem ser confirmadas.", 409, "ORDER_NOT_PENDING")

        provider_session_id = str(session_id or current_order.get("providerSessionId") or "").strip()
        checkout_status = payment_gateway.get_checkout_session_status(
            session_id=provider_session_id,
            expected_order=current_order,
        )

        def confirm_tx(db):
            self._cleanup_expired_reservations(db)
            order = next((item for item in db["paymentOrders"] if item["id"] == order_id), None)
            if not order:
                raise AppError("Ordem de pagamento nao encontrada.", 404, "ORDER_NOT_FOUND")
            if order["buyerId"] != user_id:
                raise AppError("Voce nao pode confirmar esta ordem.", 403, "FORBIDDEN")

            if order["status"] == "paid":
                return {
                    "order": self._public_order(order),
                    "purchase": None,
                    "alreadyPaid": True,
                }
            if order["status"] != "pending":
                raise AppError("Somente ordens pendentes podem ser confirmadas.", 409, "ORDER_NOT_PENDING")

            order["provider"] = checkout_status.get("provider") or order.get("provider")
            order["providerSessionId"] = checkout_status.get("sessionId") or order.get("providerSessionId")
            order["providerPaymentStatus"] = checkout_status.get("paymentStatus") or order.get("providerPaymentStatus")
            order["providerRaw"] = checkout_status.get("raw") or order.get("providerRaw")
            order["updatedAt"] = now_iso()

            if not checkout_status.get("paid"):
                if checkout_status.get("status") == "expired":
                    self._release_order_reservation(db, order, now_iso())
                    order["status"] = "expired"
                    order["failureReason"] = "Checkout expirado sem pagamento."
                    order["updatedAt"] = now_iso()
                return {
                    "order": self._public_order(order),
                    "purchase": None,
                    "alreadyPaid": False,
                }

            self._assert_paid_amount_matches_order(order, checkout_status)
            purchase = self._finalize_paid_order(db, order, checkout_status)
            return {
                "order": self._public_order(order),
                "purchase": purchase,
                "alreadyPaid": False,
            }

        return self.store.transaction(confirm_tx)

    def cancel_payment_order(self, user_id, order_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            order = next((item for item in db["paymentOrders"] if item["id"] == order_id), None)
            if not order:
                raise AppError("Ordem de pagamento nao encontrada.", 404, "ORDER_NOT_FOUND")
            if order["buyerId"] != user_id:
                raise AppError("Voce nao pode cancelar esta ordem.", 403, "FORBIDDEN")
            if order["status"] != "pending":
                raise AppError("Somente ordens pendentes podem ser canceladas.", 409, "ORDER_NOT_PENDING")

            self._release_order_reservation(db, order, now_iso())
            order["status"] = "canceled"
            order["updatedAt"] = now_iso()
            order["failureReason"] = "Cancelado pelo usuario"
            return {"order": self._public_order(order)}

        return self.store.transaction(tx)

    def buy_primary_share(self, user_id, movie_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            buyer = next((item for item in db["users"] if item["id"] == user_id), None)
            if not buyer:
                raise AppError("Usuario comprador nao encontrado.", 404, "USER_NOT_FOUND")

            movie = next((item for item in db["movies"] if item["id"] == movie_id), None)
            if not movie or movie["status"] != "active":
                raise AppError("Filme indisponivel.", 404, "MOVIE_UNAVAILABLE")

            share = next(
                (
                    item
                    for item in db["shares"]
                    if item["movieId"] == movie_id and item["state"] == "available"
                ),
                None,
            )
            if not share:
                raise AppError("Nao ha cotas primarias disponiveis para este filme.", 409, "PRIMARY_SOLD_OUT")

            return self._finalize_primary_purchase(
                db,
                {
                    "buyerId": buyer["id"],
                    "movie": movie,
                    "share": share,
                    "priceCents": movie["priceCents"],
                    "transactionType": "primary_purchase",
                },
            )

        return self.store.transaction(tx)

    def get_user_shares(self, user_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            shares = []
            for share in db["shares"]:
                if share["ownerId"] != user_id:
                    continue
                movie = next((item for item in db["movies"] if item["id"] == share["movieId"]), None)
                tokens = [item for item in db["accessTokens"] if item.get("shareId") == share["id"]]
                tokens.sort(key=lambda item: parse_date_ms(item.get("issuedAt")), reverse=True)
                latest_token = tokens[0] if tokens else None
                live_token = next(
                    (item for item in tokens if item.get("status") in {"active", "redeeming"}),
                    None,
                )
                listing = next(
                    (
                        item
                        for item in db["listings"]
                        if item["shareId"] == share["id"] and item["status"] in {"active", "reserved"}
                    ),
                    None,
                )
                pending_playback = None
                if live_token and live_token.get("status") == "redeeming":
                    session = next(
                        (
                            item
                            for item in db["playbackSessions"]
                            if item.get("accessTokenId") == live_token["id"] and item.get("status") == "active"
                        ),
                        None,
                    )
                    if session:
                        pending_playback = {
                            "watchToken": session["token"],
                            "watchPath": f"/watch/{session['token']}",
                            "watchUrl": f"/watch/{session['token']}",
                            "expiresAt": session.get("expiresAt"),
                            "remainingSeconds": remaining_seconds(session.get("expiresAt")),
                        }
                token_for_state = live_token or latest_token
                token_state = describe_token_state(share, token_for_state, listing, pending_playback, movie)
                shares.append(
                    {
                        **clone(share),
                        "movie": compact_movie_for_listing(movie) if movie else None,
                        "tokenState": token_state,
                        "accessToken": public_access_token(token_for_state),
                        "activeToken": public_access_token(live_token) if live_token else None,
                        "pendingPlayback": pending_playback,
                        "activeListing": (
                            {
                                "id": listing["id"],
                                "status": listing["status"],
                                "priceCents": listing["priceCents"],
                                "price": listing["priceCents"] / 100,
                                "createdAt": listing["createdAt"],
                                "reservationExpiresAt": listing.get("reservationExpiresAt"),
                            }
                            if listing
                            else None
                        ),
                    }
                )

            shares.sort(key=lambda item: parse_date_ms(item.get("updatedAt")), reverse=True)
            return shares

        return self.store.transaction(tx)

    def get_user_transactions(self, user_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            items = []
            for txn in db["transactions"]:
                if txn.get("buyerId") != user_id and txn.get("sellerId") != user_id:
                    continue
                movie = next((item for item in db["movies"] if item["id"] == txn.get("movieId")), None)
                items.append(
                    {
                        **clone(txn),
                        "movieTitle": (movie or {}).get("title") or txn.get("movieTitle") or "Filme",
                        "price": (txn.get("priceCents") or 0) / 100,
                    }
                )
            items.sort(key=lambda item: parse_date_ms(item.get("createdAt")), reverse=True)
            return items

        return self.store.transaction(tx)

    def list_market(self, movie_id=None):
        def tx(db):
            self._cleanup_expired_reservations(db)
            items = []
            for listing in db["listings"]:
                if listing.get("status") != "active":
                    continue
                if movie_id and listing.get("movieId") != movie_id:
                    continue
                items.append(self._to_public_listing(db, listing))
            items.sort(key=lambda item: parse_date_ms(item.get("createdAt")), reverse=True)
            return items

        return self.store.transaction(tx)

    def create_listing(self, user_id, share_id, price_cents):
        price = ensure_positive_int(price_cents, "priceCents")

        def tx(db):
            self._cleanup_expired_reservations(db)
            share = next((item for item in db["shares"] if item["id"] == share_id), None)
            if not share or share.get("ownerId") != user_id:
                raise AppError("Cota nao encontrada.", 404, "SHARE_NOT_FOUND")
            if share.get("state") != "owned":
                raise AppError("Somente cotas ativas podem ser anunciadas.", 409, "INVALID_SHARE_STATE")
            live_token = next(
                (
                    item
                    for item in db["accessTokens"]
                    if item.get("shareId") == share_id and item.get("status") == "redeeming"
                ),
                None,
            )
            if live_token:
                raise AppError(
                    "Ha uma sessao de player em andamento. Feche o player ou aguarde expirar para anunciar.",
                    409,
                    "PLAYBACK_IN_PROGRESS",
                )

            existing = next(
                (
                    item
                    for item in db["listings"]
                    if item.get("shareId") == share_id and item.get("status") in {"active", "reserved"}
                ),
                None,
            )
            if existing:
                raise AppError("Esta cota ja possui um anuncio ativo.", 409, "LISTING_EXISTS")

            now = now_iso()
            listing = {
                "id": next_id(db, "listing", "lst"),
                "shareId": share["id"],
                "movieId": share["movieId"],
                "sellerId": user_id,
                "priceCents": price,
                "status": "active",
                "createdAt": now,
                "reservedByOrderId": None,
                "reservationExpiresAt": None,
            }
            db["listings"].append(listing)
            share["state"] = "listed"
            share["updatedAt"] = now
            return clone(listing)

        return self.store.transaction(tx)

    def cancel_listing(self, user_id, listing_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            listing = next((item for item in db["listings"] if item["id"] == listing_id), None)
            if not listing:
                raise AppError("Anuncio nao encontrado.", 404, "LISTING_NOT_FOUND")
            if listing.get("sellerId") != user_id:
                raise AppError("Voce nao pode cancelar este anuncio.", 403, "FORBIDDEN")
            if listing.get("status") != "active":
                raise AppError("Somente anuncios ativos podem ser cancelados.", 409, "LISTING_NOT_ACTIVE")

            now = now_iso()
            listing["status"] = "canceled"
            listing["updatedAt"] = now
            share = next((item for item in db["shares"] if item["id"] == listing.get("shareId")), None)
            if share and share.get("ownerId") == user_id and share.get("state") == "listed":
                share["state"] = "owned"
                share["updatedAt"] = now
            return clone(listing)

        return self.store.transaction(tx)

    def buy_listing(self, user_id, listing_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            buyer = next((item for item in db["users"] if item["id"] == user_id), None)
            if not buyer:
                raise AppError("Comprador nao encontrado.", 404, "USER_NOT_FOUND")

            listing = next((item for item in db["listings"] if item["id"] == listing_id), None)
            if not listing or listing.get("status") != "active":
                raise AppError("Anuncio indisponivel.", 404, "LISTING_UNAVAILABLE")
            if listing.get("sellerId") == buyer["id"]:
                raise AppError("Voce nao pode comprar sua propria cota.", 409, "SELF_PURCHASE")

            share = next((item for item in db["shares"] if item["id"] == listing.get("shareId")), None)
            movie = next((item for item in db["movies"] if item["id"] == listing.get("movieId")), None)
            if not share or not movie:
                raise AppError("Cota do anuncio nao encontrada.", 404, "SHARE_NOT_FOUND")

            return self._transfer_listed_share(
                db,
                {
                    "buyerId": buyer["id"],
                    "sellerId": listing["sellerId"],
                    "share": share,
                    "listing": listing,
                    "movie": movie,
                    "priceCents": listing["priceCents"],
                    "transactionType": "secondary_purchase",
                },
            )

        return self.store.transaction(tx)

    def consume_access_token(self, user_id, token_value, bunny_lookup=None):
        token_value = str(token_value or "").strip()
        if not token_value:
            raise AppError("Token de acesso e obrigatorio.", 400, "VALIDATION_ERROR")

        def tx(db):
            self._cleanup_expired_reservations(db)
            access_token = next((item for item in db["accessTokens"] if item.get("token") == token_value), None)
            if not access_token:
                raise AppError("Token invalido ou expirado.", 404, "TOKEN_NOT_FOUND")
            if access_token.get("status") == "redeeming":
                raise AppError("Ja existe uma sessao de player em andamento.", 409, "PLAYBACK_IN_PROGRESS")
            if access_token.get("status") != "active":
                raise AppError("Este token ja foi utilizado ou revogado.", 409, "TOKEN_NOT_ACTIVE")

            share = next((item for item in db["shares"] if item["id"] == access_token.get("shareId")), None)
            if not share:
                raise AppError("Cota do token nao encontrada.", 404, "SHARE_NOT_FOUND")
            if share.get("ownerId") != user_id:
                raise AppError("Este token nao pertence a voce.", 403, "FORBIDDEN")
            if share.get("state") != "owned":
                raise AppError("A cota nao esta disponivel para visualizacao.", 409, "INVALID_SHARE_STATE")

            movie = next((item for item in db["movies"] if item["id"] == share.get("movieId")), None)
            if not movie:
                raise AppError("Filme nao encontrado.", 404, "MOVIE_NOT_FOUND")
            self._assert_movie_has_bunny(movie)
            if bunny_lookup:
                bunny_lookup(movie.get("bunnyLibraryId"), movie.get("bunnyVideoId"))

            now = now_iso()
            watch_token = random_token("watch")
            client_secret = random_token("pbk")
            playback = {
                "id": next_id(db, "playbackSession", "pbk"),
                "token": watch_token,
                "clientSecret": client_secret,
                "shareId": share["id"],
                "userId": user_id,
                "accessTokenId": access_token["id"],
                "status": "active",
                "createdAt": now,
                "consumedAt": None,
                "expiresAt": iso_after(seconds=int(self.config.playback_session_seconds or 120)),
                "ipAddress": None,
                "userAgent": None,
            }
            db["playbackSessions"].append(playback)

            access_token["status"] = "redeeming"
            access_token["usedAt"] = None
            share["updatedAt"] = now

            return {
                "share": clone(share),
                "movie": compact_movie_for_listing(movie),
                "tokenState": describe_token_state(share, access_token, None, {
                    "watchUrl": f"/watch/{watch_token}",
                }, movie),
                "playback": {
                    "watchToken": watch_token,
                    "watchPath": f"/watch/{watch_token}",
                    "watchUrl": f"/watch/{watch_token}",
                    "clientSecret": client_secret,
                    "expiresAt": playback["expiresAt"],
                },
            }

        return self.store.transaction(tx)

    def resume_playback(self, user_id, token_value="", share_id=""):
        token_value = str(token_value or "").strip()
        share_id = str(share_id or "").strip()

        def tx(db):
            self._cleanup_expired_reservations(db)
            access_token = None
            if token_value:
                access_token = next((item for item in db["accessTokens"] if item.get("token") == token_value), None)
            elif share_id:
                access_token = next(
                    (
                        item
                        for item in db["accessTokens"]
                        if item.get("shareId") == share_id and item.get("status") == "redeeming"
                    ),
                    None,
                )
            if not access_token or access_token.get("status") != "redeeming":
                raise AppError("Nao ha sessao de player para retomar.", 404, "PLAYBACK_NOT_FOUND")

            share = next((item for item in db["shares"] if item["id"] == access_token.get("shareId")), None)
            if not share or share.get("ownerId") != user_id:
                raise AppError("Esta sessao nao pertence a voce.", 403, "FORBIDDEN")

            session = next(
                (
                    item
                    for item in db["playbackSessions"]
                    if item.get("accessTokenId") == access_token["id"] and item.get("status") == "active"
                ),
                None,
            )
            if not session:
                self._restore_playback_token(db, None, access_token, share, now_iso())
                raise AppError("Sessao de player expirada. Seu token continua ativo.", 410, "PLAYBACK_EXPIRED")
            if parse_date_ms(session.get("expiresAt")) <= utc_now_ms():
                self._restore_playback_token(db, session, access_token, share, now_iso())
                raise AppError("Sessao de player expirada. Seu token continua ativo.", 410, "PLAYBACK_EXPIRED")

            movie = next((item for item in db["movies"] if item["id"] == share.get("movieId")), None)
            return {
                "share": clone(share),
                "movie": compact_movie_for_listing(movie) if movie else None,
                "tokenState": describe_token_state(share, access_token, None, {
                    "watchUrl": f"/watch/{session['token']}",
                }, movie),
                "playback": {
                    "watchToken": session["token"],
                    "watchPath": f"/watch/{session['token']}",
                    "watchUrl": f"/watch/{session['token']}",
                    "clientSecret": session.get("clientSecret"),
                    "expiresAt": session.get("expiresAt"),
                },
            }

        return self.store.transaction(tx)

    def open_playback_session(self, playback_token, client_info, embed_builder, bunny_lookup=None):
        playback_token = str(playback_token or "").strip()
        client_info = client_info or {}

        def tx(db):
            self._cleanup_expired_reservations(db)
            session = next((item for item in db["playbackSessions"] if item.get("token") == playback_token), None)
            if not session:
                raise AppError("Link de reproducao invalido.", 404, "PLAYBACK_NOT_FOUND")

            share = next((item for item in db["shares"] if item["id"] == session.get("shareId")), None)
            movie = next((item for item in db["movies"] if item["id"] == (share or {}).get("movieId")), None)
            access_token = next(
                (item for item in db["accessTokens"] if item["id"] == session.get("accessTokenId")),
                None,
            )

            expired = session.get("status") == "expired" or parse_date_ms(session.get("expiresAt")) <= utc_now_ms()
            if session.get("status") != "used" and expired:
                self._restore_playback_token(db, session, access_token, share, now_iso())
                raise AppError("Link de reproducao expirado. Seu token continua ativo.", 410, "PLAYBACK_EXPIRED")
            if session.get("status") != "active":
                raise AppError("Esta visualizacao ja foi utilizada.", 409, "PLAYBACK_USED")
            if session.get("clientSecret") != str(client_info.get("clientSecret") or ""):
                raise AppError(
                    "Sessao de reproducao invalida neste navegador. Volte em Minhas cotas e continue pelo mesmo aparelho.",
                    403,
                    "PLAYBACK_FORBIDDEN",
                )
            if not share or not movie:
                self._restore_playback_token(db, session, access_token, share, now_iso())
                raise AppError("Filme nao encontrado para reproducao. Seu token nao foi gasto.", 404, "MOVIE_NOT_FOUND")

            lookup_error = None
            try:
                self._assert_movie_has_bunny(movie)
                if bunny_lookup:
                    bunny_lookup(movie.get("bunnyLibraryId"), movie.get("bunnyVideoId"))
            except Exception as error:
                lookup_error = error

            embed = None
            embed_error = lookup_error
            if not embed_error:
                try:
                    embed = embed_builder(
                        {
                            "libraryId": movie.get("bunnyLibraryId"),
                            "videoId": movie.get("bunnyVideoId"),
                            "sessionTag": session["id"],
                        }
                    )
                except Exception as error:
                    embed_error = error

            if embed_error or not (embed or {}).get("embedUrl"):
                self._restore_playback_token(db, session, access_token, share, now_iso())
                message = "Player Bunny indisponivel para este filme. Seu token nao foi gasto."
                if isinstance(embed_error, AppError):
                    extra = "" if "token" in str(embed_error.message).lower() else " Seu token nao foi gasto."
                    return {
                        "_playbackError": AppError(
                            f"{embed_error.message}{extra}".strip(),
                            embed_error.status,
                            embed_error.code,
                        )
                    }
                return {"_playbackError": AppError(message, 502, "BUNNY_EMBED_FAILED")}

            now = now_iso()
            session["status"] = "used"
            session["consumedAt"] = now
            session["ipAddress"] = client_info.get("ipAddress")
            session["userAgent"] = client_info.get("userAgent")

            if access_token:
                access_token["status"] = "used"
                access_token["usedAt"] = now
            share["state"] = "consumed"
            share["consumedAt"] = now
            share["updatedAt"] = now

            return {
                "movie": compact_movie_for_listing(movie),
                "tokenState": describe_token_state(share, access_token, None, None, movie),
                "playback": {
                    **(embed or {}),
                    "watchToken": session["token"],
                },
            }

        result = self.store.transaction(tx)
        error = result.get("_playbackError") if isinstance(result, dict) else None
        if error:
            raise error
        return result

    def confirm_order_payment(self, correlation_id):
        correlation_id = str(correlation_id or "").strip()
        if not correlation_id:
            raise AppError("correlationID ausente.", 400, "VALIDATION_ERROR")

        def tx(db):
            self._cleanup_expired_reservations(db)
            order = next(
                (
                    item
                    for item in db["paymentOrders"]
                    if item.get("id") == correlation_id or item.get("providerSessionId") == correlation_id
                ),
                None,
            )
            if not order:
                raise AppError("Ordem de pagamento nao encontrada.", 404, "ORDER_NOT_FOUND")
            if order.get("status") == "paid":
                return {"alreadyPaid": True, "order": self._public_order(order), "purchase": None}
            if order.get("status") != "pending":
                raise AppError("Somente ordens pendentes podem ser confirmadas.", 409, "ORDER_NOT_PENDING")

            checkout = {
                "provider": order.get("provider"),
                "sessionId": order.get("providerSessionId") or order.get("id"),
                "paid": True,
                "amountCents": order.get("amountCents"),
                "currency": order.get("currency"),
                "paymentStatus": "paid",
                "status": "complete",
            }
            purchase = self._finalize_paid_order(db, order, checkout)
            return {"alreadyPaid": False, "order": self._public_order(order), "purchase": purchase}

        return self.store.transaction(tx)

    def _listings_for_movie(self, db, movie_id):
        return [
            self._to_public_listing(db, listing)
            for listing in db["listings"]
            if listing.get("movieId") == movie_id and listing.get("status") == "active"
        ]

    def _to_public_listing(self, db, listing):
        seller = next((item for item in db["users"] if item["id"] == listing.get("sellerId")), None)
        movie = next((item for item in db["movies"] if item["id"] == listing.get("movieId")), None)
        return {
            **clone(listing),
            "price": (listing.get("priceCents") or 0) / 100,
            "seller": sanitize_user(seller) if seller else None,
            "movie": compact_movie_for_listing(movie) if movie else None,
        }

    def _create_session(self, db, user_id, now):
        session = {
            "id": next_id(db, "session", "ses"),
            "token": random_token("ses"),
            "userId": user_id,
            "createdAt": now,
            "expiresAt": iso_after(days=int(self.config.session_duration_days or 30)),
        }
        db["sessions"].append(session)
        return session

    def _create_payment_order(self, db, payload):
        now = now_iso()
        order = {
            "id": next_id(db, "paymentOrder", "ord"),
            "type": payload["type"],
            "buyerId": payload["buyerId"],
            "sellerId": payload["sellerId"],
            "movieId": payload["movieId"],
            "shareId": payload["shareId"],
            "listingId": payload.get("listingId"),
            "amountCents": payload["amountCents"],
            "currency": payload["currency"],
            "provider": payload.get("provider"),
            "status": "pending",
            "providerSessionId": None,
            "providerCheckoutUrl": None,
            "providerPaymentStatus": "pending",
            "providerRaw": None,
            "failureReason": None,
            "createdAt": now,
            "updatedAt": now,
            "paidAt": None,
            "expiresAt": iso_after(minutes=int(self.config.checkout_reservation_minutes or 15)),
        }
        db["paymentOrders"].append(order)
        return order

    def _public_order(self, order):
        return {
            "id": order["id"],
            "type": order.get("type"),
            "status": order.get("status"),
            "amountCents": order.get("amountCents"),
            "amount": (order.get("amountCents") or 0) / 100,
            "currency": order.get("currency"),
            "movieId": order.get("movieId"),
            "shareId": order.get("shareId"),
            "listingId": order.get("listingId"),
            "buyerId": order.get("buyerId"),
            "sellerId": order.get("sellerId"),
            "provider": order.get("provider"),
            "providerSessionId": order.get("providerSessionId"),
            "providerPaymentStatus": order.get("providerPaymentStatus"),
            "expiresAt": order.get("expiresAt"),
            "createdAt": order.get("createdAt"),
            "updatedAt": order.get("updatedAt"),
            "paidAt": order.get("paidAt"),
            "failureReason": order.get("failureReason"),
        }

    def _assert_paid_amount_matches_order(self, order, checkout):
        paid_amount = checkout.get("amountCents")
        if paid_amount is not None and int(paid_amount) != int(order.get("amountCents") or 0):
            raise AppError("Valor pago diverge da ordem.", 409, "AMOUNT_MISMATCH")
        currency = checkout.get("currency")
        if currency and str(currency).upper() != str(order.get("currency") or "").upper():
            raise AppError("Moeda paga diverge da ordem.", 409, "CURRENCY_MISMATCH")

    def _cleanup_expired_reservations(self, db):
        now = now_iso()
        now_ms = utc_now_ms()
        for order in db["paymentOrders"]:
            if order.get("status") != "pending":
                continue
            if parse_date_ms(order.get("expiresAt")) > now_ms:
                continue
            self._release_order_reservation(db, order, now)
            order["status"] = "expired"
            order["failureReason"] = "Checkout expirado sem pagamento."
            order["updatedAt"] = now

        for session in db["playbackSessions"]:
            if session.get("status") != "active":
                continue
            if parse_date_ms(session.get("expiresAt")) > now_ms:
                continue
            access_token = next(
                (item for item in db["accessTokens"] if item.get("id") == session.get("accessTokenId")),
                None,
            )
            share = next((item for item in db["shares"] if item.get("id") == session.get("shareId")), None)
            self._restore_playback_token(db, session, access_token, share, now)

        self._recover_stuck_playback_tokens(db, now)

    def _recover_stuck_playback_tokens(self, db, now):
        for token in db["accessTokens"]:
            if token.get("status") != "redeeming":
                continue
            session = next(
                (
                    item
                    for item in db["playbackSessions"]
                    if item.get("accessTokenId") == token.get("id") and item.get("status") == "active"
                ),
                None,
            )
            if session and parse_date_ms(session.get("expiresAt")) > utc_now_ms():
                continue
            share = next((item for item in db["shares"] if item.get("id") == token.get("shareId")), None)
            self._restore_playback_token(db, session, token, share, now)

    def _assert_movie_has_bunny(self, movie):
        if not (movie or {}).get("bunnyVideoId") or not (movie or {}).get("bunnyLibraryId"):
            raise AppError(
                "Este filme ainda nao tem player Bunny. Seu token nao foi gasto.",
                409,
                "BUNNY_NOT_READY",
            )

    def _restore_playback_token(self, db, session, access_token, share, now):
        if session:
            session["status"] = "expired"
            session["consumedAt"] = session.get("consumedAt") or now
        if access_token and access_token.get("status") == "redeeming":
            access_token["status"] = "active"
            access_token["usedAt"] = None
            if share:
                share["updatedAt"] = now
        if share and share.get("state") == "consumed" and not share.get("consumedAt"):
            share["state"] = "owned"
            share["updatedAt"] = now

    def _release_order_reservation(self, db, order, now):
        share = next((item for item in db["shares"] if item["id"] == order.get("shareId")), None)
        if share and share.get("reservedByOrderId") == order.get("id"):
            share["state"] = "available"
            share["ownerId"] = None
            share["reservedByOrderId"] = None
            share["reservationExpiresAt"] = None
            share["updatedAt"] = now

        listing = next((item for item in db["listings"] if item["id"] == order.get("listingId")), None)
        if listing and listing.get("reservedByOrderId") == order.get("id"):
            listing["status"] = "active"
            listing["reservedByOrderId"] = None
            listing["reservationExpiresAt"] = None
            if share and share.get("ownerId") == listing.get("sellerId"):
                share["state"] = "listed"
                share["reservedByOrderId"] = None
                share["reservationExpiresAt"] = None
                share["updatedAt"] = now

    def _issue_access_token(self, db, share, owner_id, reason, now):
        token = {
            "id": next_id(db, "token", "tok"),
            "token": random_token("tok"),
            "shareId": share["id"],
            "ownerId": owner_id,
            "status": "active",
            "reason": reason,
            "issuedAt": now,
            "usedAt": None,
            "revokedAt": None,
        }
        db["accessTokens"].append(token)
        return token

    def _revoke_share_tokens(self, db, share_id, now):
        for token in db["accessTokens"]:
            if token.get("shareId") == share_id and token.get("status") == "active":
                token["status"] = "revoked"
                token["revokedAt"] = now

    def _record_transaction(self, db, payload, now):
        movie = payload.get("movie") or {}
        txn = {
            "id": next_id(db, "transaction", "txn"),
            "type": payload["transactionType"],
            "movieId": movie.get("id") or payload.get("movieId"),
            "movieTitle": movie.get("title") or "",
            "shareId": payload["share"]["id"],
            "buyerId": payload["buyerId"],
            "sellerId": payload.get("sellerId") or movie.get("producerId"),
            "priceCents": payload["priceCents"],
            "createdAt": now,
        }
        db["transactions"].append(txn)
        return txn

    def _finalize_primary_purchase(self, db, payload):
        now = now_iso()
        share = payload["share"]
        movie = payload["movie"]
        buyer_id = payload["buyerId"]

        share["ownerId"] = buyer_id
        share["state"] = "owned"
        share["lastPriceCents"] = payload["priceCents"]
        share["reservedByOrderId"] = None
        share["reservationExpiresAt"] = None
        share["updatedAt"] = now

        token = self._issue_access_token(db, share, buyer_id, payload.get("transactionType") or "primary_purchase", now)
        transaction = self._record_transaction(db, payload, now)
        return {
            "share": clone(share),
            "token": clone(token),
            "transaction": clone(transaction),
            "movie": compact_movie_for_listing(movie),
        }

    def _transfer_listed_share(self, db, payload):
        now = now_iso()
        share = payload["share"]
        listing = payload["listing"]
        movie = payload["movie"]
        buyer_id = payload["buyerId"]

        self._revoke_share_tokens(db, share["id"], now)

        listing["status"] = "sold"
        listing["updatedAt"] = now
        listing["reservedByOrderId"] = None
        listing["reservationExpiresAt"] = None

        share["ownerId"] = buyer_id
        share["state"] = "owned"
        share["lastPriceCents"] = payload["priceCents"]
        share["reservedByOrderId"] = None
        share["reservationExpiresAt"] = None
        share["updatedAt"] = now

        token = self._issue_access_token(db, share, buyer_id, "resale", now)
        transaction = self._record_transaction(db, payload, now)
        return {
            "share": clone(share),
            "token": clone(token),
            "transaction": clone(transaction),
            "movie": compact_movie_for_listing(movie),
        }

    def _finalize_paid_order(self, db, order, checkout):
        if order.get("status") == "paid":
            return None

        if order.get("type") == "primary":
            share = next((item for item in db["shares"] if item["id"] == order.get("shareId")), None)
            movie = next((item for item in db["movies"] if item["id"] == order.get("movieId")), None)
            if not share or not movie:
                raise AppError("Cota da ordem nao encontrada.", 404, "SHARE_NOT_FOUND")
            purchase = self._finalize_primary_purchase(
                db,
                {
                    "buyerId": order["buyerId"],
                    "sellerId": order.get("sellerId") or movie.get("producerId"),
                    "movie": movie,
                    "share": share,
                    "priceCents": order["amountCents"],
                    "transactionType": "primary_purchase",
                },
            )
        elif order.get("type") == "secondary":
            listing = next((item for item in db["listings"] if item["id"] == order.get("listingId")), None)
            share = next((item for item in db["shares"] if item["id"] == order.get("shareId")), None)
            movie = next((item for item in db["movies"] if item["id"] == order.get("movieId")), None)
            if not listing or not share or not movie:
                raise AppError("Anuncio da ordem nao encontrado.", 404, "LISTING_NOT_FOUND")
            purchase = self._transfer_listed_share(
                db,
                {
                    "buyerId": order["buyerId"],
                    "sellerId": order.get("sellerId") or listing.get("sellerId"),
                    "share": share,
                    "listing": listing,
                    "movie": movie,
                    "priceCents": order["amountCents"],
                    "transactionType": "secondary_purchase",
                },
            )
        else:
            raise AppError("Tipo de ordem invalido.", 400, "INVALID_ORDER_TYPE")

        now = now_iso()
        order["status"] = "paid"
        order["paidAt"] = now
        order["updatedAt"] = now
        order["providerPaymentStatus"] = checkout.get("paymentStatus") or "paid"
        order["failureReason"] = None
        return purchase

