import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import AppError
from .utils import fill_template, random_token


class MockPaymentGateway:
    provider = "mock"

    def __init__(self, currency):
        self.currency = currency

    def create_checkout_session(self, order, description, buyer, success_url, cancel_url):
        session_id = random_token("mck_sess")
        return {
            "provider": self.provider,
            "sessionId": session_id,
            "checkoutUrl": None,
            "successUrl": fill_template(success_url, {"ORDER_ID": order["id"], "CHECKOUT_SESSION_ID": session_id}),
            "cancelUrl": fill_template(cancel_url, {"ORDER_ID": order["id"], "CHECKOUT_SESSION_ID": session_id}),
            "paid": True,
            "amountCents": order["amountCents"],
            "currency": order["currency"],
            "paymentStatus": "paid",
            "status": "complete",
            "raw": {"mode": "mock", "note": "Pagamento aprovado automaticamente"},
        }

    def get_checkout_session_status(self, session_id, expected_order):
        return {
            "provider": self.provider,
            "sessionId": session_id,
            "paid": True,
            "amountCents": expected_order["amountCents"],
            "currency": expected_order["currency"],
            "paymentStatus": "paid",
            "status": "complete",
            "raw": {"mode": "mock"},
        }


class StripePaymentGateway:
    provider = "stripe"

    def __init__(self, secret_key, api_base, currency):
        if not secret_key:
            raise AppError("PAYMENTS_PROVIDER=stripe exige STRIPE_SECRET_KEY.", 500, "PAYMENTS_NOT_CONFIGURED")
        self.secret_key = secret_key
        self.api_base = str(api_base or "https://api.stripe.com/v1").rstrip("/")
        self.currency = str(currency or "BRL").lower()

    def _request(self, method, path, form_fields=None):
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = urllib.parse.urlencode(form_fields or []).encode("utf-8") if form_fields is not None else None
        req = urllib.request.Request(f"{self.api_base}{path}", method=method, headers=headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", errors="replace")

    def create_checkout_session(self, order, description, buyer, success_url, cancel_url):
        success = str(success_url or "").replace("{ORDER_ID}", order["id"])
        cancel = str(cancel_url or "").replace("{ORDER_ID}", order["id"])
        if "{CHECKOUT_SESSION_ID}" not in success:
            joiner = "&" if "?" in success else "?"
            success = f"{success}{joiner}session_id={{CHECKOUT_SESSION_ID}}"

        fields = [
            ("mode", "payment"),
            ("success_url", success),
            ("cancel_url", cancel),
            ("client_reference_id", order["id"]),
            ("metadata[order_id]", order["id"]),
            ("line_items[0][quantity]", "1"),
            ("line_items[0][price_data][currency]", self.currency),
            ("line_items[0][price_data][unit_amount]", str(int(order["amountCents"]))),
            ("line_items[0][price_data][product_data][name]", str(description or f"Cota Urbe - {order['movieId']}")[:120]),
            ("expires_at", str(int(time.time()) + 30 * 60)),
            ("automatic_payment_methods[enabled]", "true"),
        ]
        email = str((buyer or {}).get("email") or "").strip()
        if email:
            fields.append(("customer_email", email))

        status, raw_text = self._request("POST", "/checkout/sessions", fields)
        parsed = json.loads(raw_text) if raw_text else {}
        if status < 200 or status >= 300:
            message = ""
            if isinstance(parsed, dict):
                err = parsed.get("error") or {}
                message = err.get("message") if isinstance(err, dict) else str(err)
            raise AppError(f"Falha ao criar checkout Stripe: {message or raw_text}", 502, "STRIPE_CHECKOUT_FAILED")

        session_id = str(parsed.get("id") or "")
        checkout_url = str(parsed.get("url") or "")
        if not session_id or not checkout_url:
            raise AppError("Stripe nao devolveu a URL de checkout.", 502, "STRIPE_CHECKOUT_FAILED")

        return {
            "provider": self.provider,
            "sessionId": session_id,
            "checkoutUrl": checkout_url,
            "paid": False,
            "amountCents": order["amountCents"],
            "currency": str(order.get("currency") or self.currency).upper(),
            "paymentStatus": "pending",
            "status": "pending",
            "raw": parsed,
        }

    def get_checkout_session_status(self, session_id, expected_order):
        session_id = str(session_id or "").strip()
        if not session_id:
            raise AppError("Sessao Stripe ausente.", 400, "VALIDATION_ERROR")

        status, raw_text = self._request("GET", f"/checkout/sessions/{session_id}")
        parsed = json.loads(raw_text) if raw_text else {}
        if status < 200 or status >= 300:
            raise AppError("Falha ao consultar checkout Stripe.", 502, "STRIPE_LOOKUP_FAILED")

        return session_status_from_stripe(parsed, self.currency)


def session_status_from_stripe(session, fallback_currency="BRL"):
    session = session if isinstance(session, dict) else {}
    payment_status = str(session.get("payment_status") or "").strip().lower()
    session_status = str(session.get("status") or "").strip().lower()
    paid = payment_status == "paid"
    amount = session.get("amount_total")
    try:
        amount_cents = int(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount_cents = None
    currency = str(session.get("currency") or fallback_currency or "BRL").upper()
    expired = session_status == "expired" or payment_status in {"unpaid", ""} and session_status == "expired"
    return {
        "provider": "stripe",
        "sessionId": session.get("id"),
        "paid": paid,
        "amountCents": amount_cents,
        "currency": currency,
        "paymentStatus": "paid" if paid else "pending",
        "status": "complete" if paid else ("expired" if expired else "pending"),
        "raw": session,
    }


def create_payment_gateway(payments_config):
    provider = str(payments_config.provider or "mock").lower()
    if provider == "stripe":
        stripe = getattr(payments_config, "stripe", None)
        return StripePaymentGateway(
            secret_key=getattr(stripe, "secret_key", "") if stripe else "",
            api_base=getattr(stripe, "api_base", "https://api.stripe.com/v1") if stripe else "https://api.stripe.com/v1",
            currency=str(payments_config.currency or "BRL").upper(),
        )
    return MockPaymentGateway(currency=str(payments_config.currency or "BRL").upper())
