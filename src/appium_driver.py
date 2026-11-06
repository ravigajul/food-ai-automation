"""
Appium Driver Wrapper for Voice Ordering App
"""
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os
import subprocess
import tempfile
import urllib.request
import urllib.error
import yaml
import time
from typing import Optional, List


class AppiumDriver:
    """Wrapper for Appium WebDriver with helper methods"""

    def __init__(self, config_path: str = "config/appium_config.yaml"):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Resolve empty directory settings to platform-appropriate temp paths so
        # all callers (run_suite.py, end_to_end_voice_test.py, etc.) get a valid
        # non-empty path from driver.config without needing their own fallbacks.
        test_cfg = self.config.setdefault('test', {})
        if not test_cfg.get('screenshot_dir'):
            test_cfg['screenshot_dir'] = os.path.join(tempfile.gettempdir(), "screenshots")
        if not test_cfg.get('audio_dir'):
            test_cfg['audio_dir'] = os.path.join(tempfile.gettempdir(), "pizza_voice_test")

        self.driver: Optional[webdriver.Remote] = None
        self.wait: Optional[WebDriverWait] = None
        self._appium_proc: Optional[subprocess.Popen] = None  # set if we auto-started Appium

    def _ensure_appium_running(self) -> None:
        """Start Appium automatically if it is not already running."""
        server_url = self.config['appium']['server_url']
        status_url = f"{server_url}/status"

        # Probe the /status endpoint — fast, no side effects
        try:
            urllib.request.urlopen(status_url, timeout=3)
            print("   Appium server already running.")
            return
        except (urllib.error.URLError, OSError):
            pass

        print("   Appium not running — starting server...")
        self._appium_proc = subprocess.Popen(
            ["appium"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait up to 30 s for Appium to become ready
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                urllib.request.urlopen(status_url, timeout=2)
                print("   Appium server started successfully.")
                return
            except (urllib.error.URLError, OSError):
                time.sleep(1)

        self._appium_proc.terminate()
        raise RuntimeError(
            "Appium server did not become ready within 30 seconds. "
            "Check that 'appium' is installed and on PATH."
        )

    def start(self):
        """Initialize and start Appium driver (auto-starts Appium if needed)."""
        print("🚀 Starting Appium driver...")

        self._ensure_appium_running()

        options = UiAutomator2Options()
        for key, value in self.config['capabilities'].items():
            options.set_capability(key, value)

        self.driver = webdriver.Remote(
            self.config['appium']['server_url'],
            options=options
        )

        # Set implicit wait
        timeout = self.config['timeouts']['implicit_wait']
        self.driver.implicitly_wait(timeout)

        # Initialize WebDriverWait
        self.wait = WebDriverWait(
            self.driver,
            self.config['timeouts']['explicit_wait']
        )

        print("✅ Appium driver started successfully")
        return self

    def stop(self):
        """Stop Appium driver and shut down Appium server if we started it."""
        if self.driver:
            print("🛑 Stopping Appium driver...")
            self.driver.quit()
            self.driver = None
        if self._appium_proc:
            print("🛑 Stopping Appium server (auto-started)...")
            self._appium_proc.terminate()
            self._appium_proc = None
    
    def find_element_safe(self, by, value, timeout=10):
        """Find element with explicit wait and error handling"""
        try:
            wait = WebDriverWait(self.driver, timeout)
            element = wait.until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except Exception as e:
            print(f"⚠️  Element not found: {by}={value}, Error: {e}")
            return None
    
    def tap_by_coordinates(self, x: int, y: int):
        """Tap at specific coordinates"""
        self.driver.execute_script("mobile: tapGesture", {"x": x, "y": y})
    
    def get_visible_text_elements(self) -> List[str]:
        """Get all visible text elements on screen for AI validation.
        Reads both @text and @content-desc — WebView/custom elements may only
        expose content-desc (appium-automation.md rule #4).
        """
        try:
            seen = set()
            results = []
            for xpath, attr in [("//*[@text != '']", "text"),
                                 ("//*[@content-desc != '']", "content-desc")]:
                for elem in self.driver.find_elements(AppiumBy.XPATH, xpath):
                    val = elem.get_attribute(attr)
                    if val and val.strip() and val.strip() not in seen:
                        seen.add(val.strip())
                        results.append(val.strip())
            return results
        except:
            return []
    
    def get_screen_state(self) -> dict:
        """Get current screen state for validation"""
        return {
            "activity": self.driver.current_activity,
            "package": self.driver.current_package,
            "visible_texts": self.get_visible_text_elements(),
            "screenshot": self.take_screenshot_base64()
        }
    
    def take_screenshot(self, name: str):
        """Take screenshot and save to file"""
        screenshot_dir = self.config['test']['screenshot_dir']
        import os
        os.makedirs(screenshot_dir, exist_ok=True)
        
        filepath = f"{screenshot_dir}/{name}.png"
        self.driver.save_screenshot(filepath)
        print(f"📸 Screenshot saved: {filepath}")
        return filepath
    
    def take_screenshot_base64(self) -> str:
        """Get screenshot as base64 string"""
        return self.driver.get_screenshot_as_base64()
    
    def wait_for_activity(self, activity_name: str, timeout: int = 10) -> bool:
        """Wait for specific activity to appear"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            current = self.driver.current_activity
            if activity_name in current:
                return True
            time.sleep(0.5)
        return False
    
    def is_element_visible(self, by, value) -> bool:
        """Check if element is visible"""
        try:
            element = self.driver.find_element(by, value)
            return element.is_displayed()
        except:
            return False


def diagnose_input_element(element, label: str = "element") -> dict:
    """
    Print diagnostic attributes for an Appium element and warn when it cannot accept input.

    Call this the moment click/send_keys/mobile:type isn't working — it identifies
    the failure mode in one step instead of iterating through methods blindly.

    Returns a dict of the key attributes for programmatic use.
    """
    cls      = element.get_attribute("class") or ""
    txt      = element.get_attribute("text") or ""
    desc     = element.get_attribute("content-desc") or ""
    hint     = element.get_attribute("hint") or ""
    focusable = element.get_attribute("focusable") or ""
    clickable = element.get_attribute("clickable") or ""
    enabled   = element.get_attribute("enabled") or ""
    r         = element.rect

    print(f"[diagnose] {label}:")
    print(f"  class     = {cls!r}")
    print(f"  text      = {txt!r}   hint = {hint!r}   content-desc = {desc!r}")
    print(f"  focusable = {focusable}   clickable = {clickable}   enabled = {enabled}")
    print(f"  rect      : x={r['x']} y={r['y']} w={r['width']} h={r['height']}")

    if "EditText" not in cls and clickable == "false":
        print(f"  ⚠️  WRONG ELEMENT: {cls!r} is not an EditText and clickable=false.")
        print(f"     This is likely an accessibility wrapper (React Native View with content-desc).")
        print(f"     Fix: use //android.widget.EditText or UiSelector().className('android.widget.EditText')")
    elif "EditText" not in cls:
        print(f"  ⚠️  Not an EditText — typing may not work. Prefer android.widget.EditText.")
    elif clickable == "false":
        print(f"  ⚠️  EditText found but clickable=false — click() may not show keyboard.")
    else:
        print(f"  ✅ android.widget.EditText with clickable=true — correct element for input.")
        print(f"     Pattern: click() → sleep(2.5) → adb input text '...' (do NOT call clear() in between)")

    return {"class": cls, "text": txt, "hint": hint, "content-desc": desc,
            "focusable": focusable, "clickable": clickable, "enabled": enabled, "rect": r}


if __name__ == "__main__":
    # Test the driver
    driver = AppiumDriver()
    try:
        driver.start()
        print(f"Current activity: {driver.driver.current_activity}")
        print(f"Visible texts: {driver.get_visible_text_elements()[:5]}")
        driver.take_screenshot("test_screenshot")
    finally:
        driver.stop()
