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


class OpenPixPaymentGateway:
    provider = "openpix"

    def __init__(self, app_id, api_base, currency, split_pix_key="", split_percent=0):
        if not app_id:
            raise AppError("PAYMENTS_PROVIDER=openpix exige OPENPIX_APP_ID.", 500, "PAYMENTS_NOT_CONFIGURED")
        self.app_id = app_id
        self.api_base = api_base
        self.currency = currency
        self.split_pix_key = str(split_pix_key or "").strip()
        self.split_percent = int(split_percent) if isinstance(split_percent, int) else 0

    def _request(self, method, path, json_body=None):
        headers = {"Authorization": f"Bearer {self.app_id}", "Content-Type": "application/json"}
        data = json.dumps(json_body).encode("utf-8") if json_body else None

        req = urllib.request.Request(f"{self.api_base}{path}", method=method, headers=headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def create_checkout_session(self, order, description, buyer, success_url, cancel_url):
        correlation_id = order["id"]
        payload = {
            "correlationID": correlation_id,
            "value": order["amountCents"],
            "description": str(description or f"Cota Urbe - {order['movieId']}")[:100],
            "expiresIn": 900,  # 15 minutos
        }
        if buyer and buyer.get("email"):
            payload["payer"] = {"email": buyer["email"]}

        if self.split_pix_key and self.split_percent > 0:
            split_value_cents = int(round(order["amountCents"] * (self.split_percent / 100)))
            if 0 < split_value_cents < order["amountCents"]:
                payload["splits"] = [
                    {
                        "pixKey": self.split_pix_key,
                        "value": split_value_cents,
                    }
                ]

        status, raw_text = self._request("POST", "/charge", payload)
        parsed = json.loads(raw_text) if raw_text else {}

        if status < 200 or status >= 300:
            raise AppError(
                f"Falha ao criar Pix OpenPix: {parsed.get('error') or raw_text}",
                502,
                "OPENPIX_CHECKOUT_FAILED",
            )

        charge = parsed.get("charge", {})
        return {
            "provider": self.provider,
            "sessionId": correlation_id,
            "checkoutUrl": None,
            "pixCopiaECola": charge.get("pixCopiaECola"),
            "qrCodeBase64": charge.get("qrCode"),
            "paid": False,
            "amountCents": order["amountCents"],
            "currency": self.currency,
            "paymentStatus": "pending",
            "status": "pending",
            "raw": parsed,
        }

    def get_checkout_session_status(self, session_id, expected_order):
        status, raw_text = self._request("GET", f"/charge/{session_id}")
        parsed = json.loads(raw_text) if raw_text else {}
        charge = parsed.get("charge", {})
        paid = charge.get("status") == "COMPLETED"

        return {
            "provider": self.provider,
            "sessionId": session_id,
            "paid": paid,
            "amountCents": expected_order["amountCents"],
            "currency": self.currency,
            "paymentStatus": "paid" if paid else "pending",
            "status": "complete" if paid else "pending",
            "raw": parsed,
        }


def create_payment_gateway(payments_config):
    provider = str(payments_config.provider or "mock").lower()
    if provider == "openpix":
        return OpenPixPaymentGateway(
            app_id=payments_config.openpix.app_id,
            api_base=payments_config.openpix.api_base,
            currency=str(payments_config.currency or "BRL").upper(),
            split_pix_key=getattr(payments_config.openpix, "split_pix_key", ""),
            split_percent=getattr(payments_config.openpix, "split_percent", 0),
        )
    return MockPaymentGateway(currency=str(payments_config.currency or "BRL").upper())