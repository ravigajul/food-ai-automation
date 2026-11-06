#!/usr/bin/env python3
"""
Step-by-step Appium script: Navigate to and invoke the Voice Agent
Step 1: Launch the application
Step 2: Scroll until 'Start Voice Order' is visible
Step 3: Click 'Start Voice Order'
Step 4: Wait for voice agent to initialize (no arrow tap — agent starts directly)
Step 5: Grant microphone permission (optional)
Step 6: Verify voice agent is active (keywords: 'ready', 'how can i help')
"""

from appium.webdriver.common.appiumby import AppiumBy
from src.appium_driver import AppiumDriver
import json
import os
import subprocess
import time
from datetime import datetime, timedelta


def launch_app(config_path: str = "config/appium_config.yaml") -> AppiumDriver:
    print(f"\n{'='*50}")
    print("Step 1: Launch Application")
    print(f"{'='*50}")

    driver = AppiumDriver(config_path)
    driver.start()

    # Explicitly launch the app (in case it's closed)
    app_package = driver.config['capabilities']['appPackage']
    print(f"  Launching {app_package}...")
    driver.driver.activate_app(app_package)

    time.sleep(3)  # Wait for app to fully load

    activity = driver.driver.current_activity
    print(f"  Current activity: {activity}")
    driver.take_screenshot("step1_app_launched")
    print("  Screenshot saved: step1_app_launched")

    return driver


def scroll_to_start_voice_order(driver: AppiumDriver):
    print(f"\n{'='*50}")
    print("Step 2: Scroll to 'Start Voice Order'")
    print(f"{'='*50}")

    # UiScrollable instructs Android to scroll the scrollable container until
    # the matching element is visible — no manual swipe coordinates needed
    uia_strategies = [
        "new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView("
        'new UiSelector().descriptionContains("voice order"))',
        "new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView("
        'new UiSelector().textContains("voice order"))',
    ]

    for uia in uia_strategies:
        element = driver.find_element_safe(
            AppiumBy.ANDROID_UIAUTOMATOR, uia, timeout=10
        )
        if element:
            print("  Found 'Start voice order' via UiScrollable")
            driver.take_screenshot("step2_start_voice_order_visible")
            return element

    print("  'Start voice order' not found")
    return None


def click_start_voice_order(driver: AppiumDriver, element):
    print(f"\n{'='*50}")
    print("Step 3: Click 'Start Voice Order'")
    print(f"{'='*50}")

    element.click()
    # Short pause so the navigation animation starts before we poll.
    # click_arrow_on_ready_screen polls for the VOICE ORDERING title,
    # so a long fixed sleep here is unnecessary and wastes the greeting window.
    time.sleep(0.5)

    activity = driver.driver.current_activity
    print(f"  Current activity: {activity}")
    driver.take_screenshot("step3_voice_agent_launched")
    print("  Screenshot saved: step3_voice_agent_launched")


def click_arrow_on_ready_screen(driver: AppiumDriver) -> list:
    """
    Wait for the VOICE ORDERING screen to appear and return the screen texts
    captured at that moment.

    Returning the texts lets the caller (run_suite.py) pass them directly to
    verify_ai_disclaimer so no additional scrape is needed — the disclaimer
    check becomes instant, not a blocking retry loop.

    Returns:
        list of strings scraped from the screen when VOICE ORDERING was
        detected (original case), or an empty list if not detected.
    """
    print(f"\n{'='*50}")
    print("Step 4: Wait for 'VOICE ORDERING' screen")
    print(f"{'='*50}")

    # After clicking 'Start Voice Order' the app navigates directly to the
    # 'VOICE ORDERING' screen (green orb, no intermediate ready/arrow screen).
    # Poll until the title is visible rather than relying on a fixed sleep.
    timeout = 10
    poll_interval = 1
    elapsed = 0
    found = False
    detected_texts = []

    # ── Phase 1: wait for the VOICE ORDERING title ───────────────────────────
    while elapsed < timeout:
        driver.driver.implicitly_wait(0)
        try:
            elements = driver.driver.find_elements(
                AppiumBy.XPATH, "//*[@text != '' or @content-desc != '']"
            )
            raw_texts = []
            for el in elements:
                for attr in ("text", "content-desc"):
                    val = el.get_attribute(attr)
                    if val and val.strip():
                        raw_texts.append(val.strip())
            if any("voice ordering" in t.lower() for t in raw_texts):
                found = True
                detected_texts = raw_texts
                print("  'VOICE ORDERING' screen detected")
                break
        except Exception:
            pass
        finally:
            driver.driver.implicitly_wait(10)

        time.sleep(poll_interval)
        elapsed += poll_interval
        print(f"  Waiting for VOICE ORDERING screen... ({elapsed}s)")

    if not found:
        print("  VOICE ORDERING screen not confirmed — proceeding anyway")

    # ── Phase 2: wait for the loading indicator to disappear ─────────────────
    # The app shows "AI PIZZA ASSISTANT IS LOADING" before the disclaimer and
    # the voice agent are ready.  The disclaimer (and Ava's greeting) only
    # appear once loading is complete, so we must wait here — not in
    # verify_ai_disclaimer — to avoid burning the greeting window.
    def _is_loading(texts):
        combined = " ".join(texts).lower()
        return "loading" in combined

    if detected_texts and _is_loading(detected_texts):
        print("  ⏳ Loading indicator visible — waiting for it to clear...")
        load_timeout = 20
        load_elapsed = 0
        while load_elapsed < load_timeout:
            time.sleep(1)
            load_elapsed += 1
            driver.driver.implicitly_wait(0)
            try:
                elements = driver.driver.find_elements(
                    AppiumBy.XPATH, "//*[@text != '' or @content-desc != '']"
                )
                fresh = []
                for el in elements:
                    for attr in ("text", "content-desc"):
                        val = el.get_attribute(attr)
                        if val and val.strip():
                            fresh.append(val.strip())
            except Exception:
                fresh = detected_texts
            finally:
                driver.driver.implicitly_wait(10)

            if not _is_loading(fresh):
                detected_texts = fresh
                print(f"  ✅ Loading complete after {load_elapsed}s — disclaimer should now be visible")
                break
            print(f"  Still loading... ({load_elapsed}s)")
        else:
            print("  ⚠️  Loading indicator still present after timeout — proceeding anyway")

    # Screenshot intentionally skipped here — this is the last step before
    # run_ai_customer_conversation opens the mic.  Any Appium call (screenshot,
    # current_activity) burns ~0.5–1 s of Ava's opening greeting.
    return detected_texts


def grant_microphone_permission(driver: AppiumDriver):
    print(f"\n{'='*50}")
    print("Step 5: Grant microphone permission (if shown)")
    print(f"{'='*50}")

    # Only act if the permission dialog is currently on screen — otherwise skip.
    # implicitly_wait(0) ensures this check is instant with no waiting.
    locators = [
        (AppiumBy.XPATH, '//*[@text="While using the app"]'),
        (AppiumBy.XPATH, '//*[@text="Only this time"]'),
        (AppiumBy.XPATH, '//*[contains(@text, "While using")]'),
    ]

    driver.driver.implicitly_wait(0)
    element = None
    try:
        for by, value in locators:
            element = driver.find_element_safe(by, value, timeout=2)
            if element:
                print(f"  Found permission button: '{value}'")
                break
    finally:
        driver.driver.implicitly_wait(10)

    if element:
        element.click()
        time.sleep(2)
        print("  Microphone permission granted")
    else:
        print("  No permission dialog — skipping")


