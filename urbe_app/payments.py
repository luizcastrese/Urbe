from ._loader import export_public, load_root_module

module = load_root_module("urbe_app._legacy_payments", "payments.py")
export_public(module, globals())


class OpenPixPaymentGateway(module.OpenPixPaymentGateway):
    def _build_split_payload(self, order):
        amount_cents = int(order.get("amountCents") or 0)
        seller_key = str(order.get("sellerPixKey") or "").strip()
        platform_key = str(self.split_pix_key or "").strip()
        platform_percent = int(self.split_percent or 0)

        if amount_cents <= 0:
            return []

        if seller_key:
            platform_fee = 0
            if platform_key and platform_percent > 0:
                platform_fee = int(round(amount_cents * (platform_percent / 100)))
                platform_fee = max(0, min(platform_fee, amount_cents))

            seller_amount = amount_cents - platform_fee
            splits = []
            if seller_amount > 0:
                splits.append({"pixKey": seller_key, "value": seller_amount})
            if platform_key and platform_fee > 0:
                splits.append({"pixKey": platform_key, "value": platform_fee})
            return splits

        if platform_key and platform_percent > 0:
            platform_fee = int(round(amount_cents * (platform_percent / 100)))
            if 0 < platform_fee < amount_cents:
                return [{"pixKey": platform_key, "value": platform_fee}]

        return []

    def create_checkout_session(self, order, description, buyer, success_url, cancel_url):
        correlation_id = order["id"]
        payload = {
            "correlationID": correlation_id,
            "value": order["amountCents"],
            "description": str(description or f"Cota Urbe - {order['movieId']}")[:100],
            "expiresIn": 900,
        }
        if buyer and buyer.get("email"):
            payload["payer"] = {"email": buyer["email"]}

        splits = self._build_split_payload(order)
        if splits:
            payload["splits"] = splits

        status, raw_text = self._request("POST", "/charge", payload)
        parsed = module.json.loads(raw_text) if raw_text else {}

        if status < 200 or status >= 300:
            raise module.AppError(
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
    return module.MockPaymentGateway(currency=str(payments_config.currency or "BRL").upper())


globals()["OpenPixPaymentGateway"] = OpenPixPaymentGateway
globals()["create_payment_gateway"] = create_payment_gateway
