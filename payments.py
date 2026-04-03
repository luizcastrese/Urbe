class OpenPixPaymentGateway:
    def __init__(self, split_pix_key=None, split_percent=0):
        self.split_pix_key = split_pix_key
        self.split_percent = split_percent

    def create_checkout_session(self, order):
        amount_cents = order["amountCents"]
        payload = {}
        if self.split_pix_key and self.split_percent > 0:
            split_value_cents = int(round(amount_cents * (self.split_percent / 100)))
            if 0 < split_value_cents < amount_cents:
                payload["splits"] = [{"pixKey": self.split_pix_key, "value": split_value_cents}]
        # Other session creation logic...

    @staticmethod
    def create_payment_gateway(payments_config):
        # Constructing OpenPixPaymentGateway
        return OpenPixPaymentGateway(
            split_pix_key=payments_config.openpix.split_pix_key,
            split_percent=payments_config.openpix.split_percent
        )