def navigate_to_home(driver: AppiumDriver, retries: int = 3) -> bool:
    """
    Navigate back to the app's home screen after a scenario completes.

    Tries tapping the Home tab in the bottom navigation bar.
    Falls back to pressing the Android Back key repeatedly if the tab
    cannot be found.

    Returns:
        True if the Home tab was tapped, False if only back-key fallback ran.
    """
    print(f"\n{'='*50}")
    print("Navigate: Return to Home Screen")
    print(f"{'='*50}")

    # Ensure the Acme Pizza app is in the foreground before searching for
    # the Home tab.  On 3-button-nav phones the system Home button also has
    # content-desc='Home' — if the app is not active, we'd tap the wrong button
    # and land on the Android launcher instead of the app home screen.
    _app_pkg = driver.config["capabilities"]["appPackage"]
    try:
        _activity = driver.driver.current_activity or ""
        if "acmepizza" not in _activity.lower():
            print(f"  App not in foreground ({_activity}) — activating")
            driver.driver.activate_app(_app_pkg)
            time.sleep(3)
    except Exception as _ae:
        print(f"  Activity check failed: {_ae}")

    # Fast path: if the home-screen delivery/carryout header is already visible,
    # skip all back-press retries — we're already home.
    driver.driver.implicitly_wait(0)
    try:
        _hdr_check = driver.driver.find_elements(
            AppiumBy.XPATH,
            "//*[contains(@content-desc,'DELIVERY') or contains(@content-desc,'CARRYOUT')]",
        )
        if any(e.rect.get("y", 9999) < 400 for e in _hdr_check):
            print("  ✅ Already on home screen")
            return True
    except Exception:
        pass
    finally:
        driver.driver.implicitly_wait(10)

    # Restrict Home tab search to the bottom portion of the screen so the
    # system navigation bar buttons are excluded.
    try:
        _screen_h = driver.driver.get_window_size()["height"]
    except Exception:
        _screen_h = 2340  # reasonable fallback

    # Acme Pizza bottom nav sits above the system nav bar (~120 px).
    # Accept any Home element in the bottom 400 px of the app area.
    _min_y = _screen_h - 500
    _max_y = _screen_h - 80   # exclude the system nav bar

    locators = [
        (AppiumBy.XPATH, "//*[@content-desc='Home']"),
        (AppiumBy.XPATH, "//*[@text='Home']"),
        (AppiumBy.XPATH, "//*[contains(@content-desc,'Home')]"),
        (AppiumBy.XPATH, "//*[contains(@text,'Home')]"),
    ]

    for attempt in range(1, retries + 1):
        driver.driver.implicitly_wait(0)
        try:
            for by, value in locators:
                elements = driver.driver.find_elements(by, value)
                # Filter to elements in the app's bottom nav bar area
                bottom_els = [e for e in elements
                              if _min_y <= e.rect.get("y", 0) <= _max_y]
                if bottom_els:
                    bottom_els[0].click()
                    time.sleep(2)
                    print(f"  ✅ Tapped Home tab (attempt {attempt})")
                    return True
        finally:
            driver.driver.implicitly_wait(10)

        print(f"  Home tab not found (attempt {attempt}/{retries}) — pressing Back")
        driver.driver.back()
        time.sleep(1)

    print("  ⚠️  Could not find Home tab — may be on home screen already")
    return False


def get_voice_session_id(driver: AppiumDriver) -> str:
    """
    Intended to capture the voice session ID via the '#' debug button.
    That button is not currently present/recognised in this build, so
    this function returns an empty string without touching the screen.
    """
    print("  ℹ️  Session ID capture skipped (# button not available in this build)")
    return ""


def _read_clipboard(driver: AppiumDriver) -> str:
    """
    Read the Android clipboard text, trying Appium first then ADB as fallback.
    Returns empty string if nothing can be read.
    """
    # 1. Appium native
    try:
        text = driver.driver.get_clipboard_text() or ""
        if text:
            return text
    except Exception as e:
        print(f"    (Appium clipboard read failed: {e})")

    # 2. ADB fallback — most reliable: read via clipboard service call
    # via UiAutomator's getText. Simpler: just try the clipboard service call.
    try:
        result = subprocess.run(
            ["adb", "shell", "service", "call", "clipboard", "2",
             "s16", "com.android.shell"],
            capture_output=True, text=True, timeout=5,
        )
        raw = result.stdout
        # Output looks like: Result: Parcel(... "\nsome-text\n" ...)
        # Extract text between quotes
        import re
        match = re.search(r'"([^"]+)"', raw)
        if match:
            return match.group(1).strip()
    except Exception as e:
        print(f"    (ADB clipboard read failed: {e})")

    return ""


def verify_voice_agent_active(driver: AppiumDriver) -> bool:
    print(f"\n{'='*50}")
    print("Step 6: Verify voice agent is active")
    print(f"{'='*50}")

    # Quick best-effort check — do NOT wait long here because the conversation
    # must start before Ava's greeting window closes.  If greeting keywords
    # are already on screen (they often appear within 1-2 s of detection),
    # we confirm immediately; otherwise we accept the miss and move on.
    keywords = ["how can i help", "what can i get", "ready", "take your time", "voice ordering"]
    timeout = 3
    poll_interval = 1
    elapsed = 0

    while elapsed < timeout:
        texts = []
        driver.driver.implicitly_wait(0)
        try:
            elements = driver.driver.find_elements(
                AppiumBy.XPATH, "//*[@text != '' or @content-desc != '']"
            )
            for el in elements:
                for attr in ("text", "content-desc"):
                    val = el.get_attribute(attr)
                    if val and val.strip():
                        texts.append(val.strip())
        except Exception:
            pass
        finally:
            driver.driver.implicitly_wait(10)

        combined = " ".join(texts).lower()
        matched = [kw for kw in keywords if kw in combined]
        if matched:
            print(f"  Agent verified! Matched keyword(s): {matched}")
            print(f"  Visible text: {texts}")
            driver.take_screenshot("step6_agent_verified")
            return True

        time.sleep(poll_interval)
        elapsed += poll_interval
        print(f"  Waiting for agent greeting... ({elapsed}s)")

    print("  Agent greeting not detected within timeout")
    driver.take_screenshot("step6_agent_not_verified")
    return False


def _check_ai_disclaimer_text(texts: list) -> tuple:
    """
    Pure helper — determines whether a list of screen text strings contains
    a valid AI disclaimer.

    Returns (passed, has_ai_mention, has_error_caveat).
    Extracted so it can be unit-tested without an Appium session.
    """
    combined = " ".join(texts).lower()
    has_ai_mention   = "uses ai" in combined or "feature uses" in combined or "ava ai" in combined
    has_error_caveat = any(w in combined for w in ("occasionally", "incorrect", "misleading", "mistakes"))
    return has_ai_mention and has_error_caveat, has_ai_mention, has_error_caveat


def _check_ai_disclaimer_source(source: str) -> tuple:
    """
    Pure helper — same concept checks as _check_ai_disclaimer_text but operates
    on the raw page_source XML string.

    Returns (passed, has_ai_mention, has_error_caveat).
    Extracted so it can be unit-tested with a saved page_source fixture.
    """
    s = source.lower()
    has_ai_mention   = "uses ai" in s or "feature uses" in s or "ava ai" in s
    has_error_caveat = any(w in s for w in ("occasionally", "incorrect", "misleading", "mistakes"))
    return has_ai_mention and has_error_caveat, has_ai_mention, has_error_caveat


def _save_disclaimer_evidence(texts: list, source: str = None) -> None:
    """
    Save the raw texts list and page_source to logs/ on disclaimer failure.

    These files let you write or update unit tests and fix the matcher without
    re-running the device test.  File names include a timestamp so multiple
    failures don't overwrite each other.

    Output:
        logs/disclaimer_texts_<ts>.json    — the texts list as JSON
        logs/disclaimer_source_<ts>.xml    — the raw page_source XML (if available)
    """
    import json
    from datetime import datetime as _dt
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    texts_path = os.path.join(logs_dir, f"disclaimer_texts_{ts}.json")
    with open(texts_path, "w", encoding="utf-8") as f:
        json.dump(texts, f, indent=2, ensure_ascii=False)
    print(f"  Evidence saved → {texts_path}")
    if source:
        source_path = os.path.join(logs_dir, f"disclaimer_source_{ts}.xml")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(source)
        print(f"  Evidence saved → {source_path}")
        print("  To write a fixture test, copy the saved files to unit_tests/fixtures/ "
              "and add a test_real_disclaimer_source() case.")


