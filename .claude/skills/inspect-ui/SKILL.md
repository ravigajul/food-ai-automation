---
name: inspect-ui
description: >
  Dump and analyze the current screen's element tree from the connected Android device.
  Generates ready-to-use Appium locators and flags React Native input pitfalls.
  Use when: writing new navigation code, a locator isn't working, you want to know
  what elements exist on a screen, or you need the correct way to interact with
  a specific UI element. Triggers on: "inspect the screen", "what's on screen",
  "what elements are on", "find locator for", "dump ui", "what is the element for",
  "show me the element tree", "inspect ui".
---

# inspect-ui — Live Screen Element Inspector

You are inspecting the Android device's current screen to generate correct Appium
locators and identify interaction patterns. Navigate the phone to the screen you want
to inspect FIRST, then run this skill.

---

## Step 1 — Check device

```bash
adb devices 2>/dev/null | grep -v "List of devices" | grep "device$" \
  && echo "ADB: device connected" || echo "ADB: no device"
```

If no device, stop and tell the user to connect via USB with USB debugging enabled.

---

## Step 2 — Dump and pull the element tree

```bash
adb shell uiautomator dump /sdcard/ui_dump.xml 2>&1
adb pull /sdcard/ui_dump.xml /tmp/ui_dump.xml 2>&1
```

---

## Step 3 — Parse and display

Run this Python inline (do NOT create a file):

```bash
python3 - <<'PYEOF'
import xml.etree.ElementTree as ET, sys

try:
    tree = ET.parse('/tmp/ui_dump.xml')
except Exception as e:
    print(f"Parse failed: {e}"); sys.exit(1)

ROOT = tree.getroot()

def attr(node, *names, default=''):
    for n in names:
        v = node.get(n, '')
        if v and v != 'null': return v
    return default

def parse_bounds(b):
    # "[x1,y1][x2,y2]" → (x, y, w, h)
    try:
        parts = b.replace('][',',').strip('[]').split(',')
        x1,y1,x2,y2 = int(parts[0]),int(parts[1]),int(parts[2]),int(parts[3])
        return x1, y1, x2-x1, y2-y1
    except:
        return 0,0,0,0

print(f"\n{'='*70}")
print("INTERACTIVE ELEMENTS (clickable=true OR EditText)")
print(f"{'='*70}")

input_elements = []
for node in ROOT.iter():
    cls       = attr(node, 'class')
    clickable = attr(node, 'clickable')
    focusable = attr(node, 'focusable')
    enabled   = attr(node, 'enabled')
    txt       = attr(node, 'text')
    desc      = attr(node, 'content-desc')
    hint      = attr(node, 'hint')     # React Native placeholder lives here
    rid       = attr(node, 'resource-id')
    bounds    = attr(node, 'bounds')
    x,y,w,h   = parse_bounds(bounds)

    is_edit  = 'EditText' in cls
    is_click = clickable == 'true'
    if not (is_edit or is_click):
        continue

    label = txt or desc or hint or rid or ''
    short_cls = cls.split('.')[-1] if '.' in cls else cls

    # Determine interaction type
    if is_edit:
        interaction = "✏️  TEXT INPUT — use: el.click() + sleep(2.5) + adb input text '...'"
    elif 'Button' in cls:
        interaction = "🔘 BUTTON    — use: el.click()"
    elif is_click:
        interaction = "👆 CLICKABLE — use: el.click()"
    else:
        interaction = "❓ UNKNOWN"

    # Warn if this is a View wrapper (looks like input but isn't)
    if not is_edit and clickable == 'false' and focusable == 'true':
        interaction += "  ⚠️  focusable but NOT clickable — accessibility wrapper"

    print(f"\n[{short_cls}]  {interaction}")
    if label:
        print(f"  label    : {label!r}")
    if hint:
        print(f"  hint     : {hint!r}  ← React Native placeholder (NOT text attr)")
    if rid:
        print(f"  res-id   : {rid!r}")
    print(f"  attrs    : clickable={clickable}  focusable={focusable}  enabled={enabled}")
    print(f"  bounds   : x={x} y={y} w={w} h={h}  (center: {x+w//2},{y+h//2})")

    # Generate locators (best first)
    locators = []
    if is_edit:
        if hint:
            locators.append(f'AppiumBy.XPATH, "//android.widget.EditText[@hint={hint!r}]"')
        locators.append(f'AppiumBy.ANDROID_UIAUTOMATOR, \'new UiSelector().className("android.widget.EditText")\'')
        if rid:
            locators.append(f'AppiumBy.ID, {rid!r}')
    else:
        if txt:
            locators.append(f'AppiumBy.XPATH, "//*[@text={txt!r}]"')
        if desc:
            locators.append(f'AppiumBy.XPATH, "//*[@content-desc={desc!r}]"')
        if rid:
            locators.append(f'AppiumBy.ID, {rid!r}')
        if txt:
            locators.append(f'AppiumBy.ANDROID_UIAUTOMATOR, \'new UiSelector().text({txt!r})\'')
    for i,loc in enumerate(locators, 1):
        print(f"  locator{i} : {loc}")

    input_elements.append({'class':cls,'label':label,'bounds':(x,y,w,h),'is_edit':is_edit})

print(f"\n{'='*70}")
print(f"SUMMARY: {len(input_elements)} interactive elements found")
is_edit_count = sum(1 for e in input_elements if e['is_edit'])
if is_edit_count:
    print(f"  {is_edit_count} EditText (text input) — ALWAYS use android.widget.EditText locator")
print(f"{'='*70}\n")
PYEOF
```

---

## Step 4 — Interpret and advise

After the dump, answer:
1. **"Is there an EditText on this screen?"** — If yes, provide the correct locator and interaction pattern.
2. **"Is there a View with content-desc that looks like an input?"** — Warn: this is an accessibility wrapper, not an input. Point to the EditText instead.
3. **"What locator should I use for element X?"** — Give the highest-confidence locator from the dump.

### React Native input rule (most important)
If you see BOTH of these on the same screen:
- `android.view.View` with `content-desc='Zip Code'` (clickable=false)  
- `android.widget.EditText` with `hint='Zip Code'` (clickable=true)

**Always use the EditText locator.** The View is the accessibility wrapper. Clicking it does nothing.

### Correct typing pattern for any EditText found:
```python
el = driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,
    'new UiSelector().className("android.widget.EditText")')
el.click()           # fires React Native JS onFocus + shows keyboard
time.sleep(2.5)      # wait for keyboard — do NOT call clear()
import subprocess
subprocess.run(["adb","shell","input","keyevent","KEYCODE_CTRL_A"], capture_output=True)
subprocess.run(["adb","shell","input","keyevent","KEYCODE_DEL"], capture_output=True)
subprocess.run(["adb","shell","input","text", "your_text_here"], capture_output=True)
time.sleep(1)
```

---

## Step 5 — Optional: screenshot for visual reference

```bash
adb shell screencap -p /sdcard/current_screen.png
adb pull /sdcard/current_screen.png /tmp/current_screen.png
```

Then Read `/tmp/current_screen.png` to show the user what's on screen.
