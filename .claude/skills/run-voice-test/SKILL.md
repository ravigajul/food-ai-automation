---
name: run-voice-test
description: >
  Runs the Acme Pizza Android voice ordering test suite end-to-end. Use this skill
  whenever the user wants to run voice tests, execute a scenario, test a persona,
  run smoke tests, re-run a failed scenario, or check if the ordering flow works.
  Also handles failure interpretation when the user shares a log or asks why a test
  failed. Triggers on phrases like: "run the voice test", "run scenario X", "run all
  scenarios", "run smoke tests", "test with persona X", "why did this test fail",
  "interpret this log", "what went wrong".
---

# Run Voice Test Skill

You are running and/or interpreting Acme Pizza Android voice ordering tests. This is a
physical audio loop test: Ravi (AI customer) speaks via computer speakers → phone mic →
voice agent responds → phone speaker → Mac mic → Ravi listens.

## Step 1: Prerequisites Check

Before running anything, verify all services are up. Run these checks automatically — do NOT ask the user to do them manually.

```bash
# 1. Appium server
curl -s http://localhost:4723/status | python3 -c "import sys,json; s=json.load(sys.stdin); print('Appium: OK' if s.get('value',{}).get('ready') else 'Appium: NOT READY')" 2>/dev/null || echo "Appium: NOT RUNNING"

# 2. ADB device
adb devices 2>/dev/null | grep -v "List of devices" | grep "device$" && echo "ADB: device connected" || echo "ADB: no device found"

# 3. Ollama + model
curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; tags=json.load(sys.stdin); models=[m['name'] for m in tags.get('models',[])]; print('Ollama: OK, models:', models)" 2>/dev/null || echo "Ollama: NOT RUNNING"
```

If any prerequisite fails, report clearly what is missing and stop. Do not proceed with a broken environment.

## Step 2: Microphone Selection

List all available microphones automatically:

```bash
cd <project-root> && python3 -c "
import speech_recognition as sr
mics = sr.Microphone.list_microphone_names()
for i, name in enumerate(mics):
    print(f'  [{i}] {name}')
"
```

Then select the microphone:
- If the user specified a mic name (e.g. "use External Microphone", "Windows mic", "USB audio") — use that name as `--mic`
- If no mic specified — use `"MacBook Pro Microphone"` as the default
- If the listed mics contain something matching "external", "usb", or "windows" and the user hinted at a remote/Windows machine — prefer that one
- Always pass `--mic` explicitly so there is no ambiguity

## Step 3: Build and Execute the Command

### Running the full suite (`run_suite.py`)
Use when the user says "run all", "run the suite", "run smoke tests", or gives a tag:

```bash
cd <project-root> && python run_suite.py \
  [--scenario <stem>] \   # optional: simple_pepperoni, combo_with_sides, modification_extra_cheese
  [--tag <tag>] \         # optional: smoke
  --mic "<mic name>"
```

### Running a single scenario end-to-end (`end_to_end_voice_test.py`)
Use when the user specifies a persona, a free-text scenario description, or explicit flags:

```bash
cd <project-root> && python end_to_end_voice_test.py --full \
  [--persona <name>] \                         # e.g. rushed, default, combo, indecisive
  [--scenario "<free text description>"] \     # generates persona via Ollama on-the-fly
  [--cvv <digits>] \                           # default: 358
  [--termination-trigger cvv|order_confirmed] \# default: cvv
  --mic "<mic name>"
```

Always `cd` to the project root before running. Run via Bash — do not just print the command.

## Step 4: Monitor and Interpret Output

Watch the output as it runs. After completion, interpret results using these patterns:

### Failure Patterns

| What you see | Root cause | What to tell the user |
|---|---|---|
| `Items mismatched` / score < 100 | QA app always shows fixed demo data — this is expected | "This is a known QA limitation — ORDER COMPLETE always shows the same demo items regardless of conversation. The test correctly detected a mismatch. This is not a framework bug." |
| `[OLLAMA]` turns dominating (>50% of turns) | State machine not matching agent phrases | "The state machine isn't matching the agent's speech. Check agent phrasing against patterns in `.claude/rules/conversation-flow.md`." |
| `[PAYMENT FAILED` in log | Payment processing failed mid-conversation | "Payment failed during the conversation. Check the physical audio loop and verify CVV was spoken correctly." |
| `WaitTimeoutError` / Timeout after 45s | STT not hearing the phone | "STT timed out — the microphone isn't picking up the phone speaker. Check the physical audio loop and mic index." |
| `NoSuchElementException` | Appium can't find a UI element | "Appium lost a UI element — the app may be on an unexpected screen. Check the element's `content-desc` casing and scroll state." |
| `Microphone '...' not found, using default` | Mic name didn't match | "The specified microphone name wasn't found. Re-list mics and pick the exact name." |
| `Ollama: NOT RUNNING` | Ollama server down | "Start Ollama: `ollama serve` in a separate terminal." |
| `Appium: NOT RUNNING` | Appium server down | "Start Appium: `appium` in a separate terminal." |
| `no device found` | ADB not connected | "Connect the Android device via USB and enable USB debugging, or check `adb devices`." |
| `REJECTED` in log + Ollama handling CVV/payment | `rejected_items` non-empty → state machine bypassed | "An item was rejected by the agent, which bypassed the state machine. Ollama is now handling all turns including payment/CVV. Check log for `REJECTED` lines." |

### Reading the Log

After a run, the log is at `logs/test_run_<timestamp>.txt`. Look for:
- `[DETERMINISTIC]` — state machine handled the turn (good, predictable)
- `[OLLAMA]` — Ollama handled the turn (only expected for ambiguous agent questions)
- `[PAYMENT FAILED` — payment error
- `REJECTED` — an item was rejected; state machine is now bypassed for all turns

Report the ratio of `[DETERMINISTIC]` vs `[OLLAMA]` turns and highlight any anomalies.

## Available Scenarios

| File stem | Description | Tags |
|---|---|---|
| `simple_pepperoni` | One large pepperoni pizza, basic happy path | smoke |
| `combo_with_sides` | Combo order with sides and drinks | — |
| `modification_extra_cheese` | Pizza with extra cheese modification | — |

## Available Personas

`default`, `simple_pepperoni`, `combo`, `rushed`, `indecisive`, `large_order`, `extra_cheese`

## Termination Trigger Reference

- `cvv` (default) — credit card flow; exits when agent asks for CVV and Ravi speaks it
- `order_confirmed` — saved card / Apple Pay / PayPal; exits when agent confirms order
