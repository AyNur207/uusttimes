import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from uusttimes import create_app
from uusttimes.models import db


class ConfigTests(TestCase):
    def read_config(self, root, overrides=None):
        config = {
            "TESTING": True, "SECRET_KEY": "test-only-key",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "ADMIN_EMAIL": "", "ADMIN_PASSWORD": "",
        }
        config.update(overrides or {})
        with patch("uusttimes.__file__", str(root / "uusttimes" / "__init__.py")):
            app = create_app(config)
        value = app.config["DONATION_URL"]
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        return value

    def test_file_configuration_survives_recreation(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            url = "https://pay.example.org/from-file"
            (root / ".env").write_text(f"DONATION_URL={url}\n", encoding="utf-8-sig")
            self.assertEqual(self.read_config(root), url)
            self.assertEqual(self.read_config(root), url)
            self.assertNotIn("DONATION_URL", os.environ)

    def test_environment_overrides_file_and_test_config_overrides_both(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("DONATION_URL=https://pay.example.org/from-file\n", encoding="utf-8")
            with patch.dict(os.environ, {"DONATION_URL": "https://pay.example.org/from-shell"}):
                self.assertEqual(self.read_config(root), "https://pay.example.org/from-shell")
                self.assertEqual(
                    self.read_config(root, {"DONATION_URL": ""}), "",
                )

    def test_missing_file_is_optional(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.read_config(Path(directory)), "")
