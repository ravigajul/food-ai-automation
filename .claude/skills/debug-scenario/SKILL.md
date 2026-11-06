---
name: debug-scenario
description: >
  Diagnose a failing test scenario from logs and screenshots without re-running the test.
  Reads the latest log, identifies which phase and step failed, shows the relevant screenshot,
  cross-references source code, and suggests the exact fix. Use when a test failed and you
  want to know why. Triggers on: "why did the test fail", "debug the scenario", "what went wrong",
  "the test failed", "diagnose the failure", "check the log", "why is X failing".
---

# debug-scenario — Failure Diagnosis Without Re-Running

You are diagnosing a Acme Pizza voice test failure. Work through each step below
in order — do not skip steps, because symptoms in one phase often have root causes in another.

---

## Step 1 — Find the latest artifacts

```bash
# Latest log
ls -t <project-root>/logs/test_run_*.txt 2>/dev/null | head -3

# Latest screenshots (most recent batch = this run)
ls -t /var/folders/7z/56w071xj72qb5ctk_9tykxs40000gn/T/screenshots/*.png 2>/dev/null | head -20

# Latest HTML report
ls -t <project-root>/reports/report_*.html 2>/dev/null | head -1
```

If the user specified a log file, use that. Otherwise use the newest.

---

## Step 2 — Identify the failing phase

Read the log and extract the phase/turn where things went wrong:

```bash
# Phase summary (navigation, conversation, verification)
grep -E "PHASE|phase_status|✅|❌|Error|Exception|RuntimeError|WARNING" \
  <LOG_FILE> | head -60

# If conversation failed — find the turn where it broke
grep -E "Turn \d+|Agent:|Ravi:|DETERMINISTIC|OLLAMA|PAYMENT|CVV|WaitTimeout|break|KeyboardInterrupt" \
  <LOG_FILE> | head -80
```

Categorize the failure into one of:

| Phase | Symptom | Where to look |
|---|---|---|
| **Navigation** | `RuntimeError`, element not found, `navigate_*` crash | Screenshot before crash, `launch_and_invoke_voice.py` |
| **Conversation** | Wrong Ravi response, agent loops, state machine miss | Turn logs, `end_to_end_voice_test.py` state machine |
| **Verification** | Score < 100, items mismatched, delivery_type wrong | `verify_order.py`, ORDER COMPLETE screenshot |
| **Pre-step** | `RuntimeError: OA Carryout:`, store not found, time slot missing | Pre-step screenshots, `navigate_order_ahead*` function |

---

## Step 3 — Read the key screenshot(s)

For navigation/pre-step failures, read the screenshot taken just BEFORE the error:
- `oa_carryout_0N_*.png` — the step that preceded the crash
- `nav_retry_*.png` — if the retry loop failed

Use the Read tool to display the image and describe what's on screen.

For verification failures:
- Read `order_complete_*.png` and describe what items/delivery-type/schedule are shown
- Compare to the scenario's `expected_items` and `expected_delivery_type`

---

## Step 4 — Pinpoint the root cause

### Navigation failures — common causes:

**Element not found:**
- Run `/inspect-ui` NOW (while app is on that screen) to see what's actually there
- Check if the locator matches `@text` vs `@content-desc` (one may be empty)
- Check if element is inside a ScrollView that needs `UiScrollable`

**Element found but interaction fails:**
- Check: is the element `android.view.View` with `clickable=false`? → Accessibility wrapper — need `android.widget.EditText`
- Check: was `clear()` called between `click()` and `send_keys()`? → Blurs focus — use `adb input text` instead

**App on wrong screen:**
- `navigate_to_home()` may have failed silently → check `current_activity` in log
- ANR dialog may have appeared after app restart → look for `NexusLauncherActivity` in log

**Pre-step search returns wrong results:**
- Zip code entry likely failed → search used GPS NEARBY instead of the zip
- Verify the zip field is `android.widget.EditText` not a View wrapper

### Conversation failures — common causes:

**`[OLLAMA]` on a deterministic turn:**
- State machine pattern didn't match agent speech
- Check for Whisper mis-transcription (extra words, missing `?`, proper noun garbled)
- Rule 2–8 guard blocked a phrase that should have fired
- Fix: add the exact transcription to the trigger phrase list + add a unit test

**Agent loops / no progress on ordering:**
- `last_offer` was set incorrectly → Ollama stuck on forced choice
- `confirmed_updates` or `rejected_items` causing state machine to bypass
- Fix: check `_is_question()` and `last_offer` guard logic

**CVV bypass didn't fire:**
- Agent said CVV differently → `CVV_KEYWORD_RE` didn't match
- Check: does agent speech contain `"provide the code"` → payment bypass guard blocked it
- Fix: extend `CVV_KEYWORD_RE` with the actual transcription

**`WaitTimeoutError`:**
- Phone speaker not audible to Mac mic → physical audio loop problem, not a code bug

### Verification failures — common causes:

**Score < 100 / items mismatched:**
- QA app always shows fixed demo data → this is expected and CORRECT behaviour
- Check `expected_items` in YAML matches actual order items (not the demo data)
- Check modifier entries (no leading digit) — they are matched against Show Details text

**delivery_type wrong:**
- Pre-step didn't switch to the right mode, or verify_order scraped wrong field
- Check `overview["delivery_type"]` in log against screenshot

**scheduled_time wrong/missing:**
- PIPA TRACK screen might not have appeared (ASAP order shows no scheduled time)
- Check `schedule_ok = None` in log — this is a warning, not a failure

---

## Step 5 — Propose the fix

Based on the root cause, provide ONE of:

**A. Locator fix** — show the wrong locator, show the correct one, explain why.

**B. Interaction pattern fix** — show the wrong sequence, show the correct one.

**C. State machine fix** — show which phrase list to update, provide the exact string to add, and provide the unit test that must be added.

**D. Physical/environment fix** — if it's audio loop, device connection, or timing — tell the user what to check manually.

Always include:
- The exact line number(s) to change
- The exact code change (old → new)
- The unit test to add if it's a state machine change
- Confirmation that you ran unit tests after the fix: `python -m pytest unit_tests/ -q`

---

## Step 6 — Verify and commit

After applying the fix:

```bash
python -m pytest unit_tests/ -q
```

If all pass, commit with a one-line message describing what broke and how it was fixed.
Do NOT run the full scenario again unless the fix specifically requires it — unit tests are sufficient for state machine changes.
