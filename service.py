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

    def list_market(self, movie_id=None):
        def tx(db):
            self._cleanup_expired_reservations(db)
            listings = []
            for listing in db["listings"]:
                if listing["status"] != "active":
                    continue
                if movie_id and listing["movieId"] != movie_id:
                    continue
                movie = next((item for item in db["movies"] if item["id"] == listing["movieId"]), None)
                seller = next((item for item in db["users"] if item["id"] == listing["sellerId"]), None)
                listings.append(
                    {
                        **clone(listing),
                        "price": listing["priceCents"] / 100,
                        "movie": compact_movie_for_listing(movie) if movie else None,
                        "seller": sanitize_user(seller) if seller else None,
                    }
                )
            listings.sort(key=lambda item: parse_date_ms(item.get("createdAt")), reverse=True)
            return listings

        return self.store.transaction(tx)

    def create_listing(self, user_id, share_id, price_cents_value):
        price_cents = ensure_positive_int(price_cents_value, "priceCents")

        def tx(db):
            self._cleanup_expired_reservations(db)
            share = next((item for item in db["shares"] if item["id"] == share_id), None)
            if not share:
                raise AppError("Cota nao encontrada.", 404, "SHARE_NOT_FOUND")
            if share["ownerId"] != user_id:
                raise AppError("Voce nao e dono desta cota.", 403, "FORBIDDEN")
            if share["state"] != "owned":
                raise AppError("Somente cotas ativas podem ser anunciadas.", 409, "INVALID_SHARE_STATE")

            movie = next((item for item in db["movies"] if item["id"] == share["movieId"]), None)
            if not movie or movie["status"] != "active":
                raise AppError("Filme indisponivel para revenda.", 409, "MOVIE_UNAVAILABLE")

            existing = next(
                (
                    listing
                    for listing in db["listings"]
                    if listing["shareId"] == share["id"] and listing["status"] in {"active", "reserved"}
                ),
                None,
            )
            if existing:
                raise AppError("Esta cota ja esta anunciada.", 409, "LISTING_ALREADY_ACTIVE")

            active_token = next(
                (
                    token
                    for token in db["accessTokens"]
                    if token["shareId"] == share["id"] and token["status"] == "active"
                ),
                None,
            )
            if not active_token:
                raise AppError(
                    "Nao existe token ativo para esta cota. Nao e possivel anunciar sem token valido.",
                    409,
                    "MISSING_ACTIVE_TOKEN",
                )

            now = now_iso()
            share["state"] = "listed"
            share["updatedAt"] = now

            listing = {
                "id": next_id(db, "listing", "lst"),
                "movieId": movie["id"],
                "shareId": share["id"],
                "sellerId": user_id,
                "buyerId": None,
                "priceCents": price_cents,
                "status": "active",
                "createdAt": now,
                "soldAt": None,
                "canceledAt": None,
                "reservedByOrderId": None,
                "reservationExpiresAt": None,
            }
            db["listings"].append(listing)
            return clone(listing)

        return self.store.transaction(tx)

    def cancel_listing(self, user_id, listing_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            listing = next((item for item in db["listings"] if item["id"] == listing_id), None)
            if not listing:
                raise AppError("Anuncio nao encontrado.", 404, "LISTING_NOT_FOUND")
            if listing["sellerId"] != user_id:
                raise AppError("Somente o vendedor pode cancelar o anuncio.", 403, "FORBIDDEN")
            if listing["status"] != "active":
                raise AppError("Anuncio nao esta ativo.", 409, "LISTING_NOT_ACTIVE")

            share = next((item for item in db["shares"] if item["id"] == listing["shareId"]), None)
            if not share:
                raise AppError("Cota vinculada ao anuncio nao existe.", 404, "SHARE_NOT_FOUND")

            now = now_iso()
            listing["status"] = "canceled"
            listing["canceledAt"] = now
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
            if not listing or listing["status"] != "active":
                raise AppError("Anuncio indisponivel.", 404, "LISTING_UNAVAILABLE")
            if listing["sellerId"] == user_id:
                raise AppError("Voce nao pode comprar sua propria cota.", 409, "SELF_PURCHASE")

            share = next((item for item in db["shares"] if item["id"] == listing["shareId"]), None)
            if not share:
                raise AppError("Cota do anuncio nao encontrada.", 404, "SHARE_NOT_FOUND")
            if share["state"] != "listed" or share["ownerId"] != listing["sellerId"]:
                raise AppError("A cota nao esta em estado valido para transferencia.", 409, "INVALID_SHARE_STATE")

            movie = next((item for item in db["movies"] if item["id"] == listing["movieId"]), None)
            if not movie or movie["status"] != "active":
                raise AppError("Filme indisponivel.", 409, "MOVIE_UNAVAILABLE")

            return self._finalize_secondary_purchase(
                db,
                {
                    "buyerId": buyer["id"],
                    "listing": listing,
                    "share": share,
                    "movie": movie,
                    "priceCents": listing["priceCents"],
                    "transactionType": "secondary_purchase",
                },
            )

        return self.store.transaction(tx)

    def consume_access_token(self, user_id, token_value):
        if not token_value:
            raise AppError("Token e obrigatorio.", 400, "VALIDATION_ERROR")

        def tx(db):
            self._cleanup_expired_reservations(db)
            token = next((item for item in db["accessTokens"] if item["token"] == token_value), None)
            if not token:
                raise AppError("Token nao encontrado.", 404, "TOKEN_NOT_FOUND")
            if token["ownerId"] != user_id:
                raise AppError("Token nao pertence ao usuario autenticado.", 403, "FORBIDDEN")
            if token["status"] != "active":
                raise AppError("Token invalido ou ja consumido.", 409, "TOKEN_INVALID")

            share = next((item for item in db["shares"] if item["id"] == token["shareId"]), None)
            if not share:
                raise AppError("Cota associada ao token nao existe.", 404, "SHARE_NOT_FOUND")
            if share["state"] != "owned":
                raise AppError(
                    "A cota nao esta em estado valido para consumo (pode estar anunciada ou ja consumida).",
                    409,
                    "INVALID_SHARE_STATE",
                )

            movie = next((item for item in db["movies"] if item["id"] == token["movieId"]), None)
            if not movie:
                raise AppError("Filme associado ao token nao encontrado.", 404, "MOVIE_NOT_FOUND")

            now = now_iso()
            for session in db["playbackSessions"]:
                if session["accessTokenId"] == token["id"] and session["status"] == "active":
                    session["status"] = "invalidated"
                    session["invalidatedAt"] = now

            playback_session = {
                "id": next_id(db, "playbackSession", "pbs"),
                "playbackToken": random_token("watch"),
                "clientSecret": random_token("playck"),
                "ownerId": user_id,
                "movieId": movie["id"],
                "shareId": share["id"],
                "accessTokenId": token["id"],
                "status": "active",
                "createdAt": now,
                "expiresAt": (
                    dt.datetime.utcnow() + dt.timedelta(seconds=self.config.playback_session_seconds)
                ).replace(microsecond=0).isoformat()
                + "Z",
                "usedAt": None,
                "invalidatedAt": None,
                "openedByIp": None,
                "openedByUserAgent": None,
            }
            db["playbackSessions"].append(playback_session)

            return {
                "token": clone(token),
                "share": clone(share),
                "movie": clone(movie),
                "playback": {
                    "watchToken": playback_session["playbackToken"],
                    "watchPath": f"/watch/{playback_session['playbackToken']}",
                    "watchUrl": f"/watch/{playback_session['playbackToken']}",
                    "expiresAt": playback_session["expiresAt"],
                    "oneTime": True,
                    "clientSecret": playback_session["clientSecret"],
                },
            }

        return self.store.transaction(tx)

    def open_playback_session(self, playback_token, details, sign_playback_fn):
        if not playback_token:
            raise AppError("Token de reproducao e obrigatorio.", 400, "VALIDATION_ERROR")
        if not callable(sign_playback_fn):
            raise AppError("Assinador de reproducao invalido.", 500, "INTERNAL_ERROR")

        client_secret = details.get("clientSecret")
        ip_address = details.get("ipAddress")
        user_agent = details.get("userAgent")

        def tx(db):
            self._cleanup_expired_reservations(db)
            playback_session = next(
                (item for item in db["playbackSessions"] if item["playbackToken"] == playback_token), None
            )
            if not playback_session:
                raise AppError("Link de reproducao nao encontrado.", 404, "PLAYBACK_LINK_NOT_FOUND")
            if playback_session["status"] != "active":
                raise AppError("Link de reproducao invalido ou ja utilizado.", 409, "PLAYBACK_LINK_INVALID")
            if not client_secret or playback_session["clientSecret"] != client_secret:
                raise AppError("Link de reproducao nao autorizado neste navegador.", 403, "PLAYBACK_CLIENT_MISMATCH")

            movie = next((item for item in db["movies"] if item["id"] == playback_session["movieId"]), None)
            if not movie:
                raise AppError("Filme associado a sessao de reproducao nao encontrado.", 404, "MOVIE_NOT_FOUND")

            token = next((item for item in db["accessTokens"] if item["id"] == playback_session["accessTokenId"]), None)
            if not token:
                raise AppError("Token de acesso da sessao nao encontrado.", 404, "TOKEN_NOT_FOUND")
            if token["ownerId"] != playback_session["ownerId"] or token["status"] != "active":
                raise AppError("Link de reproducao invalido ou ja utilizado.", 409, "PLAYBACK_LINK_INVALID")

            share = next((item for item in db["shares"] if item["id"] == token["shareId"]), None)
            if not share:
                raise AppError("Cota associada a sessao de reproducao nao encontrada.", 404, "SHARE_NOT_FOUND")
            if share["state"] != "owned":
                raise AppError("A cota nao esta disponivel para reproducao.", 409, "INVALID_SHARE_STATE")

            now = now_iso()
            playback_session["status"] = "used"
            playback_session["usedAt"] = now
            playback_session["openedByIp"] = ip_address or None
            playback_session["openedByUserAgent"] = user_agent or None

            for sibling in db["playbackSessions"]:
                if (
                    sibling["accessTokenId"] == token["id"]
                    and sibling["status"] == "active"
                    and sibling["id"] != playback_session["id"]
                ):
                    sibling["status"] = "invalidated"
                    sibling["invalidatedAt"] = now

            token["status"] = "used"
            token["consumedAt"] = now

            share["state"] = "consumed"
            share["consumedAt"] = now
            share["updatedAt"] = now

            for listing in db["listings"]:
                if listing["shareId"] == share["id"] and listing["status"] == "active":
                    listing["status"] = "canceled"
                    listing["canceledAt"] = now

            transaction = {
                "id": next_id(db, "transaction", "txn"),
                "type": "token_consumed",
                "movieId": movie["id"],
                "shareId": share["id"],
                "sellerId": None,
                "buyerId": token["ownerId"],
                "priceCents": 0,
                "createdAt": now,
            }
            db["transactions"].append(transaction)

            playback = sign_playback_fn(
                {
                    "libraryId": movie["bunnyLibraryId"],
                    "videoId": movie["bunnyVideoId"],
                    "sessionTag": playback_session["playbackToken"],
                }
            )
            return {
                "movie": {"id": movie["id"], "title": movie["title"]},
                "playback": clone(playback),
                "session": {
                    "usedAt": playback_session["usedAt"],
                    "expiresAt": playback_session["expiresAt"],
                },
            }

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

    def get_user_transactions(self, user_id):
        def tx(db):
            self._cleanup_expired_reservations(db)
            txs = []
            for txn in db["transactions"]:
                if txn.get("buyerId") != user_id and txn.get("sellerId") != user_id:
                    continue
                movie = next((item for item in db["movies"] if item["id"] == txn["movieId"]), None)
                txs.append(
                    {
                        **clone(txn),
                        "price": txn["priceCents"] / 100,
                        "movieTitle": movie["title"] if movie else "Filme removido",
                    }
                )
            txs.sort(key=lambda item: parse_date_ms(item.get("createdAt")), reverse=True)
            return txs

        return self.store.transaction(tx)

    def _create_session(self, db, user_id, issued_at):
        created = issued_at or now_iso()
        created_dt = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
        expires = created_dt + dt.timedelta(days=self.config.session_duration_days)
        session = {
            "id": next_id(db, "session", "ses"),
            "userId": user_id,
            "token": random_token("ses"),
            "createdAt": created,
            "expiresAt": expires.replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        db["sessions"].append(session)
        return session

    def _issue_token(self, db, payload):
        now = now_iso()
        token = {
            "id": next_id(db, "token", "at"),
            "token": random_token("urbetk"),
            "movieId": payload["movieId"],
            "shareId": payload["shareId"],
            "ownerId": payload["ownerId"],
            "reason": payload["reason"],
            "status": "active",
            "issuedAt": now,
            "consumedAt": None,
            "revokedAt": None,
            "revocationReason": None,
        }
        db["accessTokens"].append(token)
        return token

    def _listings_for_movie(self, db, movie_id):
        items = []
        for listing in db["listings"]:
            if listing["movieId"] != movie_id or listing["status"] != "active":
                continue
            seller = next((user for user in db["users"] if user["id"] == listing["sellerId"]), None)
            items.append(
                {
                    "id": listing["id"],
                    "shareId": listing["shareId"],
                    "priceCents": listing["priceCents"],
                    "price": listing["priceCents"] / 100,
                    "seller": sanitize_user(seller) if seller else None,
                    "createdAt": listing["createdAt"],
                }
            )
        items.sort(key=lambda item: parse_date_ms(item.get("createdAt")), reverse=True)
        return items

    def _create_payment_order(self, db, payload):
        now = now_iso()
        expires_at = (
            dt.datetime.utcnow() + dt.timedelta(minutes=self.config.checkout_reservation_minutes)
        ).replace(microsecond=0).isoformat() + "Z"
        order = {
            "id": next_id(db, "paymentOrder", "ord"),
            "type": payload["type"],
            "buyerId": payload["buyerId"],
            "sellerId": payload["sellerId"],
            "movieId": payload["movieId"],
            "shareId": payload["shareId"],
            "listingId": payload["listingId"],
            "amountCents": payload["amountCents"],
            "currency": payload["currency"],
            "provider": payload["provider"],
            "providerSessionId": None,
            "providerCheckoutUrl": None,
            "providerPaymentStatus": "pending",
            "providerRaw": None,
            "status": "pending",
            "failureReason": None,
            "createdAt": now,
            "updatedAt": now,
            "expiresAt": expires_at,
            "paidAt": None,
        }
        db["paymentOrders"].append(order)
        return order

    def _public_order(self, order):
        return {
            "id": order["id"],
            "type": order["type"],
            "buyerId": order["buyerId"],
            "sellerId": order["sellerId"],
            "movieId": order["movieId"],
            "shareId": order["shareId"],
            "listingId": order["listingId"],
            "amountCents": order["amountCents"],
            "amount": order["amountCents"] / 100,
            "currency": order["currency"],
            "provider": order.get("provider"),
            "providerSessionId": order.get("providerSessionId"),
            "providerCheckoutUrl": order.get("providerCheckoutUrl"),
            "providerPaymentStatus": order.get("providerPaymentStatus"),
            "status": order.get("status"),
            "failureReason": order.get("failureReason"),
            "createdAt": order.get("createdAt"),
            "updatedAt": order.get("updatedAt"),
            "expiresAt": order.get("expiresAt"),
            "paidAt": order.get("paidAt"),
        }

    def _assert_paid_amount_matches_order(self, order, checkout_status):
        if int(checkout_status.get("amountCents")) != int(order["amountCents"]):
            raise AppError("Valor pago nao corresponde ao valor da ordem.", 409, "PAYMENT_AMOUNT_MISMATCH")
        if str(checkout_status.get("currency", "")).upper() != str(order["currency"]).upper():
            raise AppError("Moeda do pagamento nao corresponde a ordem.", 409, "PAYMENT_CURRENCY_MISMATCH")

    def _finalize_paid_order(self, db, order, checkout_status):
        if order["type"] == "primary":
            movie = next((item for item in db["movies"] if item["id"] == order["movieId"]), None)
            if not movie or movie["status"] != "active":
                raise AppError("Filme indisponivel para finalizar ordem.", 409, "MOVIE_UNAVAILABLE")
            share = next((item for item in db["shares"] if item["id"] == order["shareId"]), None)
            if not share:
                raise AppError("Cota da ordem nao encontrada.", 404, "SHARE_NOT_FOUND")
            if share["state"] != "reserved" or share.get("reservedByOrderId") != order["id"]:
                raise AppError("Reserva da cota nao esta mais valida.", 409, "RESERVATION_INVALID")

            result = self._finalize_primary_purchase(
                db,
                {
                    "buyerId": order["buyerId"],
                    "movie": movie,
                    "share": share,
                    "priceCents": order["amountCents"],
                    "transactionType": "primary_purchase",
                },
            )
        elif order["type"] == "secondary":
            listing = next((item for item in db["listings"] if item["id"] == order["listingId"]), None)
            if not listing:
                raise AppError("Anuncio da ordem nao encontrado.", 404, "LISTING_NOT_FOUND")
            if listing["status"] != "reserved" or listing.get("reservedByOrderId") != order["id"]:
                raise AppError("Reserva do anuncio nao esta mais valida.", 409, "RESERVATION_INVALID")

            share = next((item for item in db["shares"] if item["id"] == listing["shareId"]), None)
            if not share:
                raise AppError("Cota do anuncio nao encontrada.", 404, "SHARE_NOT_FOUND")
            movie = next((item for item in db["movies"] if item["id"] == listing["movieId"]), None)
            if not movie or movie["status"] != "active":
                raise AppError("Filme indisponivel para finalizar ordem.", 409, "MOVIE_UNAVAILABLE")

            result = self._finalize_secondary_purchase(
                db,
                {
                    "buyerId": order["buyerId"],
                    "listing": listing,
                    "share": share,
                    "movie": movie,
                    "priceCents": order["amountCents"],
                    "transactionType": "secondary_purchase",
                },
            )
        else:
            raise AppError("Tipo de ordem invalido.", 400, "ORDER_TYPE_INVALID")

        now = now_iso()
        order["status"] = "paid"
        order["providerSessionId"] = checkout_status.get("sessionId") or order.get("providerSessionId")
        order["providerPaymentStatus"] = checkout_status.get("paymentStatus") or "paid"
        order["providerRaw"] = checkout_status.get("raw") or order.get("providerRaw")
        order["paidAt"] = now
        order["updatedAt"] = now
        return result

    def _finalize_primary_purchase(self, db, payload):
        buyer_id = payload["buyerId"]
        movie = payload["movie"]
        share = payload["share"]
        price_cents = payload["priceCents"]
        transaction_type = payload["transactionType"]
        now = now_iso()

        share["ownerId"] = buyer_id
        share["state"] = "owned"
        share["lastPriceCents"] = price_cents
        share["updatedAt"] = now
        share["reservedByOrderId"] = None
        share["reservationExpiresAt"] = None

        token = self._issue_token(
            db,
            {
                "movieId": movie["id"],
                "shareId": share["id"],
                "ownerId": buyer_id,
                "reason": "primary_purchase",
            },
        )

        transaction = {
            "id": next_id(db, "transaction", "txn"),
            "type": transaction_type,
            "movieId": movie["id"],
            "shareId": share["id"],
            "sellerId": movie["producerId"],
            "buyerId": buyer_id,
            "priceCents": price_cents,
            "createdAt": now,
        }
        db["transactions"].append(transaction)

        return {
            "movie": clone(movie),
            "share": clone(share),
            "token": clone(token),
            "transaction": clone(transaction),
        }

    def _finalize_secondary_purchase(self, db, payload):
        buyer_id = payload["buyerId"]
        listing = payload["listing"]
        share = payload["share"]
        movie = payload["movie"]
        price_cents = payload["priceCents"]
        transaction_type = payload["transactionType"]
        now = now_iso()

        active_token = next(
            (
                item
                for item in db["accessTokens"]
                if item["shareId"] == share["id"] and item["status"] == "active"
            ),
            None,
        )
        if active_token:
            active_token["status"] = "revoked"
            active_token["revokedAt"] = now
            active_token["revocationReason"] = "ownership_transfer"

        share["ownerId"] = buyer_id
        share["state"] = "owned"
        share["lastPriceCents"] = price_cents
        share["updatedAt"] = now
        share["reservedByOrderId"] = None
        share["reservationExpiresAt"] = None

        listing["status"] = "sold"
        listing["buyerId"] = buyer_id
        listing["soldAt"] = now
        listing["reservedByOrderId"] = None
        listing["reservationExpiresAt"] = None

        new_token = self._issue_token(
            db,
            {
                "movieId": movie["id"],
                "shareId": share["id"],
                "ownerId": buyer_id,
                "reason": "secondary_purchase",
            },
        )

        transaction = {
            "id": next_id(db, "transaction", "txn"),
            "type": transaction_type,
            "movieId": movie["id"],
            "shareId": share["id"],
            "sellerId": listing["sellerId"],
            "buyerId": buyer_id,
            "priceCents": price_cents,
            "createdAt": now,
        }
        db["transactions"].append(transaction)

        return {
            "listing": clone(listing),
            "share": clone(share),
            "token": clone(new_token),
            "transaction": clone(transaction),
        }

    def _release_order_reservation(self, db, order, now_value=None):
        now = now_value or now_iso()
        if order["type"] == "primary":
            share = next((item for item in db["shares"] if item["id"] == order["shareId"]), None)
            if share and share["state"] == "reserved" and share.get("reservedByOrderId") == order["id"]:
                share["state"] = "available"
                share["reservedByOrderId"] = None
                share["reservationExpiresAt"] = None
                share["updatedAt"] = now
            return

        if order["type"] == "secondary":
            listing = next((item for item in db["listings"] if item["id"] == order["listingId"]), None)
            if listing and listing["status"] == "reserved" and listing.get("reservedByOrderId") == order["id"]:
                listing["status"] = "active"
                listing["reservedByOrderId"] = None
                listing["reservationExpiresAt"] = None

    def _cleanup_expired_reservations(self, db):
        now_ms = utc_now_ms()

        for order in db["paymentOrders"]:
            if order["status"] != "pending":
                continue
            expires_ms = parse_date_ms(order.get("expiresAt"))
            if not expires_ms or expires_ms > now_ms:
                continue
            self._release_order_reservation(db, order, now_iso())
            order["status"] = "expired"
            order["failureReason"] = "Reserva expirada antes da confirmacao do pagamento."
            order["updatedAt"] = now_iso()

        for playback_session in db["playbackSessions"]:
            if playback_session["status"] != "active":
                continue
            expires_ms = parse_date_ms(playback_session.get("expiresAt"))
            if not expires_ms or expires_ms > now_ms:
                continue
            playback_session["status"] = "expired"
            playback_session["invalidatedAt"] = now_iso()
