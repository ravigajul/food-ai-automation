#!/usr/bin/env python3
"""
Standalone test: Legal Consent Dialog Verification

Setup flow (automated):
  Home → Profile tab → General → AI Agent (Ava) Permissions
  → toggle OFF 'Allow AI assistance' → restart app → Start Voice Order

Then verifies the consent dialog text.

Expected to FAIL until 'Privacy Police' is corrected to 'Privacy Notice'.

Usage:
  python test_consent_dialog.py
"""

import sys
import time
from appium.webdriver.common.appiumby import AppiumBy
from src.appium_driver import AppiumDriver
from launch_and_invoke_voice import (
    launch_app,
    scroll_to_start_voice_order,
    click_start_voice_order,
)

# ── Expected values ────────────────────────────────────────────────────────────

EXPECTED_HEADING    = "do you accept the terms and conditions"
EXPECTED_LINK_TEXT  = "privacy notice"    # correct text
WRONG_LINK_TEXT     = "privacy police"    # current bug
BUTTON_ACCEPT       = "i accept"
BUTTON_DECLINE      = "i do not"

DIALOG_POLL_TIMEOUT = 8   # seconds to wait for dialog to appear


# ── Helpers ────────────────────────────────────────────────────────────────────

def _read_screen_texts(driver: AppiumDriver) -> list[str]:
    """Return all non-empty text/content-desc strings visible on screen."""
    driver.driver.implicitly_wait(0)
    try:
        elements = driver.driver.find_elements(
            AppiumBy.XPATH, "//*[@text != '' or @content-desc != '']"
        )
        texts = []
        for el in elements:
            for attr in ("text", "content-desc"):
                val = el.get_attribute(attr)
                if val and val.strip():
                    texts.append(val.strip())
        return texts
    except Exception:
        return []
    finally:
        driver.driver.implicitly_wait(10)


def _tap(driver: AppiumDriver, label: str) -> bool:
    """Tap an element by text or content-desc. Returns True if found."""
    locators = [
        (AppiumBy.XPATH, f"//*[@text='{label}']"),
        (AppiumBy.XPATH, f"//*[contains(@text,'{label}')]"),
        (AppiumBy.XPATH, f"//*[@content-desc='{label}']"),
        (AppiumBy.XPATH, f"//*[contains(@content-desc,'{label}')]"),
    ]
    driver.driver.implicitly_wait(0)
    try:
        for by, value in locators:
            els = driver.driver.find_elements(by, value)
            if els:
                els[0].click()
                time.sleep(1)
                return True
    finally:
        driver.driver.implicitly_wait(10)
    return False


# ── Reset consent via app settings ────────────────────────────────────────────

def reset_ai_consent(driver: AppiumDriver) -> None:
    """
    Navigate to Profile → General → AI Agent (Ava) Permissions and toggle
    'Allow AI assistance' OFF.  Then restart the app so the consent dialog
    appears again on the next 'Start Voice Order' tap.

    Navigation path (from screenshots):
      Bottom nav: Profile
        → General
          → AI Agent (Ava) Permissions
            → toggle OFF 'Allow AI assistance'
      Restart app, return to Home.
    """
    print("\n── Setup: reset AI consent via app settings ──")
    app_package = driver.config["capabilities"]["appPackage"]

    # 1. Profile tab
    if not _tap(driver, "Profile"):
        raise RuntimeError("Could not tap Profile tab")
    print("  Tapped Profile tab")
    time.sleep(1)

    # 2. General
    if not _tap(driver, "General"):
        raise RuntimeError("Could not tap General")
    print("  Tapped General")
    time.sleep(1)

    # 3. AI Agent (Ava) Permissions
    if not _tap(driver, "AI Agent (Ava) Permissions"):
        raise RuntimeError("Could not tap 'AI Agent (Ava) Permissions'")
    print("  Tapped AI Agent (Ava) Permissions")
    time.sleep(1)

    # 4. Find the toggle and turn it OFF if currently ON
    driver.driver.implicitly_wait(0)
    try:
        # Android Switch widget exposes @checked="true"/"false"
        switches = driver.driver.find_elements(
            AppiumBy.XPATH, "//android.widget.Switch"
        )
        if not switches:
            # Some builds use ToggleButton or a custom view with @checkable
            switches = driver.driver.find_elements(
                AppiumBy.XPATH, "//*[@checkable='true']"
            )

        if not switches:
            raise RuntimeError("Could not find 'Allow AI assistance' toggle")

        toggle = switches[0]
        is_on  = toggle.get_attribute("checked") == "true"
        if is_on:
            toggle.click()
            time.sleep(1)
            print("  Toggled 'Allow AI assistance' OFF")
        else:
            print("  'Allow AI assistance' already OFF — no change needed")
    finally:
        driver.driver.implicitly_wait(10)

    driver.take_screenshot("consent_reset_toggle_off")

    # 5. Restart the app so consent state is re-evaluated on next launch
    print("  Restarting app...")
    driver.driver.terminate_app(app_package)
    time.sleep(2)
    driver.driver.activate_app(app_package)
    time.sleep(3)
    print("  App restarted")


