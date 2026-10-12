import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deskcal import config


class EnvFileTests(unittest.TestCase):
    def load(self, toml: str, env: str | None = None) -> config.Config:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            path = Path(tmp) / "config.toml"
            path.write_text(toml)
            if env is not None:
                (Path(tmp) / ".env").write_text(env)
            return config.load(path)

    def test_urls_come_from_env_file(self):
        cfg = self.load(
            'calendars = [{ name = "Home", url = "${T_HOME}" }, { name = "Work", url = "${T_WORK}" }]\n',
            '# secrets\nT_HOME=https://script.google.com/a/exec\nT_WORK="https://script.google.com/b/exec"\n',
        )
        self.assertEqual(cfg.calendars[0]["url"], "https://script.google.com/a/exec")
        self.assertEqual(cfg.calendars[1]["url"], "https://script.google.com/b/exec")

    def test_missing_variable_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "T_MISSING"):
            self.load('calendars = [{ name = "Home", url = "${T_MISSING}" }]\n')


if __name__ == "__main__":
    unittest.main()
