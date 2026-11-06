# Appium / Android Automation Rules

These are critical — violating them causes silent failures:

1. **Always use `UiScrollable` to scroll to elements**, never manual swipe coordinates:
   ```python
   driver.find_element_safe(
       AppiumBy.ANDROID_UIAUTOMATOR,
       'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView('
       'new UiSelector().descriptionContains("voice order"))',
       timeout=10
   )
   ```

2. **`is_displayed()` is unreliable** in UiAutomator2 ScrollViews — don't use it to confirm scroll success

3. **Implicit vs explicit wait conflict** — `AppiumDriver.start()` sets `implicitly_wait(10)`; always set `implicitly_wait(0)` before short timeout checks, restore in `finally`:
   ```python
   driver.driver.implicitly_wait(0)
   try:
       element = driver.find_element_safe(by, value, timeout=2)
   finally:
       driver.driver.implicitly_wait(10)
   ```

4. **Read both `@text` and `@content-desc`** — WebView/custom elements expose values via `content-desc` only; `AppiumDriver.get_visible_text_elements()` only reads `@text` and misses these

5. **Element locator casing is exact** — confirmed value is `"Start voice order"` (lowercase v, o), not `"Start Voice Order"`; always add `contains()` fallbacks

6. **`mobile: swipeGesture` bounding box** — `top + height` must not exceed screen height or the gesture is silently ignored