def verify_ai_disclaimer(driver: AppiumDriver, texts: list = None) -> bool:
    """
    Check that the AI disclaimer is visible on the VOICE ORDERING screen.

    The disclaimer must convey that this is an AI feature and that it can
    occasionally make mistakes.  Exact wording is not enforced — we look for
    the presence of both concepts:
      • AI feature identification ("uses ai", "ava ai", etc.)
      • error caveat ("occasionally", "incorrect", "misleading", "mistakes")

    Call this POST-conversation — the disclaimer renders alongside Ava's first
    greeting (not at loading-cleared time), so only the post-conversation
    page_source check reliably finds it.

    Args:
        driver: AppiumDriver instance
        texts:  Pre-scraped screen texts; when provided the fast path is tried
                first.  Pass None to skip straight to a fresh scrape.

    Returns True if both concepts are present, False otherwise.
    """
    print(f"\n{'='*50}")
    print("Verify: AI disclaimer on VOICE ORDERING screen")
    print(f"{'='*50}")

    passed           = False
    has_ai_mention   = False
    has_error_caveat = False

    def _scrape_texts():
        driver.driver.implicitly_wait(0)
        try:
            elements = driver.driver.find_elements(
                AppiumBy.XPATH, "//*[@text != '' or @content-desc != '']"
            )
            result = []
            for el in elements:
                for attr in ("text", "content-desc"):
                    val = el.get_attribute(attr)
                    if val and val.strip():
                        result.append(val.strip())
            return result
        except Exception:
            return []
        finally:
            driver.driver.implicitly_wait(10)

    if texts is not None:
        # Fast path: use texts already captured during navigation detection.
        # Guard: if the texts still show a loading screen, discard them.
        if any("loading" in t.lower() for t in texts):
            print("  ⚠️  Pre-scraped texts show loading state — falling back to fresh scrape")
            texts = None
        else:
            passed, has_ai_mention, has_error_caveat = _check_ai_disclaimer_text(texts)
            print(f"  (Using {len(texts)} texts from navigation scrape)")

    if texts is None:
        # Slow path: fresh attribute scrape.
        texts = _scrape_texts()
        passed, has_ai_mention, has_error_caveat = _check_ai_disclaimer_text(texts)

    # Page-source fallback: the disclaimer text is often in a React Native Text
    # component that exposes content in the XML but not via @text/@content-desc.
    raw_source = None
    if not passed:
        try:
            print("  (attribute scrape missed disclaimer — trying page_source)")
            raw_source = driver.driver.page_source
            passed, has_ai_mention, has_error_caveat = _check_ai_disclaimer_source(raw_source)
            if passed:
                print("  ✅ AI disclaimer found (via page source fallback)")
        except Exception as e:
            print(f"  ⚠️  page_source check failed: {e}")

    if passed:
        print("  ✅ AI disclaimer found")
    else:
        missing = []
        if not has_ai_mention:
            missing.append("AI feature identification ('uses AI')")
        if not has_error_caveat:
            missing.append("error caveat ('occasionally', 'incorrect', 'misleading', or 'mistakes')")
        print(f"  ❌ AI disclaimer missing: {', '.join(missing)}")
        print(f"  Screen texts ({len(texts)}):")
        for t in texts:
            print(f"    {t!r}")
        # Save full evidence so the next fix can be made from the log alone —
        # no second device run needed.
        _save_disclaimer_evidence(texts, raw_source)

    driver.take_screenshot("ai_disclaimer_check")
    return passed