# ── Core verification ──────────────────────────────────────────────────────────

def verify_consent_dialog(driver: AppiumDriver) -> tuple[bool, list[str]]:
    """
    Wait for the consent dialog, run assertions, dismiss with 'I Accept'.

    Returns:
        (overall_passed, failure_messages)
    """
    dialog_texts: list[str] = []
    for elapsed in range(DIALOG_POLL_TIMEOUT + 1):
        texts = _read_screen_texts(driver)
        if EXPECTED_HEADING in " ".join(texts).lower():
            dialog_texts = texts
            print(f"  Consent dialog detected ({elapsed}s)")
            break
        if elapsed < DIALOG_POLL_TIMEOUT:
            time.sleep(1)
            print(f"  Waiting for consent dialog... ({elapsed + 1}s)")

    driver.take_screenshot("consent_dialog")

    if not dialog_texts:
        return False, ["Consent dialog did not appear after setup — check reset_ai_consent()"]

    combined = " ".join(dialog_texts).lower()
    failures: list[str] = []

    # 1. Heading present
    if EXPECTED_HEADING not in combined:
        failures.append(f"Heading missing — expected '{EXPECTED_HEADING.upper()}'")

    # 2. Link text — "Privacy Police" is the bug; expected "Privacy Notice"
    if WRONG_LINK_TEXT in combined:
        failures.append("Link text is 'Privacy Police' — expected 'Privacy Notice'")
    elif EXPECTED_LINK_TEXT not in combined:
        failures.append("Link text not found — expected 'Privacy Notice'")

    # 3. Action buttons
    if BUTTON_ACCEPT not in combined:
        failures.append("Button 'I Accept' not found")
    if BUTTON_DECLINE not in combined:
        failures.append("Button 'I do Not' not found")

    # Dismiss with I Accept so the app is left in a usable state
    if not _tap(driver, "I Accept"):
        print("  Warning: could not tap 'I Accept' — dialog may have auto-dismissed")

    return len(failures) == 0, failures


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> int:
    driver = None
    try:
        driver = launch_app()

        # Reset consent state via Profile → General → AI Agent (Ava) Permissions
        reset_ai_consent(driver)

        # Navigate back to home and find the voice order button
        element = scroll_to_start_voice_order(driver)
        if not element:
            print("\n❌ 'Start Voice Order' button not found after reset")
            return 1

        click_start_voice_order(driver, element)

        passed, failures = verify_consent_dialog(driver)

        print(f"\n{'=' * 50}")
        if passed:
            print("✅  PASSED — consent dialog text is correct")
        else:
            print("❌  FAILED — consent dialog has issues:")
            for msg in failures:
                print(f"      • {msg}")
        print(f"{'=' * 50}\n")

        return 0 if passed else 1

    except KeyboardInterrupt:
        print("\nInterrupted")
        return 1
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
