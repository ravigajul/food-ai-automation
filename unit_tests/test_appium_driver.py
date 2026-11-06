#!/usr/bin/env python3
"""
Unit tests for AppiumDriver helpers.
No Appium, no device required — runs in < 1 second.

Usage:
    python unit_tests/test_appium_driver.py
    python -m pytest unit_tests/test_appium_driver.py -v
"""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

# Allow imports from the project root regardless of where pytest is invoked from
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# ---------------------------------------------------------------------------
# Stubs for Appium/Selenium deps so AppiumDriver imports cleanly without a
# real Appium installation.
# ---------------------------------------------------------------------------
def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m

def _install_stubs():
    """(Re-)install Appium/Selenium stubs."""
    _stub("appium")
    _stub("appium.webdriver", Remote=MagicMock())
    _stub("appium.webdriver.common")
    _stub("appium.webdriver.common.appiumby", AppiumBy=MagicMock())
    _stub("appium.options")
    _stub("appium.options.android", UiAutomator2Options=MagicMock)
    _stub("selenium")
    _stub("selenium.webdriver")
    _stub("selenium.webdriver.support")
    _stub("selenium.webdriver.support.ui", WebDriverWait=MagicMock())
    _stub("selenium.webdriver.support.expected_conditions")

def _load_appium_driver_class():
    """Load AppiumDriver directly from its source file.

    Using spec_from_file_location bypasses sys.modules package caching so
    other test files' stubs (e.g. test_verify_order.py registers
    src.appium_driver with AppiumDriver=object) can never interfere.

    test_state_machine.py stubs yaml with safe_load=lambda f: {} during
    collection. We restore the real yaml before loading so AppiumDriver can
    actually parse config files.
    """
    _install_stubs()
    # Restore real yaml if it was stubbed by another test file
    # (test_state_machine.py stubs yaml with safe_load=lambda f: {})
    sys.modules.pop("yaml", None)
    import yaml as _real_yaml  # fresh import from filesystem (.venv)
    sys.modules["yaml"] = _real_yaml
    spec = importlib.util.spec_from_file_location(
        "_appium_driver_under_test",
        os.path.join(_ROOT, "src", "appium_driver.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_appium_driver_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod.AppiumDriver

# Minimal config written to a temp file so AppiumDriver.__init__ can read it
_MINIMAL_CONFIG = """\
appium:
  server_url: "http://localhost:4723"
capabilities:
  platformName: "Android"
  automationName: "UiAutomator2"
timeouts:
  implicit_wait: 10
  explicit_wait: 15
test:
  screenshot_dir: ""
  audio_dir: ""
"""


def _write_config(content: str) -> str:
    """Write config content to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestTempPathResolution(unittest.TestCase):
    """AppiumDriver.__init__ should resolve empty dir settings to temp paths."""

    def setUp(self):
        self.AppiumDriver = _load_appium_driver_class()
        self.config_path = _write_config(_MINIMAL_CONFIG)

    def tearDown(self):
        os.unlink(self.config_path)

    def _make_driver(self, config_content=None):
        path = _write_config(config_content) if config_content else self.config_path
        driver = self.AppiumDriver(path)
        if config_content:
            os.unlink(path)
        return driver

    def test_empty_screenshot_dir_resolved_to_temp(self):
        driver = self._make_driver()
        resolved = driver.config["test"]["screenshot_dir"]
        self.assertTrue(resolved, "screenshot_dir should not be empty after init")
        self.assertIn(tempfile.gettempdir(), resolved)
        self.assertIn("screenshots", resolved)

    def test_empty_audio_dir_resolved_to_temp(self):
        driver = self._make_driver()
        resolved = driver.config["test"]["audio_dir"]
        self.assertTrue(resolved, "audio_dir should not be empty after init")
        self.assertIn(tempfile.gettempdir(), resolved)
        self.assertIn("pizza_voice_test", resolved)

    def test_explicit_screenshot_dir_not_overridden(self):
        config = _MINIMAL_CONFIG.replace('screenshot_dir: ""', 'screenshot_dir: "/custom/path"')
        driver = self._make_driver(config)
        self.assertEqual(driver.config["test"]["screenshot_dir"], "/custom/path")

    def test_explicit_audio_dir_not_overridden(self):
        config = _MINIMAL_CONFIG.replace('audio_dir: ""', 'audio_dir: "/custom/audio"')
        driver = self._make_driver(config)
        self.assertEqual(driver.config["test"]["audio_dir"], "/custom/audio")

    def test_missing_test_section_does_not_crash(self):
        config = "appium:\n  server_url: 'http://localhost:4723'\ncapabilities:\n  platformName: Android\n  automationName: UiAutomator2\ntimeouts:\n  implicit_wait: 10\n  explicit_wait: 15\n"
        driver = self._make_driver(config)
        self.assertIn("screenshot_dir", driver.config["test"])
        self.assertIn("audio_dir", driver.config["test"])


class TestEnsureAppiumRunning(unittest.TestCase):
    """_ensure_appium_running should skip launch when Appium is already up,
    and start it when it is not."""

    def setUp(self):
        self.AppiumDriver = _load_appium_driver_class()
        self.config_path = _write_config(_MINIMAL_CONFIG)

    def tearDown(self):
        os.unlink(self.config_path)

    def _make_driver(self):
        return self.AppiumDriver(self.config_path)

    def test_does_not_start_appium_when_already_running(self):
        driver = self._make_driver()
        with patch("urllib.request.urlopen") as mock_open, \
             patch("subprocess.Popen") as mock_popen:
            mock_open.return_value = MagicMock()  # /status responds OK
            driver._ensure_appium_running()
            mock_popen.assert_not_called()

    def test_starts_appium_when_not_running(self):
        driver = self._make_driver()
        call_count = 0

        def urlopen_side_effect(url, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise urllib.error.URLError("connection refused")  # first probe fails
            return MagicMock()  # subsequent polls succeed

        with patch("urllib.request.urlopen", side_effect=urlopen_side_effect), \
             patch("subprocess.Popen") as mock_popen, \
             patch("time.sleep"):
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            driver._ensure_appium_running()
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            self.assertEqual(args[0], "appium")

    def test_raises_if_appium_never_becomes_ready(self):
        driver = self._make_driver()

        def always_fail(url, timeout=None):
            raise urllib.error.URLError("connection refused")

        with patch("urllib.request.urlopen", side_effect=always_fail), \
             patch("subprocess.Popen") as mock_popen, \
             patch("time.sleep"), \
             patch("time.time", side_effect=[0, 0, 31]):  # deadline exceeded
            mock_popen.return_value = MagicMock()
            with self.assertRaises(RuntimeError) as ctx:
                driver._ensure_appium_running()
            self.assertIn("PATH", str(ctx.exception))

    def test_stop_terminates_auto_started_appium(self):
        driver = self._make_driver()
        mock_proc = MagicMock()
        driver._appium_proc = mock_proc
        driver.driver = None  # no WebDriver session open
        driver.stop()
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(driver._appium_proc)

    def test_stop_does_not_crash_when_appium_not_auto_started(self):
        driver = self._make_driver()
        driver.driver = None
        driver._appium_proc = None
        driver.stop()  # should not raise


if __name__ == "__main__":
    unittest.main()
