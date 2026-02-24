import json
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
            "successUrl": fill_template(
                success_url,
                {
                    "ORDER_ID": order["id"],
                    "CHECKOUT_SESSION_ID": session_id,
                },
            ),
            "cancelUrl": fill_template(
                cancel_url,
                {
                    "ORDER_ID": order["id"],
                    "CHECKOUT_SESSION_ID": session_id,
                },
            ),
            "paid": True,
            "amountCents": order["amountCents"],
            "currency": order["currency"],
            "paymentStatus": "paid",
            "status": "complete",
            "raw": {
                "mode": "mock",
                "note": "Pagamento aprovado automaticamente no provedor mock.",
            },
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
            "raw": {
                "mode": "mock",
                "note": "Sessao mock tratada como paga.",
            },
        }


class StripePaymentGateway:
    provider = "stripe"

    def __init__(self, secret_key, api_base, currency):
        if not secret_key:
            raise AppError("PAYMENTS_PROVIDER=stripe exige STRIPE_SECRET_KEY.", 500, "PAYMENTS_NOT_CONFIGURED")
        self.secret_key = secret_key
        self.api_base = api_base
        self.currency = currency

    def _request(self, method, path, body=None, content_type=None):
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
        }
        data = None

        if body is not None:
            if content_type:
                headers["Content-Type"] = content_type
            if isinstance(body, str):
                data = body.encode("utf-8")
            else:
                data = body

        req = urllib.request.Request(
            f"{self.api_base}{path}",
            method=method,
            headers=headers,
            data=data,
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                text = response.read().decode("utf-8")
                return response.status, text
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as error:
            raise AppError(f"Falha de rede Stripe: {error.reason}", 502, "STRIPE_NETWORK_ERROR")

    def create_checkout_session(self, order, description, buyer, success_url, cancel_url):
        session_success_url = fill_template(
            success_url,
            {
                "ORDER_ID": order["id"],
                "CHECKOUT_SESSION_ID": "{CHECKOUT_SESSION_ID}",
            },
        )
        session_cancel_url = fill_template(
            cancel_url,
            {
                "ORDER_ID": order["id"],
                "CHECKOUT_SESSION_ID": "{CHECKOUT_SESSION_ID}",
            },
        )

        params = {
            "mode": "payment",
            "success_url": session_success_url,
            "cancel_url": session_cancel_url,
            "client_reference_id": order["id"],
            "metadata[orderId]": order["id"],
            "metadata[orderType]": order["type"],
            "metadata[movieId]": order["movieId"],
            "line_items[0][price_data][currency]": str(order["currency"]).lower(),
            "line_items[0][price_data][unit_amount]": str(order["amountCents"]),
            "line_items[0][price_data][product_data][name]": str(description or "")[:120],
            "line_items[0][quantity]": "1",
        }
        if buyer and buyer.get("email"):
            params["customer_email"] = buyer["email"]

        status, raw_text = self._request(
            "POST",
            "/checkout/sessions",
            urllib.parse.urlencode(params),
            "application/x-www-form-urlencoded",
        )

        try:
            parsed = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            parsed = {"rawText": raw_text}

        if status < 200 or status >= 300:
            error_message = parsed.get("error", {}).get("message") or raw_text or "erro desconhecido"
            raise AppError(f"Falha ao iniciar checkout Stripe ({status}): {error_message}", 502, "STRIPE_CHECKOUT_FAILED")

        expires_at = parsed.get("expires_at")
        return {
            "provider": self.provider,
            "sessionId": parsed.get("id"),
            "checkoutUrl": parsed.get("url"),
            "paid": parsed.get("payment_status") == "paid" and parsed.get("status") == "complete",
            "amountCents": parsed.get("amount_total", order["amountCents"]),
            "currency": str(parsed.get("currency", order["currency"])).upper(),
            "paymentStatus": parsed.get("payment_status", "unpaid"),
            "status": parsed.get("status", "open"),
            "expiresAt": None if expires_at is None else str(expires_at),
            "raw": parsed,
        }

    def get_checkout_session_status(self, session_id, expected_order):
        if not session_id:
            raise AppError("sessionId e obrigatorio para confirmar checkout Stripe.", 400, "VALIDATION_ERROR")

        status, raw_text = self._request("GET", f"/checkout/sessions/{urllib.parse.quote(session_id)}")
        try:
            parsed = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            parsed = {"rawText": raw_text}

        if status < 200 or status >= 300:
            error_message = parsed.get("error", {}).get("message") or raw_text or "erro desconhecido"
            raise AppError(f"Falha ao consultar sessao Stripe ({status}): {error_message}", 502, "STRIPE_CHECKOUT_FETCH_FAILED")

        amount = parsed.get("amount_total")
        try:
            amount_cents = int(amount)
        except (TypeError, ValueError):
            amount_cents = expected_order["amountCents"]

        return {
            "provider": self.provider,
            "sessionId": parsed.get("id"),
            "paid": parsed.get("payment_status") == "paid" and parsed.get("status") == "complete",
            "amountCents": amount_cents,
            "currency": str(parsed.get("currency", expected_order["currency"])).upper(),
            "paymentStatus": parsed.get("payment_status", "unknown"),
            "status": parsed.get("status", "unknown"),
            "raw": parsed,
        }


def create_payment_gateway(payments_config):
    provider = str(payments_config.provider or "mock").lower()
    if provider == "stripe":
        return StripePaymentGateway(
            secret_key=payments_config.stripe.secret_key,
            api_base=payments_config.stripe.api_base,
            currency=str(payments_config.currency or "BRL").upper(),
        )
    return MockPaymentGateway(currency=str(payments_config.currency or "BRL").upper())

