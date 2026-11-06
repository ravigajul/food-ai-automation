---
name: pre-step-writer
description: >
  Generate a complete, production-ready navigate_* pre-step function for launch_and_invoke_voice.py
  from a plain-English description of the navigation steps. Applies all established patterns
  and gotchas automatically. Register the result in PRE_STEP_REGISTRY and the scenario YAML.
  Triggers on: "write a pre-step for", "add navigation for", "new pre-step", "code to navigate to",
  "add a pre-step that", "write the navigation code for".
---

# pre-step-writer — Navigation Code Generator

You are generating a new `navigate_*` function for `launch_and_invoke_voice.py`.
Apply every established pattern — the user should not need to iterate on this.

---

## Step 1 — Gather requirements

Ask (or infer from context):
1. What is the navigation goal? (e.g. "Switch to Carryout mode, enter zip 40014, select first store, pick a time slot")
2. What should the function return? (usually a selected time slot string, or None)
3. What is the YAML `pre_steps` key name? (e.g. `order_ahead_carryout`)
4. Does it need a ZIP code, store filter, or other parameter?

If any are unclear from context, ask before generating. One clarifying question is fine; don't ask several.

---

## Step 2 — Run inspect-ui at each screen checkpoint

For each distinct screen the navigation touches, run the inspect-ui dump:
```bash
adb shell uiautomator dump /sdcard/ui_dump.xml && adb pull /sdcard/ui_dump.xml /tmp/ui_dump.xml
```
Parse to confirm element classes and locators before writing code.
**Never guess locators — always verify from the dump.**

If the device isn't available, note which locators need verification and mark them with `# VERIFY`.

---

## Step 3 — Generate the function

Use this template. Fill every section from the actual element dump.

```python
def navigate_YOUR_NAME(driver: AppiumDriver, param: str = "default") -> str | None:
    """
    One-line description of what this pre-step does.

    Returns:
        str: the selected slot/value (passed to verify_order as expected_schedule)
        None: if nothing to return
    """
    import re as _re
    import subprocess as _sp
    from datetime import datetime, timedelta

    _app_pkg = driver.config["capabilities"]["appPackage"]

    # ── helpers ─────────────────────────────────────────────────────────────
    def _find_first(locators, label, y_min=0):
        """Try locators in order; return first element found at y >= y_min."""
        driver.driver.implicitly_wait(0)
        try:
            for by, val in locators:
                try:
                    els = driver.driver.find_elements(by, val)
                    for el in els:
                        r = el.rect
                        if r.get("y", 0) >= y_min:
                            print(f"  Found: {label}")
                            return el
                except Exception:
                    pass
        finally:
            driver.driver.implicitly_wait(10)
        print(f"  Not found: {label}")
        return None

    def _tap_first(locators, label):
        el = _find_first(locators, label)
        if el:
            el.click()
            return True
        return False

    def _dump_screen_elements(context):
        print(f"  [dump: {context}]")

    # ── Step 1: [describe first step] ───────────────────────────────────────
    print(f"\n  Step 1: [description]")
    # ... implementation ...
    driver.take_screenshot("nav_yourname_01_stepname")

    # ── Step 2: [describe second step] ──────────────────────────────────────
    print(f"\n  Step 2: [description]")
    # ... implementation ...

    print(f"  ✅ Navigation complete")
    return selected_value  # or None
```

### Mandatory patterns to apply

