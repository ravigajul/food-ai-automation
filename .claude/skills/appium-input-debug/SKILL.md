---
name: appium-input-debug
description: >
  Diagnose why an Appium element isn't accepting text input or clicks.
  Use when: typing into a field does nothing, keyboard never appears,
  send_keys/mobile:type/adb input text all fail, or a click has no effect.
  Triggers on phrases like: "can't type into", "keyboard won't show",
  "input not working", "text field not responding", "click does nothing".
---

# Appium Input Debugging — Structured Diagnostic

## The Core Lesson (from a real multi-day bug)

We spent many iterations trying `send_keys`, `mobile:type`, `adb input text`, and `adb keyevent` 
on a zip code field. All failed. Root cause: the locator matched an `android.view.View` 
with `clickable=false` (React Native accessibility wrapper) instead of the `android.widget.EditText`
inside it. One element attribute dump would have caught this in 30 seconds.

**Rule: Always dump the element's attributes BEFORE trying interaction methods.**

---

## Step 1 — Dump the element you found

The instant any input interaction fails, run this to see what element you actually have:

```python
el = <your element>
print(f"class={el.get_attribute('class')!r}")
print(f"clickable={el.get_attribute('clickable')}  focusable={el.get_attribute('focusable')}  enabled={el.get_attribute('enabled')}")
print(f"text={el.get_attribute('text')!r}  hint={el.get_attribute('hint')!r}  content-desc={el.get_attribute('content-desc')!r}")
print(f"rect: {el.rect}")
```

Or call the helper already in `src/appium_driver.py`:
```python
from src.appium_driver import diagnose_input_element
diagnose_input_element(el, "zip field")
```

---

## Step 2 — Identify the failure mode

### Failure Mode A: Wrong element class
```
class='android.view.View'   clickable=false
```
**You found an accessibility wrapper, not the actual input.**  
React Native wraps `TextInput` in a `View` that carries the `content-desc` / accessibility label.  
That `View` is `clickable=false` — click/send_keys/mobile:type all silently do nothing.

Fix: Change your locator to find `android.widget.EditText` explicitly:
```python
# BAD — finds accessibility wrapper first
(AppiumBy.XPATH, "//*[@content-desc='Zip Code']")

# GOOD — finds the actual EditText
(AppiumBy.XPATH, "//android.widget.EditText")
(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().className("android.widget.EditText")')

# GOOD — only accept clickable elements if searching by content-desc
(AppiumBy.XPATH, "//*[@content-desc='Zip Code' and @clickable='true']")
```

### Failure Mode B: Right element, focus lost between calls
```
class='android.widget.EditText'   clickable=true
```
Element is correct, but typing still doesn't work.  
**Calling `clear()` or `send_keys("")` after `click()` blurs focus** before you type.

Fix: Never call `clear()` between `click()` and typing. Use adb keyevents to clear:
```python
el.click()
time.sleep(2)   # wait for keyboard to appear — do NOT touch el again
subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_CTRL_A"], ...)
subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_DEL"], ...)
subprocess.run(["adb", "shell", "input", "text", "40014"], ...)
```

### Failure Mode C: Right element, keyboard not appearing
```
class='android.widget.EditText'   clickable=true
```
`click()` runs, no error, but keyboard never shows in screenshot.

Causes and fixes:
- The element is off-screen / under a scrollable overlay → scroll it into view first
- React Native `TextInput` with `editable={false}` → check app state
- Appium timing — increase sleep after click to 3s before typing
- Coordinate tap missed the field — use `adb shell input tap cx cy` and verify screenshot shows keyboard

---

## Step 3 — Correct pattern for React Native TextInput

This is the ONLY reliable sequence (learned from production):

```python
import subprocess

# 1. Find the ACTUAL EditText (not a View wrapper)
zip_field = driver.find_element(
    AppiumBy.ANDROID_UIAUTOMATOR,
    'new UiSelector().className("android.widget.EditText")'
)

# 2. Click via Appium — fires React Native JS onFocus, shows keyboard
zip_field.click()
time.sleep(2.5)   # keyboard must appear before we type

# 3. Clear without blurring focus (do NOT call el.clear())
subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_CTRL_A"], capture_output=True)
subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_DEL"], capture_output=True)

# 4. Type via IME — fires commitText which React Native handles
subprocess.run(["adb", "shell", "input", "text", "your_text"], capture_output=True)
time.sleep(1)

# 5. Verify — check text attribute (not content-desc)
val = zip_field.get_attribute("text") or ""
assert "your_text" in val, f"typing failed, field={val!r}"
```

**Why `adb shell input text` works when others don't:**
- `send_keys` → calls `UiObject2.setText()` → doesn't fire React Native JS events on controlled inputs
- `mobile: type` → requires field to be focused; if focus was lost (e.g. after `clear()`), types into nothing
- `adb keyevent` per digit → fires hardware key events; works but is slower and fragile
- `adb shell input text` → fires `commitText()` via IME framework → React Native `TextInput.onChangeText` fires ✅

**Triggering search after typing:**
```python
# Try keyboard search action first
subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_SEARCH"], capture_output=True)
subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_ENTER"], capture_output=True)
# Fallback: tap the search icon at known screen position
```

---

## Step 4 — Quick locator priority rules

When looking for any input field, always search in this order:

| Priority | Locator | Use when |
|---|---|---|
| 1st | `android.widget.EditText` by class | Text input — always try this first |
| 2nd | `@clickable='true'` constraint added | If multiple EditTexts exist |
| 3rd | `@hint='...'` attribute | React Native placeholder text is stored in `hint`, not `text` |
| Last | `@content-desc='...'` | Only for non-input elements (labels, buttons) |

**Never use `content-desc` as the primary locator for a text input field.**  
Content-desc is typically on the accessibility wrapper View, not the EditText.

---

## Step 5 — Verify search results came from your input

After triggering search, screenshot and confirm the results match your input.  
If results are NEARBY/GPS-based (wrong city/state), the input didn't register:

```python
driver.take_screenshot("after_search")
# Check: do results contain expected zip/city? 
results_text = [el.get_attribute("text") or el.get_attribute("content-desc") 
                for el in driver.find_elements(AppiumBy.XPATH, "//*[@text]")]
assert any("40014" in t or "Crestwood" in t for t in results_text), \
    f"Wrong results — zip not registered. Results: {results_text[:5]}"
```

---

## Time cost of skipping Step 1

| Approach | Iterations | Time lost |
|---|---|---|
| Dump attributes first, identify failure mode, apply fix | 1 | ~2 min |
| Try methods blindly (send_keys → mobile:type → keyevent → adb input text) | 8-15 | 2+ hours |
