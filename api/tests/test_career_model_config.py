from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.controllers.model_config_controller import router
from app.core.dependencies import get_current_user
from app.core.exceptions import register_exception_handlers
from app.core.llm.chat_model import build_default_chat_model
from app.core.security import encrypt_secret
from app.db.postgres import get_session


class ModelSaveTest(TestCase):
    def test_invalid_encryption_key_returns_configuration_error(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
        app.dependency_overrides[get_session] = lambda: None

        with TestClient(app) as client, patch.object(settings, "fernet_key", "invalid"):
            response = client.post("/models", json={
                "type": "chat", "provider": "deepseek", "name": "Demo",
                "model_name": "deepseek-flash", "api_key": "test-key",
                "base_url": "https://api.deepseek.com",
            })

        self.assertEqual(response.status_code, 503)
        self.assertIn("FERNET_KEY", response.json()["message"])


class CareerDeepSeekTest(IsolatedAsyncioTestCase):
    async def test_named_tool_mode_applies_only_to_official_deepseek_endpoint(self):
        with patch.object(settings, "fernet_key", Fernet.generate_key().decode()):
            config = SimpleNamespace(model_name="deepseek-flash", api_key_encrypted=encrypt_secret("test-key"))
            with patch("app.core.llm.chat_model.get_default_chat_config", return_value=config):
                config.base_url = "https://api.deepseek.com/v1"
                model, _ = await build_default_chat_model(None, uuid4(), deepseek_tool_mode=True)
                self.assertEqual(model.extra_body, {"thinking": {"type": "disabled"}})
                model, _ = await build_default_chat_model(None, uuid4())
                self.assertIsNone(model.extra_body)

                config.base_url = "https://models.example.com/v1"
                model, _ = await build_default_chat_model(None, uuid4(), deepseek_tool_mode=True)
                self.assertIsNone(model.extra_body)
