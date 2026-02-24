import os
import shutil
import tempfile
import unittest

from py_backend.config import BunnyConfig, Config, PaymentsConfig, StripeConfig
from py_backend.errors import AppError
from py_backend.service import UrbeService
from py_backend.store import JsonStore


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="urbe-py-test-")
        db_file = os.path.join(self.temp_dir, "db.json")

        config = Config(
            port=3000,
            db_file=db_file,
            session_duration_days=30,
            checkout_reservation_minutes=15,
            playback_session_seconds=120,
            bunny=BunnyConfig(
                api_key="",
                default_library_id="12345",
                embed_token_key="",
                iframe_host="https://iframe.mediadelivery.net",
            ),
            payments=PaymentsConfig(
                provider="mock",
                currency="BRL",
                success_url="http://localhost:3000/?checkout=success&orderId={ORDER_ID}&session_id={CHECKOUT_SESSION_ID}",
                cancel_url="http://localhost:3000/?checkout=cancel&orderId={ORDER_ID}&session_id={CHECKOUT_SESSION_ID}",
                stripe=StripeConfig(secret_key="", api_base="https://api.stripe.com/v1"),
            ),
        )

        self.service = UrbeService(JsonStore(db_file), config)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_movie(self, producer_id, title="Filme Teste", bunny_video_id="video-guid-1"):
        return self.service.create_movie(
            producer_id,
            {
                "title": title,
                "description": "Teste",
                "genre": "Drama",
                "durationMinutes": 110,
                "priceCents": 2000,
                "totalShares": 1,
                "bunnyVideoId": bunny_video_id,
                "bunnyLibraryId": "12345",
            },
        )

    def test_revoga_token_antigo_apos_revenda(self):
        producer = self.service.register_user(
            {"name": "Produtor", "email": "produtor@urbe.test", "password": "123456"}
        )["user"]
        buyer_1 = self.service.register_user(
            {"name": "Alice", "email": "alice@urbe.test", "password": "123456"}
        )["user"]
        buyer_2 = self.service.register_user(
            {"name": "Bob", "email": "bob@urbe.test", "password": "123456"}
        )["user"]

        movie = self._create_movie(producer["id"])
        primary = self.service.buy_primary_share(buyer_1["id"], movie["id"])
        listing = self.service.create_listing(buyer_1["id"], primary["share"]["id"], 3500)
        secondary = self.service.buy_listing(buyer_2["id"], listing["id"])

        self.assertEqual(secondary["token"]["status"], "active")
        self.assertNotEqual(secondary["token"]["token"], primary["token"]["token"])

        with self.assertRaises(AppError):
            self.service.consume_access_token(buyer_1["id"], primary["token"]["token"])

    def test_token_so_permite_uma_visualizacao(self):
        producer = self.service.register_user(
            {"name": "Produtor", "email": "produtor2@urbe.test", "password": "123456"}
        )["user"]
        viewer = self.service.register_user(
            {"name": "Cliente", "email": "cliente@urbe.test", "password": "123456"}
        )["user"]

        movie = self._create_movie(producer["id"], title="Outro Filme", bunny_video_id="video-guid-2")
        purchase = self.service.buy_primary_share(viewer["id"], movie["id"])

        consumed = self.service.consume_access_token(viewer["id"], purchase["token"]["token"])
        self.assertTrue(consumed["playback"]["watchUrl"].startswith("/watch/"))

        opened = self.service.open_playback_session(
            consumed["playback"]["watchToken"],
            {
                "clientSecret": consumed["playback"]["clientSecret"],
                "ipAddress": "127.0.0.1",
                "userAgent": "test",
            },
            lambda info: {
                "embedUrl": f"https://iframe.mediadelivery.net/embed/{info['libraryId']}/{info['videoId']}",
                "expiresAt": "2099-01-01T00:00:00Z",
                "signed": False,
            },
        )
        self.assertIn("iframe.mediadelivery.net", opened["playback"]["embedUrl"])

        shares_after = self.service.get_user_shares(viewer["id"])
        self.assertEqual(shares_after[0]["state"], "consumed")

        with self.assertRaises(AppError):
            self.service.open_playback_session(
                consumed["playback"]["watchToken"],
                {
                    "clientSecret": consumed["playback"]["clientSecret"],
                    "ipAddress": "127.0.0.1",
                    "userAgent": "test",
                },
                lambda info: {"embedUrl": "https://example.com", "expiresAt": "2099-01-01T00:00:00Z", "signed": False},
            )

        with self.assertRaises(AppError):
            self.service.consume_access_token(viewer["id"], purchase["token"]["token"])

    def test_checkout_primario_mock_finaliza_compra(self):
        producer = self.service.register_user(
            {"name": "Produtora", "email": "produtora@urbe.test", "password": "123456"}
        )["user"]
        buyer = self.service.register_user(
            {"name": "Comprador", "email": "comprador@urbe.test", "password": "123456"}
        )["user"]
        movie = self._create_movie(producer["id"], title="Filme Pagamento", bunny_video_id="video-guid-pay-1")

        class InstantGateway:
            provider = "mock"

            def create_checkout_session(self, order, description, buyer, success_url, cancel_url):
                return {
                    "provider": "mock",
                    "sessionId": f"sess_{order['id']}",
                    "checkoutUrl": None,
                    "paid": True,
                    "amountCents": order["amountCents"],
                    "currency": order["currency"],
                    "paymentStatus": "paid",
                    "status": "complete",
                    "raw": {"mode": "instant"},
                }

            def get_checkout_session_status(self, session_id, expected_order):
                return {
                    "provider": "mock",
                    "sessionId": session_id,
                    "paid": True,
                    "amountCents": expected_order["amountCents"],
                    "currency": expected_order["currency"],
                    "paymentStatus": "paid",
                    "status": "complete",
                    "raw": {"mode": "instant"},
                }

        checkout = self.service.start_primary_checkout(buyer["id"], movie["id"], InstantGateway())
        self.assertEqual(checkout["order"]["status"], "paid")
        self.assertIsNotNone(checkout["purchase"])
        self.assertEqual(checkout["purchase"]["token"]["status"], "active")
        self.assertEqual(checkout["purchase"]["transaction"]["type"], "primary_purchase")

    def test_checkout_revenda_reserva_e_confirma(self):
        producer = self.service.register_user(
            {"name": "Produtor Revenda", "email": "revenda-produtor@urbe.test", "password": "123456"}
        )["user"]
        seller = self.service.register_user(
            {"name": "Vendedor", "email": "vendedor@urbe.test", "password": "123456"}
        )["user"]
        buyer = self.service.register_user(
            {"name": "Compradora", "email": "compradora@urbe.test", "password": "123456"}
        )["user"]

        movie = self._create_movie(producer["id"], title="Filme Revenda", bunny_video_id="video-guid-pay-2")
        first_purchase = self.service.buy_primary_share(seller["id"], movie["id"])
        listing = self.service.create_listing(seller["id"], first_purchase["share"]["id"], 4200)

        class DelayedGateway:
            provider = "mock"

            def create_checkout_session(self, order, description, buyer, success_url, cancel_url):
                return {
                    "provider": "mock",
                    "sessionId": f"sess_{order['id']}",
                    "checkoutUrl": "https://checkout.mock/session",
                    "paid": False,
                    "amountCents": order["amountCents"],
                    "currency": order["currency"],
                    "paymentStatus": "unpaid",
                    "status": "open",
                    "raw": {"mode": "delayed"},
                }

            def get_checkout_session_status(self, session_id, expected_order):
                return {
                    "provider": "mock",
                    "sessionId": session_id,
                    "paid": True,
                    "amountCents": expected_order["amountCents"],
                    "currency": expected_order["currency"],
                    "paymentStatus": "paid",
                    "status": "complete",
                    "raw": {"mode": "delayed"},
                }

        gateway = DelayedGateway()
        pending_checkout = self.service.start_listing_checkout(buyer["id"], listing["id"], gateway)
        self.assertEqual(pending_checkout["order"]["status"], "pending")

        seller_shares = self.service.get_user_shares(seller["id"])
        self.assertEqual(seller_shares[0]["activeListing"]["status"], "reserved")

        confirmed = self.service.confirm_payment_order(
            buyer["id"],
            pending_checkout["order"]["id"],
            pending_checkout["checkout"]["sessionId"],
            gateway,
        )
        self.assertEqual(confirmed["order"]["status"], "paid")
        self.assertIsNotNone(confirmed["purchase"])
        self.assertEqual(confirmed["purchase"]["token"]["status"], "active")
        self.assertNotEqual(confirmed["purchase"]["token"]["token"], first_purchase["token"]["token"])

        with self.assertRaises(AppError):
            self.service.consume_access_token(seller["id"], first_purchase["token"]["token"])


if __name__ == "__main__":
    unittest.main()

