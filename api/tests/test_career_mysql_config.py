"""Regression checks for the shared local MySQL configuration."""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import config
from scripts import configure_career_mysql


class CareerMySQLConfigTest(unittest.TestCase):
    def test_compose_password_is_used_for_an_empty_api_override(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compose.career.yml").touch()
            (root / ".env").write_text("CAREER_MYSQL_PASSWORD=fixture-from-compose\n", encoding="utf-8")
            api_env = root / "api.env"
            api_env.write_text("CAREER_MYSQL_PASSWORD=\n", encoding="utf-8")
            with patch.object(config, "_PROJECT_ROOT", root), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(config.Settings(_env_file=api_env).career_mysql_password.get_secret_value(),
                                 "fixture-from-compose")
                os.environ["CAREER_MYSQL_PASSWORD"] = "fixture-process-override"
                self.assertEqual(config.Settings(_env_file=api_env).career_mysql_password.get_secret_value(),
                                 "fixture-process-override")

    def test_recover_container_password_once_and_keep_other_settings(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compose.career.yml").touch()
            env_path = root / ".env"
            env_path.write_text("APP_ENV=development\nCAREER_MYSQL_PASSWORD=\n", encoding="utf-8")
            password = "fixture#'${LITERAL}"
            with (
                patch.object(configure_career_mysql, "ROOT", root),
                patch.object(configure_career_mysql, "docker_command", return_value="docker"),
                patch.object(configure_career_mysql, "docker_output", side_effect=[
                    "container-id", json.dumps(["MYSQL_PASSWORD=" + password]),
                ]) as docker,
                patch("builtins.print") as console,
            ):
                configure_career_mysql.main()
                configure_career_mysql.main()
                self.assertEqual(docker.call_count, 2)
                self.assertNotIn(password, str(console.call_args_list))

            with patch.object(config, "_PROJECT_ROOT", root), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(config.Settings(_env_file=None).career_mysql_password.get_secret_value(), password)
            self.assertIn("APP_ENV=development", env_path.read_text(encoding="utf-8"))