**A. Text input fields — ALWAYS use this sequence:**
```python
# 1. Find the ACTUAL EditText (not a View wrapper)
field = _find_first([
    (AppiumBy.XPATH, "//android.widget.EditText"),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().className("android.widget.EditText")'),
    # hint-based only as fallback:
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Placeholder Text']"),
], "field name")

# 2. Focus + type
field.click()
time.sleep(2.5)   # wait for keyboard — do NOT call clear() here
_sp.run(["adb","shell","input","keyevent","KEYCODE_CTRL_A"], capture_output=True, timeout=5)
_sp.run(["adb","shell","input","keyevent","KEYCODE_DEL"],    capture_output=True, timeout=5)
_sp.run(["adb","shell","input","text", value],              capture_output=True, timeout=5)
time.sleep(1)

# 3. Verify (read text attribute, not content-desc)
actual = (field.get_attribute("text") or "").strip()
if value in actual:
    print(f"  ✅ {value!r} confirmed in field")
else:
    print(f"  ⚠️  Field shows {actual!r} — proceeding anyway")
```

**B. Trigger search / submit:**
```python
_sp.run(["adb","shell","input","keyevent","KEYCODE_SEARCH"], capture_output=True, timeout=5)
time.sleep(0.3)
_sp.run(["adb","shell","input","keyevent","KEYCODE_ENTER"],  capture_output=True, timeout=5)
time.sleep(1.5)
# Fallback: tap icon at known screen-relative x
_sw = driver.driver.get_window_size()["width"]
_sp.run(["adb","shell","input","tap", str(int(_sw*0.92)), str(field_y)], capture_output=True)
```

**C. App restart to known state:**
```python
try:
    driver.driver.terminate_app(_app_pkg)
    time.sleep(3)
except Exception: pass
driver.driver.activate_app(_app_pkg)
time.sleep(7)
# Handle ANR dialog
driver.driver.implicitly_wait(0)
try:
    for _by, _val in [(AppiumBy.XPATH, "//*[@text='Wait']"),
                      (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Wait")')]:
        _els = driver.driver.find_elements(_by, _val)
        if _els:
            _els[0].click(); time.sleep(3); break
finally:
    driver.driver.implicitly_wait(10)
navigate_to_home(driver)
time.sleep(3)
```

**D. Time slot selection:**
```python
from datetime import datetime, timedelta
today  = datetime.now()
target = today + timedelta(hours=1)
remainder = target.minute % 15
if remainder:
    target += timedelta(minutes=15 - remainder)
slot_text = target.strftime("%I:%M %p").upper()
print(f"  Target slot: {slot_text}")

# Try UiScrollable first, fall back to direct find
slot_tapped = False
driver.driver.implicitly_wait(0)
try:
    for uia in [
        f'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView(new UiSelector().text("{slot_text}"))',
    ]:
        els = driver.driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, uia)
        if els:
            els[0].click(); slot_tapped = True; break
finally:
    driver.driver.implicitly_wait(10)
if not slot_tapped:
    # Fall back to first available slot
    driver.driver.implicitly_wait(0)
    try:
        els = driver.driver.find_elements(AppiumBy.XPATH, "//*[contains(@text,' AM') or contains(@text,' PM')]")
        time_els = [e for e in els if re.match(r'^\d{2}:\d{2} (AM|PM)$', (e.get_attribute("text") or "").strip())]
        if time_els:
            slot_text = time_els[0].get_attribute("text").strip()
            time_els[0].click(); slot_tapped = True
    finally:
        driver.driver.implicitly_wait(10)
if not slot_tapped:
    raise RuntimeError("Could not select any time slot")
return slot_text
```

---

## Step 4 — Register and wire up

After generating the function, make these two edits:

**In `launch_and_invoke_voice.py` — add to PRE_STEP_REGISTRY:**
```python
PRE_STEP_REGISTRY = {
    "order_ahead":          navigate_order_ahead,
    "order_ahead_carryout": navigate_order_ahead_carryout,
    "YOUR_KEY":             navigate_YOUR_NAME,   # ← add this
}
```

**In the scenario YAML — add to pre_steps:**
```yaml
pre_steps:
  - YOUR_KEY
```

---

## Step 5 — Verify locators before finishing

For every locator in the generated code that couldn't be verified from a live dump,
run inspect-ui on the relevant screen and confirm the element class and attributes match.
Replace any `# VERIFY` markers before handing back to the user.
