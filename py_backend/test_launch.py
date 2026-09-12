import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from py_backend.config import (
    BunnyConfig,
    Config,
    OpenPixConfig,
    PaymentsConfig,
    assert_runtime_ready,
    production_gaps,
)
from py_backend.errors import AppError
from py_backend.payments import create_payment_gateway
from py_backend.service import UrbeService
from py_backend.store import JsonStore
from py_backend.utils import (
    extract_openpix_correlation_id,
    extract_openpix_event,
    is_openpix_expired_event,
    is_openpix_paid_event,
    load_env_file,
    verify_openpix_signature,
)


def launch_config(db_file, **overrides):
    values = dict(
        port=3000,
        db_file=db_file,
        database_url="",
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
            success_url="http://localhost:3000/?checkout=success&orderId={ORDER_ID}",
            cancel_url="http://localhost:3000/?checkout=cancel&orderId={ORDER_ID}",
            openpix=OpenPixConfig(app_id=""),
        ),
    )
    values.update(overrides)
    return Config(**values)


class DelayedGateway:
    provider = "openpix"

    def create_checkout_session(self, order, description, buyer, success_url, cancel_url):
        return {
            "provider": "openpix",
            "sessionId": order["id"],
            "checkoutUrl": None,
            "pixCopiaECola": "00020126",
            "qrCodeBase64": "https://example.test/qr.png",
            "expiresIn": 900,
            "paid": False,
            "amountCents": order["amountCents"],
            "currency": order["currency"],
            "paymentStatus": "pending",
            "status": "pending",
            "raw": {},
        }

    def get_checkout_session_status(self, session_id, expected_order):
        return {
            "provider": "openpix",
            "sessionId": session_id,
            "paid": True,
            "amountCents": expected_order["amountCents"],
            "currency": expected_order["currency"],
            "paymentStatus": "paid",
            "status": "complete",
            "raw": {},
        }


