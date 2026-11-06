#!/usr/bin/env python3
"""
Navigation Debug Script — Pizza Voice Test
==========================================
Runs a dry-run of every navigation step (no audio, no conversation) and
collects diagnostic data to pinpoint failures before a full test run.

What it does:
  1. Pre-flight checks  — ADB device, Appium server, Ollama, app installed
  2. ADB logcat capture — background thread; filters crashes/errors for the app
  3. Navigation trace   — each step timed + screenshotted
     Step 1: Launch app
     Step 2: Scroll to "Start Voice Order"
     Step 3: Click "Start Voice Order"
     Step 4: Wait for VOICE ORDERING screen
     Step 5: Mic permission dialog (grant if present)
     Step 6: Verify voice agent active
  4. Failure dump       — UI hierarchy + all visible elements on any failure
  5. Report             — logs/debug_<timestamp>.txt with full findings

Usage:
  python debug_navigation.py
  python debug_navigation.py --keep-open   # don't quit Appium at the end
  python debug_navigation.py --no-logcat   # skip ADB logcat capture
"""

import argparse
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

CONFIG_PATH = "config/appium_config.yaml"
LOG_DIR = Path("logs")
SCREENSHOT_DIR = Path(tempfile.gettempdir()) / "screenshots" / "debug"

# ADB logcat patterns that indicate a problem (case-insensitive)
CRASH_PATTERNS = [
    "FATAL EXCEPTION",
    "ANR in",
    "Force finishing activity",
    "java.lang.RuntimeException",
    "java.lang.NullPointerException",
    "java.lang.IllegalStateException",
    "android.os.NetworkOnMainThreadException",
    "W/ActivityManager",
    "E/AndroidRuntime",
    "Process: com.acmepizza",
]

# Keywords confirming voice agent is ready
AGENT_READY_KEYWORDS = [
    "how can i help",
    "what can i get",
    "ready",
    "take your time",
    "voice ordering",
    "hi, how",
    "hello",
]


# ─────────────────────────────────────────────────────────────────────────────
# Logger — writes to stdout AND a file simultaneously
# ─────────────────────────────────────────────────────────────────────────────

class DebugLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(log_path, "w", encoding="utf-8")
        self.step_results: list[dict] = []

    def log(self, msg: str = ""):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {msg}"
        print(line)
        self._fh.write(line + "\n")
        self._fh.flush()

    def section(self, title: str):
        sep = "=" * 60
        self.log()
        self.log(sep)
        self.log(f"  {title}")
        self.log(sep)

    def record_step(self, name: str, status: str, detail: str = "", elapsed: float = 0.0):
        self.step_results.append({
            "name": name,
            "status": status,
            "detail": detail,
            "elapsed": elapsed,
        })
        icon = "PASS" if status == "pass" else ("SKIP" if status == "skip" else "FAIL")
        self.log(f"  [{icon}] {name}  ({elapsed:.1f}s)  {detail}")

    def close(self):
        self._fh.close()


# ─────────────────────────────────────────────────────────────────────────────
# ADB logcat capture — background thread
# ─────────────────────────────────────────────────────────────────────────────

