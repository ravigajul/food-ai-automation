# Voice Ordering — End-to-End Test Runbook

## Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Prerequisites](#prerequisites)
4. [Physical Audio Setup](#physical-audio-setup)
5. [Running Tests](#running-tests)
   - [Single scenario (ad-hoc)](#single-scenario-ad-hoc)
   - [Test suite](#test-suite)
   - [Verify order only](#verify-order-only)
6. [Scenario YAML Reference](#scenario-yaml-reference)
7. [Personas](#personas)
8. [Reports](#reports)
9. [Project Structure](#project-structure)
10. [Troubleshooting](#troubleshooting)

---

## Overview

This framework tests the Android voice ordering experience end-to-end.
An AI customer (Ravi) navigates the app, speaks with the voice agent through the
physical audio loop, and the framework verifies the final order on the Order Complete
screen — no human interaction required after the test starts.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                        run_suite.py                             │
│                                                                 │
│  launch app (once)                                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  for each scenario.yaml                                 │   │
│  │                                                         │   │
│  │  Phase 1 ─ Navigation                                   │   │
│  │    scroll → "Start Voice Order" → arrow → verify agent  │   │
│  │    tap # → capture session ID                           │   │
│  │                                                         │   │
│  │  Phase 2 ─ AI Customer Conversation                     │   │
│  │    Ravi listens (computer mic ← phone speaker)          │   │
│  │    Ollama generates Ravi's reply                        │   │
│  │    Edge TTS speaks reply (computer speakers → phone mic)│   │
│  │    loop until order confirmed / CVV provided            │   │
│  │                                                         │   │
│  │  Phase 3 ─ Order Verification                           │   │
│  │    wait for ORDER COMPLETE screen                       │   │
│  │    scrape Overview tab (order #, total, payment)        │   │
│  │    scrape Order Details tab (full-page scroll)          │   │
│  │    keyword-match scraped items vs expected_items        │   │
│  │    generate per-scenario HTML report                    │   │
│  │                                                         │   │
│  │  navigate Home → next scenario                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│  generate suite summary report                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key design decisions

| Decision | Rationale |
|---|---|
| Single Appium session for all scenarios | Faster — avoids app restart overhead |
| Navigate Home between scenarios | Resets to a known state without full restart |
| `expected_items` in YAML (ground truth) | Eliminates Ollama from the verification critical path — no hallucination possible |
| Keyword matching (no LLM) for verification | Deterministic, reproducible, handles plural/singular and size aliases |
| Physical audio loop | Tests the real voice stack end-to-end, including TTS and STT quality |

---

## Prerequisites

### Software

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | `python --version` |
| Appium Server | 2.x | `appium --version` |
| UiAutomator2 driver | latest | `appium driver install uiautomator2` |
| Ollama | latest | `ollama --version` |
| `qwen2.5:7b` model | — | `ollama pull qwen2.5:7b` |
| ADB | latest | Included with Android SDK Platform Tools |

### Python packages

```bash
pip install -r requirements.txt
```

### Device

- Android device connected via USB with USB debugging enabled
- the pizza ordering app QA app installed: `<app-package>`
- App must be on the home screen before starting (not mid-flow)
- Verify device is visible: `adb devices`

### Start Appium

```bash
appium
```

Appium must be running on `http://localhost:4723` before any test command.

---

## Physical Audio Setup

The AI customer communicates with the voice agent through real audio — no mock.

```
  Mac (computer speakers)  ──────►  Phone (microphone)
         Ravi's TTS voice                Voice agent hears Ravi

  Phone (speaker)          ──────►  Mac (MacBook Pro Microphone)
         Voice agent speaks             Framework transcribes agent
```

**Positioning tips:**
- Place phone face-up next to the Mac speakers
- Keep ambient noise low
- Phone speaker volume: 50–70%
- Mac speaker volume: 60–80%

To use a different microphone pass `--mic "Microphone Name"` to any run command.

---

## Running Tests

### Single scenario (ad-hoc)

Run a full end-to-end test with default persona and no scenario file:

```bash
python end_to_end_voice_test.py --full
```

With a named persona:

```bash
python end_to_end_voice_test.py --full --persona rushed
```

With a free-text scenario (Ollama generates the persona on the fly):

```bash
python end_to_end_voice_test.py --full --scenario "customer who wants to add extra cheese"
```

Without screenshots in the report:

```bash
python end_to_end_voice_test.py --full --no-images
```

---

### Test suite

Run all scenarios defined in `scenarios/`:

```bash
python run_suite.py
```

Run only scenarios tagged `smoke`:

```bash
python run_suite.py --tag smoke
```

Run a single scenario by file stem or name:

```bash
python run_suite.py --scenario simple_pepperoni
python run_suite.py --scenario "Simple Pepperoni Order"
```

With a custom microphone:

```bash
python run_suite.py --mic "External Microphone" --tag smoke
```

**What happens between scenarios:**
1. The Order Complete screen is visible after verification
2. `navigate_to_home()` taps the **Home** tab in the bottom navigation bar
3. 3-second settle delay
4. The next scenario scrolls to "Start Voice Order" and relaunches the voice experience

---

### Verify order only

App is already on the Order Complete screen and you want to re-run verification
against a previous conversation log:

```bash
python end_to_end_voice_test.py --verify-only --log logs/test_run_20260218_130913.txt
```

With explicit expected items (bypasses log extraction):

```bash
python end_to_end_voice_test.py --verify-only --items "1 Large Pepperoni Pizza" "1 Order of Breadsticks"
```

---

## Scenario YAML Reference

Scenarios live in the `scenarios/` directory. Add a new `.yaml` file to create a
new test case — no code changes needed.

```yaml
# scenarios/my_scenario.yaml

# Required — human-readable name shown in reports and filtering
name: My Scenario Name

# Required — passed to Ollama to generate or guide Ravi's persona
# Use plain English to describe what the customer wants to do
description: >
  Customer wants a large pepperoni pizza with extra cheese and a side of
  garlic knots. They are polite and decisive.

# Optional — persona file from personas/ to use as the base
# Defaults to "default" if omitted
persona: default

# Required for deterministic verification — the items Ravi intends to order.
# Must match what the Order Details screen shows (flexible: singular/plural
# and size abbreviations are normalised automatically).
expected_items:
  - "1 Large Pepperoni Pizza"
  - "1 Order of Garlic Knots"

# Optional — used to filter with --tag
tags:
  - smoke
  - regression
```

### `expected_items` matching rules

The verification engine uses keyword matching — no LLM involved.

| Expected item | Will match on screen |
|---|---|
| `"1 Large Pepperoni Pizza"` | `"Large Pepperoni Pizza"`, `"1 Lg Pepperoni"` |
| `"1 Order of Breadsticks"` | `"Garlic Parmesan Breadstick"`, `"Breadsticks"` |
| `"1 2-Liter Pepsi"` | `"2-Liter Pepsi"`, `"2 Liter Pepsi"` |

Words automatically ignored: `a`, `an`, `the`, `of`, `order`, `1`–`5`, `pizza`
Size aliases: `lg` → `large`, `md` → `medium`, `sm` → `small`
Plural handling: `breadsticks` matches `breadstick` and vice versa
Pass threshold: **≥ 60%** of keywords must be found on screen

---

## Personas

Persona files live in `personas/` and define Ravi's character and ordering goals.

| File | Description |
|---|---|
| `_template.txt` | Canonical template with authoring guide — copy this to create a new persona. |
| `default.txt` | Polite, clear customer. Orders **one large pepperoni pizza** only. |
| `simple_pepperoni.txt` | Minimal single-item order — one large pepperoni pizza. |
| `combo.txt` | Orders pizza + breadsticks + 2-liter Pepsi one item at a time. |
| `rushed.txt` | Customer in a hurry, wants to order quickly with minimal back-and-forth. |
| `extra_cheese.txt` | Orders a large pepperoni pizza then requests extra cheese as a mid-order modification. |
| `modifiers_with_pizza.txt` | Orders a large pepperoni pizza then requests multiple modifications sequentially. |
| `indecisive.txt` | Hesitant customer who hedges on details but settles on pizza + breadsticks. |
| `large_order.txt` | Party order — two pepperoni, two cheese, breadsticks, garlic knots, and a Pepsi. |

To add a new persona, create `personas/my_persona.txt` and reference it in the
scenario YAML as `persona: my_persona`.

You can also skip persona files entirely and let Ollama generate one from the
scenario `description` — useful for quick one-off tests.

---

## Reports

### Per-scenario report (`reports/report_YYYYMMDD_HHMMSS.html`)

Self-contained HTML file with:

- **Header** — overall PASS/FAIL badge and score
- **Test Configuration** — persona, scenario, mic, session ID (debug)
- **Test Phases** — navigation / conversation / verification status
- **Order Verification** — score ring, matched/missing/extra items table, order overview (order #, total, payment)
- **Conversation Transcript** — full chat-bubble view of what Ravi and the agent said
- **Screenshots** — all Appium screenshots taken during the run

### Suite summary report (`reports/suite_summary_YYYYMMDD_HHMMSS.html`)

Generated after `run_suite.py` finishes. Shows a single table across all scenarios:

| Scenario | Status | Score | Matched Items | Missing Items | Duration | Report |
|---|---|---|---|---|---|---|
| Simple Pepperoni | ✅ PASS | 100 | 1 Large Pepperoni Pizza | — | 4m 12s | view |
| Combo with Sides | ❌ FAIL | 66 | … | 1 Order of Breadsticks | 5m 44s | view |

---

## Project Structure

```
pizza-voice-test/
│
├── run_suite.py                   ← suite runner (main entry point)
├── end_to_end_voice_test.py       ← single-run entry point
├── verify_order.py                ← order verification + keyword matching
├── launch_and_invoke_voice.py     ← Appium navigation steps
├── manual_voice_test.py           ← manual/standalone voice conversation
│
├── scenarios/                     ← test scenario definitions (YAML)
│   ├── simple_pepperoni.yaml
│   ├── combo_with_sides.yaml
│   ├── modification_extra_cheese.yaml
│   ├── modifiers_with_pizza.yaml
│   ├── indecisive.yaml
│   └── large_order.yaml
│
├── personas/                      ← Ravi's character profiles
│   ├── _template.txt              ← copy this to create a new persona
│   ├── default.txt
│   ├── simple_pepperoni.txt
│   ├── combo.txt
│   ├── rushed.txt
│   ├── extra_cheese.txt
│   ├── modifiers_with_pizza.txt
│   ├── indecisive.txt
│   └── large_order.txt
│
├── src/
│   ├── appium_driver.py           ← Appium session wrapper
│   ├── ollama_client.py           ← Ollama API wrapper
│   ├── scenario_monitor.py        ← per-scenario ADB log monitor
│   ├── report_generator.py        ← HTML report builder
│   └── voice_ai.py                ← TTS (Edge TTS)
│
├── config/
│   └── appium_config.yaml         ← Appium + device + Ollama config
│
├── logs/                          ← conversation transcripts (auto-generated)
├── reports/                       ← HTML reports (auto-generated)
│
└── requirements.txt
```

---

## Troubleshooting

### "Start Voice Order" button not found

- Scroll the home screen manually and confirm the button is visible
- The app may be on a different screen — restart it: `adb shell am force-stop <app-package>`
- Check the UiScrollable locator in `launch_and_invoke_voice.py:scroll_to_start_voice_order`

### Voice agent greeting not detected

- Increase phone speaker volume
- Check Whisper transcription in terminal — if the agent speech is being heard but
  not matched, add the greeting phrase to the `keywords` list in `verify_voice_agent_active`

### ORDER COMPLETE screen timeout

- The app typically takes 1–3 minutes after CVV to navigate to ORDER COMPLETE
- Default timeout is 180s — increase `timeout` in `wait_for_order_complete_screen` if needed
- Check that the order actually went through in the app manually

### Session ID shows "—" in report

- The `#` debug button may not be accessible via standard Appium locators
- Run with debug output enabled and look for **Step 7** in the terminal — it prints
  every visible element on the voice screen to identify the correct locator
- Check clipboard output before/after click — if empty, the ADB fallback log will show the error

### Items incorrectly marked as missing

- Check `expected_items` in the scenario YAML matches the spirit of what was ordered
- The keyword threshold is 60% — lower it temporarily in `_item_found_in_screen` to debug
- Add commonly missed words to `_STOP_WORDS` in `verify_order.py` if they create false negatives
  (e.g. `"order"` was added because `"1 Order of Breadsticks"` was matching on "Order Total")

### Appium connection refused

```bash
appium                          # make sure Appium is running
adb devices                     # make sure device is connected
```

### Ollama not responding

```bash
ollama serve                    # start Ollama
ollama list                     # confirm qwen2.5:7b is available
ollama pull qwen2.5:7b          # pull if missing
```
