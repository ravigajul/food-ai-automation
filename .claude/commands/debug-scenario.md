# Debug Scenario

Debug a failing `run_suite.py` scenario using a tight read-screenshot → inspect-UI → fix → rerun loop.

**Usage:** `/debug-scenario <scenario_name>`  
**Example:** `/debug-scenario order_ahead_pepperoni`

---

## Before You Start — Kill Stale Processes

**Always do this before every debug run.** Multiple simultaneous instances produce overlapping audio, echo loops, and misleading logs.

```bash
# Check what's already running
ps aux | grep -E "(run_suite|end_to_end|afplay)" | grep -v grep

# Kill any stale instances (user must run this — Claude cannot pkill without approval)
# kill <pid1> <pid2> ...; pkill -x afplay
```

If you see more than one `run_suite.py` process, **stop and ask the user to kill the old PIDs before proceeding.** Never start a new background run while old ones are alive.

**Never run scenarios in the background** (`run_in_background: true`) — orphaned audio processes accumulate silently and cause phantom voices. Always run in the foreground with a timeout.

---

## Loop

Repeat until the scenario passes or you exhaust 5 iterations:

### 1. Run (foreground only)
```bash
source .venv/bin/activate && python run_suite.py --scenario $ARGUMENTS 2>&1
```

### 2. Triage the failure

- **Exception in the output** → read the traceback. Identify which function and line failed.
- **"not found" / locator error** → go to step 3 (inspect UI).
- **Screenshot available** → read the most recent screenshot to see what screen the app is on.
- **Conversation loop symptoms** → see Audio / Echo section below.

Find the latest screenshots:
```bash
ls -t /var/folders/*/T/screenshots/*.png 2>/dev/null | head -5
```

Check the conversation log for turn-by-turn dialogue:
```bash
ls -t logs/*.txt | head -1
```

### 3. Inspect the live UI (when locator fails)

Run inspect-ui to see what's actually on screen:
```bash
source .venv/bin/activate && python inspect_ui.py --clickable 2>&1
```

If looking for a specific element:
```bash
source .venv/bin/activate && python inspect_ui.py --filter "<keyword>" 2>&1
```

### 4. Fix

**Navigation / locator failures:**

| Symptom | Fix |
|---|---|
| Element not found | Update locator in `launch_and_invoke_voice.py` with exact `content-desc` or `text` from inspect output |
| Wrong screen after tap | Add/fix navigation check; update intermediate step |
| Tap found right element but didn't navigate | Use `mobile: clickGesture` at the **chevron** (right edge of element) — `el.click()` and centre-tap both fail silently on this React Native delivery row |
| Deal/banner matched instead of target | Narrow locator (add class constraint or full phrase) |
| Screenshot shows dialog/modal | Add dismiss step before the failing action |
| Delivery header shows "Today at HH:MM" not "ASAP" | `noReset:true` retains state — match on `contains(@content-desc,'DELIVERY')` only, not the time chip |
| Time slots not visible despite Day & Time selected | Guard calendar/slot steps with `_time_slots_visible()` check — app may already show slots |

**Audio / conversation loop failures:**

| Symptom | Root cause | Fix |
|---|---|---|
| Ravi says "Okay, thanks." in a loop | Echo of Ravi's voice captured as Ava's speech; Rule 8 fires again | Check `calibration duration` in listen block (must be ≥ 1.0 s when `ravi_just_spoke`); check echo guard threshold |
| Ravi responds before Ava finishes | `pause_threshold` too short or calibration window too short after Ravi speaks | `pause_threshold` ≥ 1.5 s short turns, ≥ 1.8 s long turns; calibration ≥ 1.0 s post-speak |
| Multiple voices / overlapping audio | Stale `afplay` orphans from prior interrupted runs | Kill all old PIDs first (see Before You Start); `pkill -x afplay` |
| Ravi immediately orders without greeting | Echo of Ravi's greeting captured and Ollama responds to it | Echo guard (`last_ravi_response` Jaccard ≥ 0.7) should catch; if not, increase calibration duration |
| "Okay, thanks." loop persists after echo fix | Same response repeating back-to-back | Check `last_ravi_response` tracking — must be set at ALL four speak sites (CVV, payment, deterministic, Ollama) |

Key files:
- Navigation steps: `launch_and_invoke_voice.py` → `navigate_order_ahead()`
- Conversation loop: `end_to_end_voice_test.py` → `run_ai_customer_conversation()`
- Audio playback / orphan kill: `src/voice_ai.py` → `speak()` → `Popen` + `kill()`
- Screenshot dir: check `driver.config["test"]["screenshot_dir"]` in `config/appium_config.yaml`

### 5. Write tests, then verify and repeat

**Tests are part of the fix — write them before moving on:**
- New state machine rule or branch → test in `test_state_machine.py`
- New helper function → extract it so it's importable, then test it
- Bug fix → add a test using the real failure input as the test case

```bash
source .venv/bin/activate && python -m pytest unit_tests/ -q
```

After tests pass, go back to step 1.

---

## Rules

- **Kill stale processes first** — always check `ps aux` before starting a run.
- **Never use `run_in_background`** for scenario runs — orphaned audio processes are invisible and hard to diagnose.
- Read each failure screenshot before changing any code — the screenshot tells you where the app actually is.
- Never guess a locator. Always confirm via `inspect_ui.py` output or screenshot.
- When a tap does nothing: check `_on_delivery_options_panel()` / `_on_delivery_time_screen()` logic first — the tap may have worked but the navigation check was wrong.
- Fix one step at a time. Don't refactor surrounding code while fixing a locator.
- After fixing audio/echo issues: read the conversation log (`logs/test_run_*.txt`) to confirm Ravi and Ava turns alternate correctly before declaring success.