class LogcatCapture:
    """Runs `adb logcat` in a background thread and stores matching lines."""

    def __init__(self, app_package: str, log: DebugLogger):
        self.app_package = app_package
        self.log = log
        self._q: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.captured_lines: list[str] = []
        self.error_lines: list[str] = []

    def start(self):
        # Clear existing logcat buffer so we only see fresh lines
        try:
            subprocess.run(["adb", "logcat", "-c"], capture_output=True, timeout=5)
        except Exception as e:
            self.log.log(f"  [logcat] Could not clear buffer: {e}")

        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        self.log.log("  [logcat] Background capture started")

    def _reader(self):
        try:
            proc = subprocess.Popen(
                ["adb", "logcat", "-v", "time"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            for raw_line in proc.stdout:
                if self._stop.is_set():
                    proc.terminate()
                    break
                line = raw_line.rstrip()
                # Capture any line that mentions our app package
                if self.app_package in line or any(
                    p.lower() in line.lower() for p in CRASH_PATTERNS
                ):
                    self.captured_lines.append(line)
                    if any(p.lower() in line.lower() for p in CRASH_PATTERNS):
                        self.error_lines.append(line)
        except Exception as e:
            self.log.log(f"  [logcat] Reader thread error: {e}")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.log.log(
            f"  [logcat] Stopped. Captured {len(self.captured_lines)} app lines, "
            f"{len(self.error_lines)} error lines."
        )

    def dump_errors(self, log: DebugLogger):
        if not self.error_lines:
            log.log("  [logcat] No crash/error lines detected.")
            return
        log.log(f"  [logcat] *** {len(self.error_lines)} ERROR LINE(S) DETECTED ***")
        for line in self.error_lines[-30:]:   # last 30 error lines
            log.log(f"    {line}")

    def dump_recent(self, log: DebugLogger, n: int = 20):
        """Dump the last N captured app lines — useful for context around failures."""
        recent = self.captured_lines[-n:]
        if not recent:
            log.log("  [logcat] No recent app log lines captured.")
            return
        log.log(f"  [logcat] Last {len(recent)} app log lines:")
        for line in recent:
            log.log(f"    {line}")


# ─────────────────────────────────────────────────────────────────────────────
# Pre-flight checks
# ─────────────────────────────────────────────────────────────────────────────

def check_adb_device(log: DebugLogger) -> tuple[bool, str]:
    """Returns (ok, device_serial)."""
    try:
        result = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=10
        )
        lines = [l for l in result.stdout.splitlines()
                 if l.strip() and not l.startswith("List")]
        devices = [l for l in lines if "device" in l and "offline" not in l]
        if not devices:
            return False, "No ADB device connected (or device is offline/unauthorized)"
        serial = devices[0].split()[0]
        return True, serial
    except FileNotFoundError:
        return False, "adb not found in PATH"
    except Exception as e:
        return False, str(e)


def check_appium_server(server_url: str, log: DebugLogger) -> tuple[bool, str]:
    """Returns (ok, message)."""
    try:
        resp = requests.get(f"{server_url}/status", timeout=5)
        data = resp.json()
        ready = data.get("value", {}).get("ready", False)
        msg = data.get("value", {}).get("message", "")
        if resp.status_code == 200:
            return True, f"ready={ready}, message={msg}"
        return False, f"HTTP {resp.status_code}"
    except requests.ConnectionError:
        return False, f"Cannot reach {server_url} — is Appium running?"
    except Exception as e:
        return False, str(e)


def check_ollama(base_url: str, model: str, log: DebugLogger) -> tuple[bool, str]:
    """Returns (ok, message)."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        if model in models or any(model in m for m in models):
            return True, f"Model '{model}' available"
        return False, (
            f"Model '{model}' NOT found. Available: {models[:5]}"
            if models else "No models listed"
        )
    except requests.ConnectionError:
        return False, f"Cannot reach {base_url} — is Ollama running?"
    except Exception as e:
        return False, str(e)


def check_app_installed(app_package: str, log: DebugLogger) -> tuple[bool, str]:
    """Returns (ok, message)."""
    try:
        result = subprocess.run(
            ["adb", "shell", "pm", "list", "packages", app_package],
            capture_output=True, text=True, timeout=10
        )
        if app_package in result.stdout:
            return True, f"'{app_package}' is installed"
        return False, f"'{app_package}' is NOT installed on the device"
    except Exception as e:
        return False, str(e)


def check_app_permissions(app_package: str, log: DebugLogger) -> list[str]:
    """Return list of missing/denied runtime permissions."""
    try:
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "package", app_package],
            capture_output=True, text=True, timeout=15
        )
        denied = []
        for line in result.stdout.splitlines():
            if "RECORD_AUDIO" in line and "denied" in line.lower():
                denied.append("RECORD_AUDIO permission denied")
            if "permission" in line.lower() and "denied" in line.lower():
                denied.append(line.strip())
        return denied[:5]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Navigation helpers
# ─────────────────────────────────────────────────────────────────────────────

def dump_ui_elements(driver, log: DebugLogger, label: str = ""):
    """Dump all visible UI elements — called on navigation failures."""
    log.log(f"\n  --- UI DUMP{': ' + label if label else ''} ---")
    try:
        from appium.webdriver.common.appiumby import AppiumBy
        driver.driver.implicitly_wait(0)
        try:
            elems = driver.driver.find_elements(AppiumBy.XPATH, "//*[@clickable='true']")
            log.log(f"  Clickable elements ({len(elems)}):")
            for el in elems[:20]:
                text  = el.get_attribute("text") or ""
                desc  = el.get_attribute("content-desc") or ""
                rid   = el.get_attribute("resource-id") or ""
                cls   = el.get_attribute("class") or ""
                label_str = text or desc or rid or cls
                log.log(f"    [{cls.split('.')[-1]}]  text='{text}'  desc='{desc}'  id='{rid}'")
        finally:
            driver.driver.implicitly_wait(10)
    except Exception as e:
        log.log(f"  UI dump failed: {e}")

    try:
        from appium.webdriver.common.appiumby import AppiumBy
        driver.driver.implicitly_wait(0)
        try:
            all_texts = []
            for xpath, attr in [("//*[@text != '']", "text"),
                                 ("//*[@content-desc != '']", "content-desc")]:
                for el in driver.driver.find_elements(AppiumBy.XPATH, xpath):
                    val = el.get_attribute(attr)
                    if val and val.strip():
                        all_texts.append(val.strip())
        finally:
            driver.driver.implicitly_wait(10)
        log.log(f"  All visible text ({len(all_texts)} items): {all_texts[:30]}")
    except Exception as e:
        log.log(f"  Visible text dump failed: {e}")


def get_current_activity(driver) -> str:
    try:
        return f"{driver.driver.current_package}/{driver.driver.current_activity}"
    except Exception:
        return "unknown"


def take_debug_screenshot(driver, name: str, log: DebugLogger) -> str | None:
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = str(SCREENSHOT_DIR / f"{name}.png")
        driver.driver.save_screenshot(path)
        log.log(f"  Screenshot: {path}")
        return path
    except Exception as e:
        log.log(f"  Screenshot failed ({name}): {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Navigation steps
# ─────────────────────────────────────────────────────────────────────────────

def step1_launch_app(driver, config: dict, log: DebugLogger) -> bool:
    log.section("Step 1: Launch Application")
    t0 = time.time()
    app_package = config["capabilities"]["appPackage"]
    app_activity = config["capabilities"]["appActivity"]
    try:
        driver.driver.activate_app(app_package)
        time.sleep(3)
        activity = get_current_activity(driver)
        log.log(f"  Current activity: {activity}")
        take_debug_screenshot(driver, "step1_launched", log)

        ok = app_package in activity
        detail = f"activity={activity}"
        if not ok:
            log.log(f"  WARN: Expected package '{app_package}', got '{activity}'")
            dump_ui_elements(driver, log, "after launch")
        log.record_step("Launch App", "pass" if ok else "fail", detail, time.time() - t0)
        return ok
    except Exception as e:
        log.log(f"  ERROR: {e}")
        log.record_step("Launch App", "fail", str(e), time.time() - t0)
        return False


def step2_scroll_to_voice_order(driver, log: DebugLogger):
    """Returns the found element or None."""
    log.section("Step 2: Scroll to 'Start Voice Order'")
    t0 = time.time()

    from appium.webdriver.common.appiumby import AppiumBy
    from src.appium_driver import AppiumDriver

    uia_strategies = [
        (
            "descriptionContains",
            "new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView("
            'new UiSelector().descriptionContains("voice order"))',
        ),
        (
            "textContains",
            "new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView("
            'new UiSelector().textContains("voice order"))',
        ),
        (
            "descriptionContains(Start)",
            "new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView("
            'new UiSelector().descriptionContains("Start"))',
        ),
    ]

    for strategy_name, uia in uia_strategies:
        log.log(f"  Trying UiScrollable strategy: {strategy_name}")
        element = driver.find_element_safe(AppiumBy.ANDROID_UIAUTOMATOR, uia, timeout=10)
        if element:
            log.log(f"  Found element via: {strategy_name}")
            take_debug_screenshot(driver, "step2_voice_order_visible", log)
            log.record_step("Scroll to Voice Order", "pass",
                            f"strategy={strategy_name}", time.time() - t0)
            return element

    # Not found — dump UI for diagnosis
    log.log("  'Start Voice Order' not found with any strategy")
    log.log(f"  Current activity: {get_current_activity(driver)}")
    dump_ui_elements(driver, log, "voice order not found")
    take_debug_screenshot(driver, "step2_not_found", log)

    # Extra: check if we're on the right screen at all
    try:
        driver.driver.implicitly_wait(0)
        try:
            elems = driver.driver.find_elements(AppiumBy.XPATH,
                                                "//*[@text != '' or @content-desc != '']")
            texts = []
            for el in elems:
                for attr in ("text", "content-desc"):
                    val = el.get_attribute(attr)
                    if val and val.strip():
                        texts.append(val.strip())
            log.log(f"  All visible text: {texts[:20]}")
        finally:
            driver.driver.implicitly_wait(10)
    except Exception as e:
        log.log(f"  Could not read screen text: {e}")

    log.record_step("Scroll to Voice Order", "fail",
                    "Button not found — see UI dump above", time.time() - t0)
    return None


def step3_click_voice_order(driver, element, log: DebugLogger) -> bool:
    log.section("Step 3: Click 'Start Voice Order'")
    t0 = time.time()
    try:
        element.click()
        time.sleep(3)
        activity = get_current_activity(driver)
        log.log(f"  Activity after click: {activity}")
        take_debug_screenshot(driver, "step3_after_click", log)
        log.record_step("Click Voice Order", "pass", f"activity={activity}", time.time() - t0)
        return True
    except Exception as e:
        log.log(f"  ERROR clicking element: {e}")
        take_debug_screenshot(driver, "step3_click_error", log)
        log.record_step("Click Voice Order", "fail", str(e), time.time() - t0)
        return False


def step4_wait_for_voice_ordering_screen(driver, log: DebugLogger) -> bool:
    log.section("Step 4: Wait for VOICE ORDERING Screen")
    t0 = time.time()

    from appium.webdriver.common.appiumby import AppiumBy

    timeout = 12
    elapsed = 0
    found = False

    while elapsed < timeout:
        driver.driver.implicitly_wait(0)
        try:
            elems = driver.driver.find_elements(
                AppiumBy.XPATH, "//*[@text != '' or @content-desc != '']"
            )
            texts = []
            for el in elems:
                for attr in ("text", "content-desc"):
                    val = el.get_attribute(attr)
                    if val and val.strip():
                        texts.append(val.strip().lower())
            if any("voice ordering" in t for t in texts):
                found = True
                log.log(f"  VOICE ORDERING screen detected at {elapsed}s")
                log.log(f"  All text: {texts[:15]}")
                break
        except Exception:
            pass
        finally:
            driver.driver.implicitly_wait(10)

        time.sleep(1)
        elapsed += 1
        log.log(f"  Waiting... ({elapsed}s/{timeout}s)  activity={get_current_activity(driver)}")

    take_debug_screenshot(driver, "step4_voice_ordering_screen", log)

    if not found:
        log.log("  VOICE ORDERING screen not detected within timeout")
        dump_ui_elements(driver, log, "timeout waiting for voice ordering screen")

    log.record_step("Voice Ordering Screen", "pass" if found else "fail",
                    f"detected_in={elapsed}s" if found else "timeout", time.time() - t0)
    return found


def step5_mic_permission(driver, log: DebugLogger) -> str:
    """Returns 'granted', 'not_shown', or 'failed'."""
    log.section("Step 5: Microphone Permission")
    t0 = time.time()

    from appium.webdriver.common.appiumby import AppiumBy

    locators = [
        (AppiumBy.XPATH, '//*[@text="While using the app"]'),
        (AppiumBy.XPATH, '//*[@text="Only this time"]'),
        (AppiumBy.XPATH, '//*[contains(@text, "While using")]'),
        (AppiumBy.XPATH, '//*[contains(@text, "Allow")]'),
    ]

    driver.driver.implicitly_wait(0)
    element = None
    try:
        for by, value in locators:
            element = driver.find_element_safe(by, value, timeout=2)
            if element:
                log.log(f"  Permission dialog found — tapping: '{value}'")
                break
    finally:
        driver.driver.implicitly_wait(10)

    if element:
        try:
            element.click()
            time.sleep(1)
            take_debug_screenshot(driver, "step5_permission_granted", log)
            log.record_step("Mic Permission", "pass", "granted", time.time() - t0)
            return "granted"
        except Exception as e:
            log.log(f"  Error tapping permission button: {e}")
            log.record_step("Mic Permission", "fail", str(e), time.time() - t0)
            return "failed"
    else:
        log.log("  No permission dialog — already granted or not triggered yet")
        log.record_step("Mic Permission", "skip", "no dialog shown", time.time() - t0)
        return "not_shown"


def step6_verify_agent_active(driver, log: DebugLogger) -> bool:
    log.section("Step 6: Verify Voice Agent Active")
    t0 = time.time()

    from appium.webdriver.common.appiumby import AppiumBy

    timeout = 15
    elapsed = 0
    matched_keywords = []

    while elapsed < timeout:
        texts = []
        driver.driver.implicitly_wait(0)
        try:
            elems = driver.driver.find_elements(
                AppiumBy.XPATH, "//*[@text != '' or @content-desc != '']"
            )
            for el in elems:
                for attr in ("text", "content-desc"):
                    val = el.get_attribute(attr)
                    if val and val.strip():
                        texts.append(val.strip())
        except Exception:
            pass
        finally:
            driver.driver.implicitly_wait(10)

        combined = " ".join(texts).lower()
        matched_keywords = [kw for kw in AGENT_READY_KEYWORDS if kw in combined]
        if matched_keywords:
            log.log(f"  Agent ready at {elapsed}s — matched: {matched_keywords}")
            log.log(f"  Full visible text: {texts[:15]}")
            break

        time.sleep(1)
        elapsed += 1
        log.log(f"  Waiting for agent greeting... ({elapsed}s/{timeout}s)")

    take_debug_screenshot(driver, "step6_agent_state", log)

    if not matched_keywords:
        log.log("  Agent greeting not detected within timeout")
        dump_ui_elements(driver, log, "agent not active")

    log.record_step("Voice Agent Active", "pass" if matched_keywords else "fail",
                    f"keywords={matched_keywords}" if matched_keywords else "timeout",
                    time.time() - t0)
    return bool(matched_keywords)


# ─────────────────────────────────────────────────────────────────────────────
# Final report
# ─────────────────────────────────────────────────────────────────────────────

def write_summary(log: DebugLogger, logcat: LogcatCapture | None,
                  preflight: dict, total_elapsed: float):
    log.section("SUMMARY")

    # Pre-flight
    log.log("  Pre-flight checks:")
    for check, (ok, msg) in preflight.items():
        icon = "PASS" if ok else "FAIL"
        log.log(f"    [{icon}] {check}: {msg}")

    # Navigation steps
    log.log("\n  Navigation steps:")
    for s in log.step_results:
        icon = "PASS" if s["status"] == "pass" else ("SKIP" if s["status"] == "skip" else "FAIL")
        log.log(f"    [{icon}] {s['name']:35s}  {s['elapsed']:5.1f}s  {s['detail']}")

    # ADB errors
    log.log("")
    if logcat:
        logcat.dump_errors(log)

    # Recommendations
    log.log("\n  Recommendations:")
    failures = [s for s in log.step_results if s["status"] == "fail"]
    if not failures and all(ok for ok, _ in preflight.values()):
        log.log("    All checks passed — no obvious navigation issues detected.")
    else:
        for s in failures:
            name = s["name"]
            if "Launch" in name:
                log.log("    - App failed to launch. Check device connection and app install.")
            elif "Scroll" in name:
                log.log("    - 'Start Voice Order' not found. App may be on wrong screen,")
                log.log("      or the home screen banner hasn't loaded. Run navigate_to_home()")
                log.log("      before scrolling and allow 3-4s for the banner.")
            elif "Click" in name:
                log.log("    - Click on voice order button failed. Element may have moved.")
            elif "Voice Ordering Screen" in name:
                log.log("    - VOICE ORDERING screen didn't appear. Possible navigation bug")
                log.log("      or the app is showing an error/dialog blocking the transition.")
            elif "Agent" in name:
                log.log("    - Voice agent not responding. Check network connectivity,")
                log.log("      voice service backend, and app logcat for connection errors.")
        for check, (ok, msg) in preflight.items():
            if not ok:
                log.log(f"    - Pre-flight failed [{check}]: {msg}")

    log.log(f"\n  Total elapsed: {total_elapsed:.1f}s")
    log.log(f"  Log saved to: {log.log_path}")
    log.log(f"  Screenshots: {SCREENSHOT_DIR}/")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Navigation debug script")
    parser.add_argument("--keep-open", action="store_true",
                        help="Don't stop the Appium session at the end")
    parser.add_argument("--no-logcat", action="store_true",
                        help="Skip ADB logcat capture")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"debug_{ts}.txt"
    log = DebugLogger(log_path)
    t_start = time.time()

    log.section("PIZZA VOICE — NAVIGATION DEBUG")
    log.log(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.log(f"  Log: {log_path}")

    # ── Load config ────────────────────────────────────────────────────────
    try:
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        log.log(f"  Config loaded: {CONFIG_PATH}")
    except Exception as e:
        log.log(f"  ERROR: Could not load config: {e}")
        log.close()
        sys.exit(1)

    app_package  = config["capabilities"]["appPackage"]
    appium_url   = config["appium"]["server_url"]
    ollama_url   = config["ollama"]["base_url"]
    ollama_model = config["ollama"]["model"]

    # ── Pre-flight checks ──────────────────────────────────────────────────
    log.section("PRE-FLIGHT CHECKS")
    preflight: dict[str, tuple[bool, str]] = {}

    ok, msg = check_adb_device(log)
    preflight["ADB device"] = (ok, msg)
    log.log(f"  {'[PASS]' if ok else '[FAIL]'} ADB device: {msg}")

    ok, msg = check_appium_server(appium_url, log)
    preflight["Appium server"] = (ok, msg)
    log.log(f"  {'[PASS]' if ok else '[FAIL]'} Appium ({appium_url}): {msg}")

    ok, msg = check_ollama(ollama_url, ollama_model, log)
    preflight["Ollama"] = (ok, msg)
    log.log(f"  {'[PASS]' if ok else '[FAIL]'} Ollama ({ollama_model}): {msg}")

    if preflight["ADB device"][0]:
        ok, msg = check_app_installed(app_package, log)
        preflight["App installed"] = (ok, msg)
        log.log(f"  {'[PASS]' if ok else '[FAIL]'} App installed: {msg}")

        denied_perms = check_app_permissions(app_package, log)
        if denied_perms:
            log.log(f"  [WARN] Denied permissions: {denied_perms}")
        else:
            log.log("  [PASS] No obvious denied permissions found")

    # Abort if Appium or device is missing — nothing else can run
    if not preflight.get("Appium server", (False, ""))[0]:
        log.log("\n  ABORT: Appium server not reachable. Start Appium and retry.")
        write_summary(log, None, preflight, time.time() - t_start)
        log.close()
        sys.exit(1)

    if not preflight.get("ADB device", (False, ""))[0]:
        log.log("\n  ABORT: No ADB device. Connect device with USB debugging enabled.")
        write_summary(log, None, preflight, time.time() - t_start)
        log.close()
        sys.exit(1)

    # ── ADB logcat ─────────────────────────────────────────────────────────
    logcat: LogcatCapture | None = None
    if not args.no_logcat:
        logcat = LogcatCapture(app_package, log)
        logcat.start()

    # ── Start Appium driver ────────────────────────────────────────────────
    log.section("CONNECTING TO APPIUM")
    from src.appium_driver import AppiumDriver

    driver = None
    try:
        driver = AppiumDriver(CONFIG_PATH)
        driver.start()
        log.log(f"  Appium session started")
        log.log(f"  Device: {driver.driver.capabilities.get('deviceName', 'unknown')}")
        log.log(f"  Platform: {driver.driver.capabilities.get('platformVersion', 'unknown')}")
    except Exception as e:
        log.log(f"  ERROR starting Appium session: {e}")
        if logcat:
            logcat.stop()
            logcat.dump_errors(log)
        write_summary(log, logcat, preflight, time.time() - t_start)
        log.close()
        sys.exit(1)

    # ── Navigation steps ───────────────────────────────────────────────────
    try:
        ok1 = step1_launch_app(driver, config, log)

        if ok1:
            elem = step2_scroll_to_voice_order(driver, log)
        else:
            log.log("  Skipping remaining steps — app launch failed")
            elem = None

        if elem:
            ok3 = step3_click_voice_order(driver, elem, log)
        else:
            if ok1:
                pass  # already recorded as fail in step2
            ok3 = False

        if ok3:
            ok4 = step4_wait_for_voice_ordering_screen(driver, log)
            step5_mic_permission(driver, log)
            step6_verify_agent_active(driver, log)
        else:
            log.log("  Skipping steps 4-6 — navigation did not reach voice ordering screen")

    except KeyboardInterrupt:
        log.log("\n  Interrupted by user")
    except Exception as e:
        log.log(f"\n  Unexpected error during navigation: {e}")
        import traceback
        log.log(traceback.format_exc())
        take_debug_screenshot(driver, "error_state", log)
        dump_ui_elements(driver, log, "unexpected error")
    finally:
        # Dump recent logcat around any errors before stopping
        if logcat:
            logcat.stop()
            if logcat.error_lines:
                log.log("\n  ADB errors detected during run:")
                logcat.dump_recent(log, n=30)

        write_summary(log, logcat, preflight, time.time() - t_start)

        if not args.keep_open and driver:
            driver.stop()
            log.log("\n  Appium session closed.")
        elif args.keep_open:
            log.log("\n  --keep-open: Appium session left running.")

        log.close()
        print(f"\nDebug log: {log_path}")


if __name__ == "__main__":
    main()
