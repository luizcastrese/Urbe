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
                    "checkout": {
                        "provider": checkout.get("provider"),
                        "sessionId": checkout.get("sessionId"),
                        "checkoutUrl": checkout.get("checkoutUrl"),
                        "paymentStatus": checkout.get("paymentStatus"),
                        "status": checkout.get("status"),
                        "paid": checkout.get("paid") is True,
                    },
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
                    "checkout": {
                        "provider": checkout.get("provider"),
                        "sessionId": checkout.get("sessionId"),
                        "checkoutUrl": checkout.get("checkoutUrl"),
                        "paymentStatus": checkout.get("paymentStatus"),
                        "status": checkout.get("status"),
                        "paid": False,
                    },
                    "purchase": None,
                }

            self._assert_paid_amount_matches_order(order, checkout)
            purchase = self._finalize_paid_order(db, order, checkout)
            return {
                "order": self._public_order(order),
                "checkout": {
                    "provider": checkout.get("provider"),
                    "sessionId": checkout.get("sessionId"),
                    "checkoutUrl": checkout.get("checkoutUrl"),
                    "paymentStatus": checkout.get("paymentStatus"),
                    "status": checkout.get("status"),
                    "paid": True,
                },
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
                    "checkout": {
                        "provider": checkout.get("provider"),
                        "sessionId": checkout.get("sessionId"),
                        "checkoutUrl": checkout.get("checkoutUrl"),
                        "paymentStatus": checkout.get("paymentStatus"),
                        "status": checkout.get("status"),
                        "paid": checkout.get("paid") is True,
                    },
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
                    "checkout": {
                        "provider": checkout.get("provider"),
                        "sessionId": checkout.get("sessionId"),
                        "checkoutUrl": checkout.get("checkoutUrl"),
                        "paymentStatus": checkout.get("paymentStatus"),
                        "status": checkout.get("status"),
                        "paid": False,
                    },
                    "purchase": None,
                }

            self._assert_paid_amount_matches_order(order, checkout)
            purchase = self._finalize_paid_order(db, order, checkout)
            return {
                "order": self._public_order(order),
                "checkout": {
                    "provider": checkout.get("provider"),
                    "sessionId": checkout.get("sessionId"),
                    "checkoutUrl": checkout.get("checkoutUrl"),
                    "paymentStatus": checkout.get("paymentStatus"),
                    "status": checkout.get("status"),
                    "paid": True,
                },
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
                active_token = next(
                    (
                        token
                        for token in db["accessTokens"]
                        if token["shareId"] == share["id"] and token["status"] == "active"
                    ),
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
                shares.append(
                    {
                        **clone(share),
                        "movie": compact_movie_for_listing(movie) if movie else None,
                        "activeToken": (
                            {
                                "id": active_token["id"],
                                "token": active_token["token"],
                                "issuedAt": active_token["issuedAt"],
                                "reason": active_token["reason"],
                            }
                            if active_token
                            else None
                        ),
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
