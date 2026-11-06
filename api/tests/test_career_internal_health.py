from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import settings
from app.controllers.career_internal_controller import router
from app.core.exceptions import register_exception_handlers


class CareerInternalHealthTest(TestCase):
    def setUp(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.path = "/internal/v1/health"

    def test_accepts_configured_service_token(self):
        with patch.object(settings, "career_agent_internal_token", SecretStr("test-token")):
            response = self.client.get(self.path, headers={"Authorization": "Bearer test-token"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "UP"})

    def test_rejects_missing_or_wrong_token(self):
        with patch.object(settings, "career_agent_internal_token", SecretStr("test-token")):
            for headers in ({}, {"Authorization": "Bearer wrong-token"}):
                with self.subTest(headers=headers):
                    response = self.client.get(self.path, headers=headers)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
                    self.assertEqual(response.json()["code"], 401)

    def test_unconfigured_endpoint_fails_closed(self):
        with patch.object(settings, "career_agent_internal_token", SecretStr("")):
            response = self.client.get(self.path)

        self.assertEqual(response.status_code, 503)