class LaunchHelpersTest(unittest.TestCase):
    def test_dotenv_nao_sobrescreve_ambiente(self):
        previous = os.environ.get("URBE_TEST_DOTENV")
        os.environ["URBE_TEST_DOTENV"] = "from-env"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, ".env")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("URBE_TEST_DOTENV=from-file\nURBE_TEST_DOTENV_NEW=ok\n")
                load_env_file(path)
                self.assertEqual(os.environ["URBE_TEST_DOTENV"], "from-env")
                self.assertEqual(os.environ["URBE_TEST_DOTENV_NEW"], "ok")
        finally:
            if previous is None:
                os.environ.pop("URBE_TEST_DOTENV", None)
            else:
                os.environ["URBE_TEST_DOTENV"] = previous
            os.environ.pop("URBE_TEST_DOTENV_NEW", None)

    def test_production_gaps_e_assert(self):
        config = launch_config("/tmp/unused.json", is_production=True)
        gaps = production_gaps(config)
        self.assertIn("PAYMENTS_PROVIDER nao pode ser mock", gaps)
        self.assertIn("DATABASE_URL", gaps)
        self.assertIn("OPENPIX_WEBHOOK_SECRET", gaps)
        with self.assertRaises(SystemExit):
            assert_runtime_ready(config)

        ready = launch_config(
            "/tmp/unused.json",
            is_production=True,
            database_url="postgres://urbe:urbe@localhost:5432/urbe",
            bunny=BunnyConfig(
                api_key="bunny-key",
                default_library_id="12345",
                embed_token_key="embed-key",
                iframe_host="https://iframe.mediadelivery.net",
            ),
            payments=PaymentsConfig(
                provider="openpix",
                currency="BRL",
                success_url="https://urbe.test/ok",
                cancel_url="https://urbe.test/cancel",
                openpix=OpenPixConfig(app_id="app", webhook_secret="secret"),
            ),
        )
        self.assertEqual(production_gaps(ready), [])
        assert_runtime_ready(ready)

    def test_check_lista_gaps_sem_inicializar_servicos(self):
        env = os.environ.copy()
        for key in (
            "OPENPIX_APP_ID",
            "OPENPIX_WEBHOOK_SECRET",
            "BUNNY_STREAM_API_KEY",
            "BUNNY_STREAM_LIBRARY_ID",
            "BUNNY_STREAM_EMBED_TOKEN_KEY",
        ):
            env[key] = ""
        env["URBE_ENV"] = "production"
        env["PAYMENTS_PROVIDER"] = "openpix"
        env["DATABASE_URL"] = "postgres://invalid:invalid@127.0.0.1:1/urbe"
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        result = subprocess.run(
            [sys.executable, "-m", "py_backend.server", "--check"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("Pendencias de lancamento", result.stdout)
        self.assertIn("OPENPIX_APP_ID", result.stdout)
        self.assertIn("OPENPIX_WEBHOOK_SECRET", result.stdout)

    def test_run_check_programatico_nao_inicializa_runtime(self):
        from py_backend import server

        called = {"n": 0}
        original = server.init_runtime

        def boom():
            called["n"] += 1
            raise AssertionError("init_runtime nao deve rodar no --check")

        server.init_runtime = boom
        try:
            try:
                server.run(["--check"])
            except SystemExit:
                pass
            self.assertEqual(called["n"], 0)
        finally:
            server.init_runtime = original

    def test_payload_oficial_openpix(self):
        body = {
            "event": "OPENPIX:CHARGE_COMPLETED",
            "charge": {"correlationID": "ord_9", "status": "COMPLETED", "value": 2000},
        }
        self.assertEqual(extract_openpix_event(body), "OPENPIX:CHARGE_COMPLETED")
        self.assertEqual(extract_openpix_correlation_id(body), "ord_9")
        self.assertTrue(is_openpix_paid_event(body["event"], body))
        self.assertTrue(is_openpix_expired_event("OPENPIX:CHARGE_EXPIRED"))
        self.assertFalse(is_openpix_paid_event("OPENPIX:CHARGE_CREATED", body))

        legacy = {"event": "pix_received", "data": {"correlationID": "ord_1"}}
        self.assertTrue(is_openpix_paid_event(legacy["event"], legacy))
        self.assertEqual(extract_openpix_correlation_id(legacy), "ord_1")

    def test_assinatura_hmac_hex_e_base64(self):
        raw = b'{"event":"OPENPIX:CHARGE_COMPLETED"}'
        secret = "whsec"
        digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256)
        self.assertTrue(verify_openpix_signature(raw, digest.hexdigest(), secret))
        self.assertTrue(verify_openpix_signature(raw, digest.hexdigest().upper(), secret))
        encoded = __import__("base64").b64encode(digest.digest()).decode("ascii")
        self.assertTrue(verify_openpix_signature(raw, encoded, secret))
        self.assertFalse(verify_openpix_signature(raw, "deadbeef", secret))


class LaunchServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="urbe-launch-")
        db_file = os.path.join(self.temp_dir, "db.json")
        self.service = UrbeService(JsonStore(db_file), launch_config(db_file))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_webhook_oficial_confirma_e_expiracao_libera_cota(self):
        producer = self.service.register_user(
            {"name": "Produtor", "email": "launch-produtor@urbe.test", "password": "123456"}
        )["user"]
        buyer = self.service.register_user(
            {"name": "Cliente", "email": "launch-cliente@urbe.test", "password": "123456"}
        )["user"]
        movie = self.service.create_movie(
            producer["id"],
            {
                "title": "Filme Lancamento",
                "description": "Teste",
                "genre": "Drama",
                "durationMinutes": 100,
                "priceCents": 2500,
                "totalShares": 1,
                "bunnyVideoId": "video-guid-launch",
                "bunnyLibraryId": "12345",
            },
        )
        pending = self.service.start_primary_checkout(buyer["id"], movie["id"], DelayedGateway())
        self.assertEqual(pending["order"]["status"], "pending")

        confirmed = self.service.confirm_order_payment(pending["order"]["id"], DelayedGateway())
        self.assertEqual(confirmed["order"]["status"], "paid")
        self.assertEqual(self.service.get_user_shares(buyer["id"])[0]["tokenState"]["code"], "ready")

    def test_expira_ordem_pendente_pelo_webhook(self):
        producer = self.service.register_user(
            {"name": "Produtor Exp", "email": "launch-exp-produtor@urbe.test", "password": "123456"}
        )["user"]
        buyer = self.service.register_user(
            {"name": "Cliente Exp", "email": "launch-exp-cliente@urbe.test", "password": "123456"}
        )["user"]
        movie = self.service.create_movie(
            producer["id"],
            {
                "title": "Filme Expira Pix",
                "description": "Teste",
                "genre": "Drama",
                "durationMinutes": 90,
                "priceCents": 1800,
                "totalShares": 1,
                "bunnyVideoId": "video-guid-expire",
                "bunnyLibraryId": "12345",
            },
        )
        pending = self.service.start_primary_checkout(buyer["id"], movie["id"], DelayedGateway())
        expired = self.service.expire_order_payment(pending["order"]["id"])
        self.assertEqual(expired["order"]["status"], "expired")
        movie_after = self.service.get_movie(movie["id"])
        self.assertEqual(movie_after["stats"]["primaryAvailable"], 1)


class LaunchHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from py_backend import server

        cls.server_module = server
        cls.temp_dir = tempfile.mkdtemp(prefix="urbe-http-")
        db_file = os.path.join(cls.temp_dir, "db.json")
        cls.original_store = server.STORE
        cls.original_service = server.SERVICE
        cls.original_gateway = server.PAYMENT_GATEWAY
        cls.original_secret = server.CONFIG.payments.openpix.webhook_secret
        store = JsonStore(db_file)
        server.STORE = store
        server.SERVICE = UrbeService(store, server.CONFIG)
        if server.PAYMENT_GATEWAY is None:
            server.PAYMENT_GATEWAY = create_payment_gateway(server.CONFIG.payments)
        server.CONFIG.payments.openpix.webhook_secret = "whsec_http"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.UrbeHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.server_module.STORE = cls.original_store
        cls.server_module.SERVICE = cls.original_service
        cls.server_module.PAYMENT_GATEWAY = cls.original_gateway
        cls.server_module.CONFIG.payments.openpix.webhook_secret = cls.original_secret
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_auth_me_anonimo_nao_e_401(self):
        with urllib.request.urlopen(self._url("/api/auth/me"), timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertIsNone(payload.get("user"))

    def test_health_e_cabecalhos(self):
        with urllib.request.urlopen(self._url("/api/health"), timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["service"], "urbe")
            self.assertIn(payload["store"], {"json", "postgres"})
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(response.headers.get("X-Frame-Options"), "SAMEORIGIN")

    def test_webhook_charge_completed(self):
        from py_backend import server

        producer = server.SERVICE.register_user(
            {"name": "HTTP Produtor", "email": f"http-prod-{self.port}@urbe.test", "password": "123456"}
        )["user"]
        buyer = server.SERVICE.register_user(
            {"name": "HTTP Cliente", "email": f"http-cli-{self.port}@urbe.test", "password": "123456"}
        )["user"]
        movie = server.SERVICE.create_movie(
            producer["id"],
            {
                "title": "Filme HTTP",
                "description": "Teste",
                "genre": "Drama",
                "durationMinutes": 80,
                "priceCents": 1500,
                "totalShares": 1,
                "bunnyVideoId": "video-guid-http",
                "bunnyLibraryId": "12345",
            },
        )
        pending = server.SERVICE.start_primary_checkout(buyer["id"], movie["id"], DelayedGateway())
        body = json.dumps(
            {
                "event": "OPENPIX:CHARGE_COMPLETED",
                "charge": {
                    "correlationID": pending["order"]["id"],
                    "status": "COMPLETED",
                    "value": pending["order"]["amountCents"],
                },
            }
        ).encode("utf-8")
        signature = hmac.new(b"whsec_http", body, hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            self._url("/api/payments/webhook/openpix"),
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["status"], "ok")
        shares = server.SERVICE.get_user_shares(buyer["id"])
        self.assertEqual(shares[0]["tokenState"]["code"], "ready")

    def test_webhook_assinatura_invalida(self):
        body = b'{"event":"OPENPIX:CHARGE_COMPLETED","charge":{"correlationID":"ord_x"}}'
        request = urllib.request.Request(
            self._url("/api/payments/webhook/openpix"),
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "X-OpenPix-Signature": "nope"},
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