def _dump_screen_elements(label: str = "") -> None:
    """
    Dump current screen elements via adb uiautomator dump and print a compact table.
    Called automatically on navigation failures so you can copy-paste the output here.
    No-ops silently if adb is unavailable.
    """
    import subprocess
    import xml.etree.ElementTree as ET

    prefix = f"[dump{': ' + label if label else ''}]"
    try:
        r = subprocess.run(
            ["adb", "shell", "uiautomator", "dump", "/sdcard/ui_dump.xml"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            print(f"  {prefix} adb dump failed: {r.stderr.strip()}")
            return
        r2 = subprocess.run(
            ["adb", "pull", "/sdcard/ui_dump.xml", "/tmp/ui_dump.xml"],
            capture_output=True, text=True, timeout=10,
        )
        if r2.returncode != 0:
            print(f"  {prefix} adb pull failed: {r2.stderr.strip()}")
            return
        xml_str = open("/tmp/ui_dump.xml", encoding="utf-8").read()
        root = ET.fromstring(xml_str)
        print(f"\n  {prefix} Elements on screen (class | clickable | text | content-desc | bounds):")
        for node in root.iter("node"):
            cls  = (node.get("class") or "").rsplit(".", 1)[-1]
            cl   = "Y" if node.get("clickable") == "true" else "."
            text = (node.get("text") or "")[:40]
            desc = (node.get("content-desc") or "")[:60]
            bnd  = node.get("bounds", "")
            if text or desc:   # skip empty nodes
                print(f"    [{cls}] cl={cl}  text='{text}'  desc='{desc}'  {bnd}")
        print()
    except Exception as e:
        print(f"  {prefix} Could not dump screen: {e}")


def navigate_order_ahead(driver: AppiumDriver) -> str:
    """
    Pre-conversation setup for Order Ahead scenarios.

    Flow (mirrors the screenshots):
      1. Tap the ASAP chip in the DELIVERY row at the top of Home
      2. Tap ASAP next to Time in the delivery options sheet
      3. Select the Day & Time radio button
      4. Tap Select Date → pick today in the calendar → OK
      5. Pick the time slot closest to current time + 1 hour
      6. Tap Continue

    Returns the selected time string (e.g. '06:15 PM') so the scenario
    can include it in verification or state-machine prompts.

    Raises RuntimeError if any navigation step fails.
    """
    print(f"\n{'='*50}")
    print("Order Ahead: Configure scheduled delivery time")
    print(f"{'='*50}")

    def _tap_first(locators, label):
        """
        Try each locator in order; tap the first element found.
        If the matched element is not directly clickable, walk up to the
        nearest clickable ancestor using a relative XPath from the element.
        """
        driver.driver.implicitly_wait(0)
        try:
            for by, value in locators:
                els = driver.driver.find_elements(by, value)
                if not els:
                    continue
                el = els[0]
                if el.get_attribute("clickable") != "true":
                    try:
                        # Relative search from the element — correct ancestor walk
                        el = el.find_element(
                            AppiumBy.XPATH,
                            "./ancestor-or-self::*[@clickable='true'][1]"
                        )
                    except Exception:
                        pass  # fall through and click the original element
                el.click()
                print(f"  Tapped: {label}")
                time.sleep(1.5)
                return True
        finally:
            driver.driver.implicitly_wait(10)
        return False

    # ── Step 1: Tap the DELIVERY/ASAP header row on the home screen ─────────────
    # From the element dump the row is an ImageView with no @text but
    # content-desc = 'DELIVERY\nASAP\n6540 W STATE HWY 22'.
    # Retry up to 4× with 2 s gaps — the delivery row may take a moment to
    # render after navigate_to_home() uses Back to return to home.
    # The delivery header shows "DELIVERY\nASAP\n<address>" on first run but
    # "DELIVERY\nToday at HH:MM AM\n<address>" if a time was previously selected.
    # Match on "DELIVERY" alone so both states are found.
    delivery_row = None
    for _attempt in range(4):
        driver.driver.implicitly_wait(0)
        try:
            for by, value in [
                (AppiumBy.XPATH,
                 "//android.widget.ImageView[contains(@content-desc,'DELIVERY')]"),
                (AppiumBy.XPATH,
                 "//*[contains(@content-desc,'DELIVERY') and contains(@content-desc,'6540')]"),
                (AppiumBy.XPATH,
                 "//*[contains(@content-desc,'DELIVERY')]"),
                # Also match CARRYOUT mode (app state left over from a previous scenario)
                (AppiumBy.XPATH,
                 "//android.widget.ImageView[contains(@content-desc,'CARRYOUT')]"),
                (AppiumBy.XPATH,
                 "//*[contains(@content-desc,'CARRYOUT')]"),
            ]:
                els = driver.driver.find_elements(by, value)
                # Filter to elements in the top header area (y < 400) to avoid false matches
                els = [e for e in els if e.rect.get("y", 9999) < 400]
                if els:
                    delivery_row = els[0]
                    break
        finally:
            driver.driver.implicitly_wait(10)

        if delivery_row is not None:
            break
        print(f"  ⏳ Delivery header not found yet (attempt {_attempt + 1}/4) — waiting 2 s...")
        time.sleep(2)

    if delivery_row is None:
        _dump_screen_elements("home screen — delivery header not found")
        raise RuntimeError("Order Ahead: could not find delivery header row")

    # If the app is in CARRYOUT mode (previous scenario), switch via the UI.
    # The app persists mode to disk so an app restart does NOT reset it.
    try:
        _hdr_desc = delivery_row.get_attribute("content-desc") or ""
    except Exception:
        _hdr_desc = ""
    if "CARRYOUT" in _hdr_desc.upper() and "DELIVERY" not in _hdr_desc.upper():
        print("  App is in CARRYOUT mode — opening DEL/CARRYOUT panel to switch to DELIVERY")
        # App persists CARRYOUT mode across restarts so we must switch via the UI.
        # The chevron position on CARRYOUT header differs from DELIVERY, so try
        # multiple x percentages with mobile:clickGesture (el.click() is unreliable
        # on this React Native element per existing learnings in navigate_order_ahead).
        # Panel-open detection: look for @text='DELIVERY' exact match — the DELIVERY
        # panel tab.  The CARRYOUT header has CARRYOUT in content-desc (not @text),
        # so the exact-text match only fires when the panel is open.
        time.sleep(3)  # let React Native touch handlers settle (same as main flow)
        _r = delivery_row.rect

        def _delivery_panel_open() -> bool:
            driver.driver.implicitly_wait(0)
            try:
                return bool(driver.driver.find_elements(
                    AppiumBy.XPATH, "//*[@text='DELIVERY' or @content-desc='DELIVERY']"
                ))
            finally:
                driver.driver.implicitly_wait(10)

        _panel_opened = False
        # Strategy 1: try multiple x positions on the found element
        for _pct in [0.85, 0.75, 0.65, 0.50, 0.35]:
            _cx = _r["x"] + int(_r["width"] * _pct)
            _cy = _r["y"] + int(_r["height"] * 0.75)
            print(f"  clickGesture at {int(_pct * 100)}% x → ({_cx}, {_cy})")
            driver.driver.execute_script("mobile: clickGesture", {"x": _cx, "y": _cy})
            time.sleep(1.5)
            if _delivery_panel_open():
                _panel_opened = True
                print(f"  Panel opened at {int(_pct * 100)}% x")
                break

        # Strategy 2: tap every clickable element in the header y-band
        if not _panel_opened:
            driver.driver.implicitly_wait(0)
            try:
                _hdr_clickables = [
                    e for e in driver.driver.find_elements(AppiumBy.XPATH, "//*[@clickable='true']")
                    if _r["y"] <= e.rect.get("y", 9999) <= _r["y"] + _r["height"] + 20
                    and e.rect.get("y", 9999) < 400
                ]
            finally:
                driver.driver.implicitly_wait(10)
            for _cel in _hdr_clickables:
                _cr = _cel.rect
                driver.driver.execute_script("mobile: clickGesture", {
                    "x": _cr["x"] + _cr["width"] // 2,
                    "y": _cr["y"] + _cr["height"] // 2,
                })
                time.sleep(1.5)
                if _delivery_panel_open():
                    _panel_opened = True
                    print("  Panel opened via header clickable element")
                    break

        if not _panel_opened:
            _dump_screen_elements("could not open DEL/CARRYOUT panel from CARRYOUT mode")
            raise RuntimeError("Order Ahead: could not open delivery/carryout panel from CARRYOUT mode")

        _tap_first([
            (AppiumBy.XPATH, "//*[@text='DELIVERY']"),
            (AppiumBy.XPATH, "//*[@content-desc='DELIVERY']"),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("DELIVERY")'),
        ], "DELIVERY tab")
        time.sleep(2)

        # After tapping DELIVERY the app shows an address search — enter the known
        # delivery test address (same address visible in the DELIVERY header content-desc).
        import subprocess as _sp_sw
        _sw_zip = "6540 W State Hwy 22"

        # Find the zip EditText
        _zip_fld = None
        driver.driver.implicitly_wait(0)
        try:
            for _zby, _zval in [
                (AppiumBy.XPATH, "//android.widget.EditText"),
                (AppiumBy.ANDROID_UIAUTOMATOR,
                 'new UiSelector().className("android.widget.EditText")'),
            ]:
                _zels = driver.driver.find_elements(_zby, _zval)
                if _zels:
                    _zip_fld = _zels[0]
                    break
        finally:
            driver.driver.implicitly_wait(10)

        if _zip_fld is None:
            _dump_screen_elements("DELIVERY tab — zip field not found")
            raise RuntimeError("Order Ahead: zip field not found after tapping DELIVERY tab")

        _zr = _zip_fld.rect
        _zy = _zr["y"] + _zr["height"] // 2
        print(f"  Entering delivery address: {_sw_zip!r}")
        _zip_fld.click()
        time.sleep(2.5)
        _sp_sw.run(["adb", "shell", "input", "keyevent", "KEYCODE_CTRL_A"],
                   capture_output=True, timeout=5)
        time.sleep(0.2)
        _sp_sw.run(["adb", "shell", "input", "keyevent", "KEYCODE_DEL"],
                   capture_output=True, timeout=5)
        time.sleep(0.2)
        _sp_sw.run(["adb", "shell", "input", "text", _sw_zip],
                   capture_output=True, timeout=5)
        time.sleep(1.0)
        _sp_sw.run(["adb", "shell", "input", "keyevent", "KEYCODE_SEARCH"],
                   capture_output=True, timeout=5)
        time.sleep(0.5)
        _sp_sw.run(["adb", "shell", "input", "keyevent", "KEYCODE_ENTER"],
                   capture_output=True, timeout=5)
        time.sleep(1.5)
        try:
            _ssw = driver.driver.get_window_size()["width"]
        except Exception:
            _ssw = 1080
        _sp_sw.run(["adb", "shell", "input", "tap", str(int(_ssw * 0.92)), str(_zy)],
                   capture_output=True, timeout=5)
        time.sleep(3)

        # Tap first address result (same locators as carryout step 5)
        _first_addr = None
        driver.driver.implicitly_wait(0)
        try:
            for _aby, _aval in [
                (AppiumBy.XPATH,
                 "//*[contains(@text,' miles') or contains(@content-desc,' miles')]"
                 "/ancestor-or-self::*[@clickable='true'][1]"),
                (AppiumBy.XPATH,
                 "//*[contains(@text,'DR') or contains(@text,'AVE') or "
                 "contains(@text,'RD') or contains(@text,'BLVD') or "
                 "contains(@text,'ST') or contains(@text,'HWY') or "
                 "contains(@text,'WAY')]"
                 "/ancestor-or-self::*[@clickable='true'][1]"),
                (AppiumBy.XPATH, "//*[@clickable='true']"),
            ]:
                _aels = driver.driver.find_elements(_aby, _aval)
                _aels = [e for e in _aels if e.rect.get("y", 0) >= 250]
                if _aels:
                    _first_addr = _aels[0]
                    break
        finally:
            driver.driver.implicitly_wait(10)

        if _first_addr is None:
            _dump_screen_elements("delivery address search — no result found")
            raise RuntimeError("Order Ahead: could not find first delivery address result")

        _addr_txt = (_first_addr.get_attribute("content-desc") or
                     _first_addr.get_attribute("text") or "")[:60]
        print(f"  Tapping address: {repr(_addr_txt)}")
        _first_addr.click()
        time.sleep(3)

        # The app shows an address-confirmation form — tap "Deliver to this location"
        if not _tap_first([
            (AppiumBy.XPATH, "//*[@text='Deliver to this location']"),
            (AppiumBy.XPATH, "//*[@content-desc='Deliver to this location']"),
            (AppiumBy.ANDROID_UIAUTOMATOR,
             'new UiSelector().text("Deliver to this location")'),
            (AppiumBy.XPATH, "//*[contains(@text,'Deliver to')]"),
        ], "Deliver to this location"):
            _dump_screen_elements("address form — 'Deliver to this location' not found")
            raise RuntimeError("Order Ahead: 'Deliver to this location' button not found")
        time.sleep(3)

        # Re-find the DELIVERY header with retries
        delivery_row = None
        for _sw in range(5):
            driver.driver.implicitly_wait(0)
            try:
                for _by, _val in [
                    (AppiumBy.XPATH,
                     "//android.widget.ImageView[contains(@content-desc,'DELIVERY')]"),
                    (AppiumBy.XPATH, "//*[contains(@content-desc,'DELIVERY')]"),
                ]:
                    _els = driver.driver.find_elements(_by, _val)
                    _els = [e for e in _els if e.rect.get("y", 9999) < 400]
                    if _els:
                        delivery_row = _els[0]
                        break
            finally:
                driver.driver.implicitly_wait(10)
            if delivery_row is not None:
                break
            print(f"  ⏳ DELIVERY header not visible yet (attempt {_sw + 1}/5) — waiting 2 s...")
            time.sleep(2)

        if delivery_row is None:
            _dump_screen_elements("DELIVERY header not found after mode switch")
            raise RuntimeError("Order Ahead: DELIVERY header not found after switching from CARRYOUT mode")
        print("  ✅ Switched to DELIVERY mode")

    try:
        _found_desc = delivery_row.get_attribute("content-desc") or ""
        print(f"  Found delivery header: {repr(_found_desc[:60])}")
    except Exception:
        pass

    driver.take_screenshot("order_ahead_00_before_tap")

    rect = delivery_row.rect
    cx = rect["x"] + rect["width"] // 2
    cy = rect["y"] + rect["height"] // 2
    # Also try the lower-right quarter of the element (where the ˅ chevron is)
    cx_chevron = rect["x"] + int(rect["width"] * 0.85)
    cy_chevron = rect["y"] + int(rect["height"] * 0.75)
    print(f"  Center coords: ({cx}, {cy})  Chevron coords: ({cx_chevron}, {cy_chevron})")

    # Wait for React Native touch handlers to settle after home navigation.
    time.sleep(3)

    import subprocess as _sp

    def _adb_tap(x: int, y: int) -> None:
        _sp.run(["adb", "shell", "input", "tap", str(x), str(y)],
                capture_output=True, timeout=5)

    def _wait_for(check_fn, timeout: float = 5.0, interval: float = 0.4) -> bool:
        """Poll check_fn until it returns True or timeout expires."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if check_fn():
                return True
            time.sleep(interval)
        return False

    def _on_delivery_options_panel() -> bool:
        """Return True when delivery options panel is open (DELIVERY/CARRYOUT toggle visible)."""
        driver.driver.implicitly_wait(0)
        try:
            return bool(driver.driver.find_elements(
                AppiumBy.XPATH,
                "//*[contains(@content-desc,'CARRYOUT') or contains(@text,'CARRYOUT')]"
            ))
        finally:
            driver.driver.implicitly_wait(10)

    def _on_delivery_time_screen() -> bool:
        """Return True when the delivery-time selection screen is active."""
        driver.driver.implicitly_wait(0)
        try:
            return bool(driver.driver.find_elements(
                AppiumBy.XPATH,
                "//*[contains(@content-desc,'As soon as possible') or contains(@content-desc,'Day & Time')]"
            ))
        finally:
            driver.driver.implicitly_wait(10)

    def _time_slots_visible() -> bool:
        """Return True when time slot buttons are visible on screen."""
        driver.driver.implicitly_wait(0)
        try:
            return bool(driver.driver.find_elements(
                AppiumBy.XPATH,
                "//*[contains(@content-desc,' AM') or contains(@content-desc,' PM') "
                "or contains(@text,' AM') or contains(@text,' PM')]"
            ))
        finally:
            driver.driver.implicitly_wait(10)

    # Strategy 1: try multiple x positions on the delivery row element.
    # el.click() and a single centre-tap both fail silently on this React Native
    # element — multiple positions are needed because the chevron hit-target is narrow.
    _panel_opened = False
    for _pct in [0.85, 0.75, 0.65, 0.50, 0.35]:
        _tx = rect["x"] + int(rect["width"] * _pct)
        _ty = rect["y"] + int(rect["height"] * 0.75)
        print(f"  clickGesture at {int(_pct * 100)}% x → ({_tx}, {_ty})")
        driver.driver.execute_script("mobile: clickGesture", {"x": _tx, "y": _ty})
        time.sleep(1.5)
        if _on_delivery_options_panel() or _on_delivery_time_screen():
            _panel_opened = True
            print(f"  Panel opened at {int(_pct * 100)}% x")
            break

    # Strategy 2: tap every clickable element in the header y-band
    if not _panel_opened:
        driver.driver.implicitly_wait(0)
        try:
            _hdr_clickables = [
                e for e in driver.driver.find_elements(AppiumBy.XPATH, "//*[@clickable='true']")
                if rect["y"] <= e.rect.get("y", 9999) <= rect["y"] + rect["height"] + 20
                and e.rect.get("y", 9999) < 400
            ]
        finally:
            driver.driver.implicitly_wait(10)
        for _cel in _hdr_clickables:
            _cr = _cel.rect
            driver.driver.execute_script("mobile: clickGesture", {
                "x": _cr["x"] + _cr["width"] // 2,
                "y": _cr["y"] + _cr["height"] // 2,
            })
            time.sleep(1.5)
            if _on_delivery_options_panel() or _on_delivery_time_screen():
                _panel_opened = True
                print("  Panel opened via header clickable element")
                break

    if not _panel_opened:
        driver.take_screenshot("order_ahead_tap_failed")
        _dump_screen_elements("delivery options panel — all tap strategies failed")
        raise RuntimeError("Order Ahead: could not open delivery options panel after 5 attempts")

    driver.take_screenshot("order_ahead_01_delivery_options_panel")
    print("  Delivery options panel opened")

    # ── Step 1b: Tap Time row chip to open delivery-time selection ───────────────
    # Panel shows "Time  ASAP >" when default, or "Time  Today at HH:MM AM >"
    # when a time was previously selected.  Match the chip by "Time" row or "ASAP".
    # Time chip shows "ASAP", "Today at HH:MM", "Tomorrow at HH:MM", or a date string.
    # Match any of those patterns.
    if not _tap_first([
        (AppiumBy.XPATH, "//*[@content-desc='ASAP']"),
        (AppiumBy.XPATH, "//*[contains(@content-desc,'ASAP')]"),
        (AppiumBy.XPATH, "//*[contains(@content-desc,' at ')]"),   # "Today at", "Tomorrow at", etc.
        (AppiumBy.XPATH, "//*[contains(@content-desc,'Time') and contains(@content-desc,'AM')]"),
        (AppiumBy.XPATH, "//*[contains(@content-desc,'Time') and contains(@content-desc,'PM')]"),
        (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().description("ASAP")'),
        (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("ASAP")'),
        (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains(" at ")'),
    ], "Time row chip"):
        _dump_screen_elements("delivery options panel — Time row chip not found")
        raise RuntimeError("Order Ahead: could not find Time row chip on delivery options panel")

    _wait_for(lambda: _time_slots_visible() or _on_delivery_time_screen(), timeout=5)
    driver.take_screenshot("order_ahead_02_delivery_time_screen")

    today = datetime.now()
    day_str = str(today.day)
    month_name = today.strftime("%B")   # e.g. "April"

    # ── Step 2: Select Day & Time radio button ────────────────────────────────
    # Only tap it if we're on the delivery-time selection screen (ASAP/Day&Time radios).
    # If Day & Time was previously selected the screen may already show time slots.
    if not _time_slots_visible():
        if not _tap_first([
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Day & Time')]"),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("Day & Time")'),
        ], "Day & Time radio"):
            _dump_screen_elements("delivery time screen — Day & Time radio not found")
            raise RuntimeError("Order Ahead: could not find Day & Time radio button")
        _wait_for(_time_slots_visible, timeout=4)

    driver.take_screenshot("order_ahead_02_day_time_selected")

    # ── Step 3: Tap Select Date (only needed when no date is pre-selected) ────
    # When Day & Time was previously selected the date is already set and time
    # slots are shown immediately — skip this step in that case.
    if not _time_slots_visible():
        if not _tap_first([
            (AppiumBy.XPATH, "//*[@content-desc='Select Date']"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Select Date')]"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Select date')]"),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("Select Date")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("Select date")'),
        ], "Select Date button"):
            _dump_screen_elements("delivery time screen — Select Date not found")
            raise RuntimeError("Order Ahead: could not find Select Date button")

        driver.take_screenshot("order_ahead_03_calendar")

        # ── Step 4: Tap today's date in the calendar picker ──────────────────
        if not _tap_first([
            (AppiumBy.XPATH, f"//*[@text='{day_str}']"),
            (AppiumBy.XPATH, f"//*[contains(@content-desc,'{day_str} {month_name}')]"),
            (AppiumBy.XPATH, f"//*[contains(@content-desc,'{month_name} {day_str}')]"),
            (AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{day_str}")'),
            (AppiumBy.ANDROID_UIAUTOMATOR,
             f'new UiSelector().descriptionContains("{day_str} {month_name}")'),
        ], f"day {day_str} in calendar"):
            _dump_screen_elements(f"calendar — day {day_str} not found")
            raise RuntimeError(f"Order Ahead: could not select day {day_str} in calendar")

        # ── Step 5: Tap OK to confirm date ───────────────────────────────────
        driver.take_screenshot("order_ahead_03b_day_selected")
        time.sleep(0.5)
        if not _tap_first([
            (AppiumBy.XPATH, "//*[@text='Ok']"),
            (AppiumBy.XPATH, "//*[@text='OK']"),
            (AppiumBy.XPATH, "//*[@content-desc='Ok']"),
            (AppiumBy.XPATH, "//*[@content-desc='OK']"),
            (AppiumBy.XPATH, "//*[contains(@text,'Ok') or contains(@text,'OK')]"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Ok') or contains(@content-desc,'OK')]"),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Ok")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("OK")'),
        ], "OK button"):
            _dump_screen_elements("date picker — OK button not found")
            raise RuntimeError("Order Ahead: could not find OK button in date picker")

    driver.take_screenshot("order_ahead_04_time_slots")

    # ── Step 7: Pick the time slot closest to current time + 1 hour ──────────
    target = today + timedelta(hours=1)
    # Round up to the next 15-minute boundary
    remainder = target.minute % 15
    if remainder:
        target += timedelta(minutes=15 - remainder)
    target = target.replace(second=0, microsecond=0)

    # App displays zero-padded 12-hour time: "06:15 PM"
    slot_text = target.strftime("%I:%M %p").upper()
    print(f"  Target time slot: {slot_text} (now + ~1 h)")

    selected_slot = slot_text
    slot_tapped = False

    import re as _re

    def _slot_value(el) -> str:
        """Return the display value of a time slot element (text or content-desc)."""
        return (el.get_attribute("text") or el.get_attribute("content-desc") or "").strip()

    def _is_time_slot(val: str) -> bool:
        return bool(_re.match(r'^\d{2}:\d{2} (AM|PM)$', val))

    # Try scrolling to exact slot via text, then content-desc
    driver.driver.implicitly_wait(0)
    try:
        for uia in [
            f'new UiScrollable(new UiSelector().scrollable(true))'
            f'.scrollIntoView(new UiSelector().text("{slot_text}"))',
            f'new UiScrollable(new UiSelector().scrollable(true))'
            f'.scrollIntoView(new UiSelector().description("{slot_text}"))',
        ]:
            try:
                els = driver.driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, uia)
                if els:
                    els[0].click()
                    slot_tapped = True
                    print(f"  Selected: {slot_text}")
                    time.sleep(0.5)
                    break
            except Exception:
                pass
    finally:
        driver.driver.implicitly_wait(10)

    if not slot_tapped:
        # Direct XPath — both @text and @content-desc
        driver.driver.implicitly_wait(0)
        try:
            for by, value in [
                (AppiumBy.XPATH, f"//*[@text='{slot_text}']"),
                (AppiumBy.XPATH, f"//*[@content-desc='{slot_text}']"),
                (AppiumBy.XPATH, f"//*[contains(@text,'{slot_text}')]"),
                (AppiumBy.XPATH, f"//*[contains(@content-desc,'{slot_text}')]"),
            ]:
                els = driver.driver.find_elements(by, value)
                if els:
                    els[0].click()
                    slot_tapped = True
                    time.sleep(0.5)
                    break
        finally:
            driver.driver.implicitly_wait(10)

    if not slot_tapped:
        # Last resort: tap the first visible time slot (text OR content-desc)
        print(f"  Warning: {slot_text} not visible — selecting first available slot")
        driver.driver.implicitly_wait(0)
        try:
            for by, value in [
                (AppiumBy.XPATH, "//*[contains(@text,' AM') or contains(@text,' PM')]"),
                (AppiumBy.XPATH, "//*[contains(@content-desc,' AM') or contains(@content-desc,' PM')]"),
            ]:
                els = driver.driver.find_elements(by, value)
                time_els = [e for e in els if _is_time_slot(_slot_value(e))]
                if time_els:
                    selected_slot = _slot_value(time_els[0])
                    time_els[0].click()
                    slot_tapped = True
                    print(f"  Fell back to first slot: {selected_slot}")
                    time.sleep(0.5)
                    break
        finally:
            driver.driver.implicitly_wait(10)

    if not slot_tapped:
        _dump_screen_elements("time slot screen — no slot found")
        raise RuntimeError("Order Ahead: could not select any time slot")

    driver.take_screenshot("order_ahead_05_slot_selected")

    # ── Step 8: Continue ──────────────────────────────────────────────────────
    if not _tap_first([
        (AppiumBy.XPATH, "//*[@text='Continue']"),
        (AppiumBy.XPATH, "//*[contains(@text,'Continue')]"),
        (AppiumBy.XPATH, "//*[@content-desc='Continue']"),
    ], "Continue"):
        _dump_screen_elements("time slot screen — Continue button not found")
        raise RuntimeError("Order Ahead: could not find Continue button")

    driver.take_screenshot("order_ahead_07_complete")
    print(f"  ✅ Order ahead set: {selected_slot}")
    return selected_slot


def navigate_order_ahead_carryout(driver: AppiumDriver, zip_code: str = "40014") -> str:
    """
    Pre-conversation setup for Order Ahead CARRYOUT scenarios.

    Flow (linear, no retry loops):
      1. Find DELIVERY or CARRYOUT header (app persists mode, restart does not reset it)
      2. Open DEL/CARRYOUT panel (85% x if DELIVERY; multi-position if CARRYOUT)
      3. Tap CARRYOUT tab → wait for zip search field
      4. Enter zip_code → tap magnifying-glass search button
      5. Wait for store results → tap first result
      6. Tap "Place a future order"
      7. Pick today's date → select time slot ~1 h from now → Continue

    Returns the selected time slot string (e.g. '02:00 PM').
    Raises RuntimeError if any step fails (with screenshot + element dump).
    """
    print(f"\n{'='*50}")
    print(f"Order Ahead (Carryout): zip={zip_code}")
    print(f"{'='*50}")

    import re as _re

    _app_pkg = driver.config["capabilities"]["appPackage"]

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _tap_first(locators, label):
        driver.driver.implicitly_wait(0)
        try:
            for by, value in locators:
                els = driver.driver.find_elements(by, value)
                if not els:
                    continue
                el = els[0]
                if el.get_attribute("clickable") != "true":
                    try:
                        el = el.find_element(
                            AppiumBy.XPATH,
                            "./ancestor-or-self::*[@clickable='true'][1]"
                        )
                    except Exception:
                        pass
                el.click()
                print(f"  Tapped: {label}")
                time.sleep(1.5)
                return True
        finally:
            driver.driver.implicitly_wait(10)
        return False

    def _find_first(locators, label, y_min=None, y_max=None):
        """Return first matching element (filtered by y range if given)."""
        driver.driver.implicitly_wait(0)
        try:
            for by, value in locators:
                els = driver.driver.find_elements(by, value)
                if y_min is not None:
                    els = [e for e in els if e.rect.get("y", 9999) >= y_min]
                if y_max is not None:
                    els = [e for e in els if e.rect.get("y", 9999) <= y_max]
                if els:
                    print(f"  Found: {label}")
                    return els[0]
        finally:
            driver.driver.implicitly_wait(10)
        return None

    def _visible(locators) -> bool:
        driver.driver.implicitly_wait(0)
        try:
            for by, value in locators:
                if driver.driver.find_elements(by, value):
                    return True
        finally:
            driver.driver.implicitly_wait(10)
        return False

    def _time_slots_visible() -> bool:
        return _visible([
            (AppiumBy.XPATH,
             "//*[contains(@content-desc,' AM') or contains(@content-desc,' PM') "
             "or contains(@text,' AM') or contains(@text,' PM')]"),
        ])

    # ── Steps 1-2: Find current mode header and open DEL/CARRYOUT panel ─────────
    # App persists mode to disk — a restart does NOT reset to DELIVERY.
    # Detect whichever header is current and open the panel accordingly.
    print("\n  Steps 1-2: Find header and open DEL/CARRYOUT panel")

    hdr_el = None
    for _att in range(4):
        hdr_el = _find_first([
            (AppiumBy.XPATH,
             "//android.widget.ImageView[contains(@content-desc,'DELIVERY')]"),
            (AppiumBy.XPATH,
             "//android.widget.ImageView[contains(@content-desc,'CARRYOUT')]"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'DELIVERY')]"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'CARRYOUT')]"),
        ], "DELIVERY/CARRYOUT header", y_max=400)
        if hdr_el:
            break
        print(f"  ⏳ Header not found (attempt {_att + 1}/4) — waiting 2 s")
        time.sleep(2)

    if hdr_el is None:
        _dump_screen_elements("home — order mode header not found")
        raise RuntimeError("OA Carryout: could not find DELIVERY or CARRYOUT header")

    _hdr_desc = hdr_el.get_attribute("content-desc") or ""
    _current_mode = "CARRYOUT" if "CARRYOUT" in _hdr_desc.upper() else "DELIVERY"
    print(f"  Current mode: {_current_mode}")

    def _panel_open() -> bool:
        """Panel open when CARRYOUT tab is visible as exact @text (not the header content-desc)."""
        return _visible([
            (AppiumBy.XPATH, "//*[@text='CARRYOUT' or @content-desc='CARRYOUT']"),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("CARRYOUT")'),
        ])

    time.sleep(3)  # let React Native touch handlers settle
    r = hdr_el.rect
    _panel_opened = False

    # Mirror the position order that works in navigate_order_ahead's CARRYOUT→DELIVERY
    # switch: right-to-left, no BACK keypresses between attempts.
    for _pct in [0.85, 0.75, 0.65, 0.50, 0.35]:
        _cx = r["x"] + int(r["width"] * _pct)
        _cy = r["y"] + int(r["height"] * 0.75)
        print(f"  clickGesture at {int(_pct * 100)}% x → ({_cx}, {_cy})")
        driver.driver.execute_script("mobile: clickGesture", {"x": _cx, "y": _cy})
        time.sleep(1.5)
        if _panel_open():
            _panel_opened = True
            print(f"  Panel opened at {int(_pct * 100)}% x")
            break

    # Fallback: tap every clickable element in the header y-band
    if not _panel_opened:
        driver.driver.implicitly_wait(0)
        try:
            _hdr_clickables = [
                e for e in driver.driver.find_elements(
                    AppiumBy.XPATH, "//*[@clickable='true']")
                if r["y"] <= e.rect.get("y", 9999) <= r["y"] + r["height"] + 20
                and e.rect.get("y", 9999) < 400
            ]
        finally:
            driver.driver.implicitly_wait(10)
        for _cel in _hdr_clickables:
            _cr = _cel.rect
            driver.driver.execute_script("mobile: clickGesture", {
                "x": _cr["x"] + _cr["width"] // 2,
                "y": _cr["y"] + _cr["height"] // 2,
            })
            time.sleep(1.5)
            if _panel_open():
                _panel_opened = True
                print("  Panel opened via header clickable element")
                break

    driver.take_screenshot("oa_carryout_02_after_chevron")

    if not _panel_opened:
        _dump_screen_elements("expected DEL/CARRYOUT panel — not found")
        raise RuntimeError("OA Carryout: DEL/CARRYOUT selector panel did not open")

    print("  ✅ DEL/CARRYOUT panel is open")
    driver.take_screenshot("oa_carryout_03_panel_open")

    # ── Step 3: Tap CARRYOUT tab ──────────────────────────────────────────────
    print("\n  Step 3: Tap CARRYOUT tab")
    if not _tap_first([
        (AppiumBy.XPATH, "//*[@text='CARRYOUT']"),
        (AppiumBy.XPATH, "//*[@content-desc='CARRYOUT']"),
        (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("CARRYOUT")'),
        (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().description("CARRYOUT")'),
    ], "CARRYOUT tab"):
        _dump_screen_elements("panel — CARRYOUT tab not found")
        raise RuntimeError("OA Carryout: could not tap CARRYOUT tab")

    time.sleep(2)
    driver.take_screenshot("oa_carryout_04_carryout_tab")

    # After tapping CARRYOUT the app shows either:
    #   A) Zip search EditText — no saved store, need to search
    #   B) Carryout home with address row — saved store, tap Time row to schedule
    zip_search_visible = _visible([
        (AppiumBy.XPATH, "//android.widget.EditText"),
        (AppiumBy.ANDROID_UIAUTOMATOR,
         'new UiSelector().className("android.widget.EditText")'),
    ])
    _carryout_home_visible = not zip_search_visible

    if zip_search_visible:
        # ── Step 4: Enter zip code and tap search ─────────────────────────────
        print(f"\n  Step 4: Enter zip {zip_code} and search")
        zip_field = _find_first([
            (AppiumBy.XPATH, "//android.widget.EditText"),
            (AppiumBy.ANDROID_UIAUTOMATOR,
             'new UiSelector().className("android.widget.EditText")'),
            (AppiumBy.XPATH, "//*[@content-desc='Zip Code' and @clickable='true']"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Zip') and @clickable='true']"),
        ], "zip field")

        if zip_field is None:
            _dump_screen_elements("CARRYOUT tab — zip field not found")
            raise RuntimeError("OA Carryout: could not find zip code field")

        import subprocess as _sp_oa

        zr        = zip_field.rect
        zy        = zr["y"] + zr["height"] // 2
        zx_center = zr["x"] + zr["width"] // 2

        def _zip_field_value():
            return (zip_field.get_attribute("text") or
                    zip_field.get_attribute("content-desc") or "").strip()

        print(f"  Entering zip — Appium click to focus field, then adb input text")
        zip_field.click()
        time.sleep(2.5)
        driver.take_screenshot("oa_carryout_05a_focus")

        _sp_oa.run(["adb", "shell", "input", "keyevent", "KEYCODE_CTRL_A"],
                   capture_output=True, timeout=5)
        time.sleep(0.2)
        _sp_oa.run(["adb", "shell", "input", "keyevent", "KEYCODE_DEL"],
                   capture_output=True, timeout=5)
        time.sleep(0.2)
        _sp_oa.run(["adb", "shell", "input", "text", zip_code],
                   capture_output=True, timeout=5)
        time.sleep(1.0)
        driver.take_screenshot("oa_carryout_05b_typed")

        _fv = _zip_field_value()
        print(f"  Field value after typing: {repr(_fv)}")
        if zip_code in _fv:
            print(f"  ✅ Zip {zip_code!r} confirmed in field")
        else:
            print(f"  ⚠️  Field shows {_fv!r} — keyboard may not have appeared")

        driver.take_screenshot("oa_carryout_05_zip_done")

        print("  Triggering search via KEYCODE_SEARCH")
        _sp_oa.run(["adb", "shell", "input", "keyevent", "KEYCODE_SEARCH"],
                   capture_output=True, timeout=5)
        time.sleep(0.5)
        _sp_oa.run(["adb", "shell", "input", "keyevent", "KEYCODE_ENTER"],
                   capture_output=True, timeout=5)
        time.sleep(1.5)

        try:
            _sw = driver.driver.get_window_size()["width"]
        except Exception:
            _sw = 1080
        mg_x = int(_sw * 0.92)
        mg_y = zy
        print(f"  Also tapping magnifying glass at ({mg_x}, {mg_y}) [92% of screen width]")
        _sp_oa.run(["adb", "shell", "input", "tap", str(mg_x), str(mg_y)],
                   capture_output=True, timeout=5)
        time.sleep(3)
        driver.take_screenshot("oa_carryout_06_search_results")

        # ── Step 5: Tap first store result ────────────────────────────────────
        print("\n  Step 5: Tap first store result")
        first_result = _find_first([
            (AppiumBy.XPATH,
             "//*[contains(@text,' miles') or contains(@content-desc,' miles')]"
             "/ancestor-or-self::*[@clickable='true'][1]"),
            (AppiumBy.XPATH,
             "//*[contains(@text,'Online ordering') or "
             "contains(@content-desc,'Online ordering')]"
             "/ancestor-or-self::*[@clickable='true'][1]"),
            (AppiumBy.XPATH,
             "//*[contains(@text,'DR') or contains(@text,'AVE') or "
             "contains(@text,'RD') or contains(@text,'BLVD') or "
             "contains(@text,'ST') or contains(@text,'HWY') or "
             "contains(@text,'WAY')]"
             "/ancestor-or-self::*[@clickable='true'][1]"),
        ], "first store result (by address)", y_min=250)

        if first_result is None:
            first_result = _find_first([
                (AppiumBy.XPATH, "//*[@clickable='true']"),
            ], "first clickable below header", y_min=300)

        if first_result is None:
            _dump_screen_elements("search results — no clickable store found")
            raise RuntimeError("OA Carryout: could not find first store result")

        addr = (first_result.get_attribute("content-desc") or
                first_result.get_attribute("text") or "")[:60]
        print(f"  Tapping store: {repr(addr)}")
        first_result.click()
        time.sleep(3)
        driver.take_screenshot("oa_carryout_07_store_selected")
        _dump_screen_elements("after store tap")

    # ── Step 6: Open scheduler
    if _carryout_home_visible:
        # Carryout home with saved store — tap the Time row to open the scheduler directly.
        print("\n  Step 6: Tapping Time row on carryout home to open scheduler")
        if not _tap_first([
            (AppiumBy.XPATH, "//*[@text='Time']"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Today at')]"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Time')]"),
        ], "Time row"):
            _dump_screen_elements("carryout home — Time row not tappable")
            raise RuntimeError("OA Carryout: could not tap Time row on carryout home screen")
        time.sleep(2)
        driver.take_screenshot("oa_carryout_08_future_order_screen")
    else:
        # Fresh store selection flow — tap "Place a future order" in the store panel.
        print("\n  Step 6: Tap 'Place a future order'")
        if not _tap_first([
            (AppiumBy.XPATH, "//*[@text='Place a future order']"),
            (AppiumBy.XPATH, "//*[@content-desc='Place a future order']"),
            (AppiumBy.XPATH, "//*[contains(@text,'future order')]"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'future order')]"),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Place a future order")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("future order")'),
        ], "Place a future order"):
            _dump_screen_elements("store panel — 'Place a future order' not found")
            raise RuntimeError("OA Carryout: 'Place a future order' button not found")

        time.sleep(2)
        driver.take_screenshot("oa_carryout_08_future_order_screen")

    # ── Step 7: Pick date and time slot ──────────────────────────────────────
    print("\n  Step 7: Select date and time slot")
    today      = datetime.now()
    day_str    = str(today.day)
    month_name = today.strftime("%B")

    # Tap "Day & Time" radio if present (some app builds show it before the calendar)
    if not _time_slots_visible():
        _tap_first([
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Day & Time')]"),
            (AppiumBy.ANDROID_UIAUTOMATOR,
             'new UiSelector().descriptionContains("Day & Time")'),
        ], "Day & Time radio (optional)")
        time.sleep(1)

    # If still no time slots, tap "Select Date" to open the calendar picker
    if not _time_slots_visible():
        if not _tap_first([
            (AppiumBy.XPATH, "//*[@text='Select Date']"),
            (AppiumBy.XPATH, "//*[@content-desc='Select Date']"),
            (AppiumBy.XPATH, "//*[contains(@text,'Select Date')]"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Select Date')]"),
            (AppiumBy.XPATH, "//*[contains(@content-desc,'Select date')]"),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Select Date")'),
            (AppiumBy.ANDROID_UIAUTOMATOR,
             'new UiSelector().descriptionContains("Select Date")'),
        ], "Select Date"):
            _dump_screen_elements("time screen — Select Date not found")
            raise RuntimeError("OA Carryout: could not find Select Date")

        driver.take_screenshot("oa_carryout_09_calendar")

        if not _tap_first([
            (AppiumBy.XPATH, f"//*[@text='{day_str}']"),
            (AppiumBy.XPATH, f"//*[contains(@content-desc,'{day_str} {month_name}')]"),
            (AppiumBy.XPATH, f"//*[contains(@content-desc,'{month_name} {day_str}')]"),
            (AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{day_str}")'),
        ], f"day {day_str} in calendar"):
            _dump_screen_elements(f"calendar — day {day_str} not found")
            raise RuntimeError(f"OA Carryout: could not select day {day_str}")

        driver.take_screenshot("oa_carryout_09b_day_selected")
        time.sleep(0.5)

        if not _tap_first([
            (AppiumBy.XPATH, "//*[@text='Ok']"),
            (AppiumBy.XPATH, "//*[@text='OK']"),
            (AppiumBy.XPATH, "//*[@content-desc='Ok']"),
            (AppiumBy.XPATH, "//*[@content-desc='OK']"),
            (AppiumBy.XPATH, "//*[contains(@text,'Ok') or contains(@text,'OK')]"),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Ok")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("OK")'),
        ], "OK"):
            _dump_screen_elements("date picker — OK not found")
            raise RuntimeError("OA Carryout: could not find OK in date picker")

    driver.take_screenshot("oa_carryout_10_time_slots")
    time.sleep(1)

    target    = today + timedelta(hours=1)
    remainder = target.minute % 15
    if remainder:
        target += timedelta(minutes=15 - remainder)
    target    = target.replace(second=0, microsecond=0)
    slot_text = target.strftime("%I:%M %p").upper()
    print(f"  Target time slot: {slot_text}")

    selected_slot = slot_text
    slot_tapped   = False

    def _slot_value(el) -> str:
        return (el.get_attribute("text") or el.get_attribute("content-desc") or "").strip()

    def _is_time_slot(val: str) -> bool:
        return bool(_re.match(r'^\d{2}:\d{2} (AM|PM)$', val))

    # Try scrolling to exact slot
    driver.driver.implicitly_wait(0)
    try:
        for uia in [
            f'new UiScrollable(new UiSelector().scrollable(true))'
            f'.scrollIntoView(new UiSelector().text("{slot_text}"))',
            f'new UiScrollable(new UiSelector().scrollable(true))'
            f'.scrollIntoView(new UiSelector().description("{slot_text}"))',
        ]:
            try:
                els = driver.driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, uia)
                if els:
                    els[0].click()
                    slot_tapped = True
                    print(f"  Selected: {slot_text}")
                    time.sleep(0.5)
                    break
            except Exception:
                pass
    finally:
        driver.driver.implicitly_wait(10)

    if not slot_tapped:
        driver.driver.implicitly_wait(0)
        try:
            for by, value in [
                (AppiumBy.XPATH, f"//*[@text='{slot_text}']"),
                (AppiumBy.XPATH, f"//*[@content-desc='{slot_text}']"),
                (AppiumBy.XPATH, f"//*[contains(@text,'{slot_text}')]"),
                (AppiumBy.XPATH, f"//*[contains(@content-desc,'{slot_text}')]"),
            ]:
                els = driver.driver.find_elements(by, value)
                if els:
                    els[0].click()
                    slot_tapped = True
                    time.sleep(0.5)
                    break
        finally:
            driver.driver.implicitly_wait(10)

    if not slot_tapped:
        print(f"  ⚠️  {slot_text} not visible — selecting first available slot")
        driver.driver.implicitly_wait(0)
        try:
            for by, value in [
                (AppiumBy.XPATH, "//*[contains(@text,' AM') or contains(@text,' PM')]"),
                (AppiumBy.XPATH,
                 "//*[contains(@content-desc,' AM') or contains(@content-desc,' PM')]"),
            ]:
                els = driver.driver.find_elements(by, value)
                time_els = [e for e in els if _is_time_slot(_slot_value(e))]
                if time_els:
                    selected_slot = _slot_value(time_els[0])
                    time_els[0].click()
                    slot_tapped = True
                    print(f"  Fell back to first slot: {selected_slot}")
                    time.sleep(0.5)
                    break
        finally:
            driver.driver.implicitly_wait(10)

    if not slot_tapped:
        _dump_screen_elements("time slots — none found")
        raise RuntimeError("OA Carryout: could not select any time slot")

    driver.take_screenshot("oa_carryout_11_slot_selected")

    if not _tap_first([
        (AppiumBy.XPATH, "//*[@text='Continue']"),
        (AppiumBy.XPATH, "//*[contains(@text,'Continue')]"),
        (AppiumBy.XPATH, "//*[@content-desc='Continue']"),
    ], "Continue"):
        _dump_screen_elements("time slots — Continue not found")
        raise RuntimeError("OA Carryout: could not find Continue")

    driver.take_screenshot("oa_carryout_12_complete")
    print(f"  ✅ Order ahead (carryout) set: {selected_slot}")
    return selected_slot


# ── Pre-step registry ─────────────────────────────────────────────────────────
# Maps YAML pre_steps entries to functions.  Each function takes (driver) and
# returns an optional string (e.g. the selected time slot for order_ahead).
PRE_STEP_REGISTRY = {
    "order_ahead":          navigate_order_ahead,
    "order_ahead_delivery": navigate_order_ahead,
    "order_ahead_carryout": navigate_order_ahead_carryout,
}


if __name__ == "__main__":
    driver = None
    try:
        driver = launch_app()
        element = scroll_to_start_voice_order(driver)
        if element:
            click_start_voice_order(driver, element)
            click_arrow_on_ready_screen(driver)
            # grant_microphone_permission(driver)
            verify_voice_agent_active(driver)
        else:
            print("\n'Start Voice Order' not found — check screen manually.")
        time.sleep(5)
    finally:
        if driver:
            driver.stop()
