# Pizza Voice Ordering — AI Test Automation

> **Note:** Brand, app-package and voice-agent names in this repository are fictional placeholders ("Acme Pizza", "Ava", "Pipa Dough"). To run against a real app, supply your own app package, UI locators and agent wording in `config/` and the scenario files. Credentials are never stored here.


End-to-end test automation for the Android voice ordering experience. An AI customer ("Ravi") navigates the app via Appium, holds a live conversation with the voice agent through a **physical audio loop** (Mac speakers → phone mic, phone speaker → Mac mic), and verifies the final order on the Order Complete screen — no human interaction required once the test starts.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│  run_suite.py  (or  end_to_end_voice_test.py  for one run)  │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │  1. Persona Preparation  │  Load personas/*.txt (or generate via Ollama)
          └────────────┬────────────┘
          ┌────────────▼────────────┐
          │  2. Navigation           │  Appium: launch → scroll → tap → verify agent
          └────────────┬────────────┘
          ┌────────────▼────────────┐
          │  3. AI Conversation      │  Whisper STT → state machine / Ollama → EdgeTTS
          └────────────┬────────────┘
          ┌────────────▼────────────┐
          │  4. Order Verification   │  Scrape ORDER COMPLETE → keyword match
          └─────────────────────────┘
```

### Conversation Architecture

Each agent turn is handled by the first matching layer:

| Priority | Handler | When used |
|---|---|---|
| 1 | **CVV bypass** | Agent asks for CVV / security code |
| 2 | **Payment bypass** | Agent asks to confirm card / finalize |
| 3 | **Deterministic state machine** | Predictable turns (greeting, ordering, "no extras", review) |
| 4 | **Ollama (`qwen2.5:7b`)** | Ambiguous turns (clarifying questions, rejections, variants) |

Every Ravi turn in the conversation log is tagged `[DETERMINISTIC]` or `[OLLAMA]`.

---

## Prerequisites

`pip install -r requirements.txt` installs only the **Python client libraries** (Appium-Python-Client, Whisper, SpeechRecognition, etc.). The **Appium server**, **Node.js**, **ADB**, and **Ollama** are separate native tools you must install yourself. This section covers everything from a clean machine.

> Windows users: the system tools are the same, but see the dedicated **[Windows Setup](#windows-setup)** section below for the Windows-specific commands (different requirements file, PyAudio, PATH).

### 1. Python 3.11+ and dependencies

```bash
python3 --version              # 3.11 or newer recommended
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

This pulls in Whisper + Torch (speech-to-text), EdgeTTS/pyttsx3 (text-to-speech), SpeechRecognition, PyAudio, the Appium **client**, and pytest. First install downloads Torch and the Whisper model and can take several minutes.

### 2. Node.js + Appium server + Android driver

The Appium server is a Node.js app — not a pip package:

```bash
brew install node                       # or install Node 18+ from nodejs.org
npm install -g appium                    # the Appium server CLI
appium driver install uiautomator2       # required Android automation driver
appium --version                         # verify (server CLI is on PATH)
appium driver list --installed           # confirm uiautomator2 is listed
```

> You do **not** need to start the server manually — the framework auto-starts Appium if it isn't already running (see below). But the `appium` CLI and the `uiautomator2` driver must be installed.

### 3. Android platform-tools (ADB) + device

```bash
brew install android-platform-tools      # provides `adb`
adb devices                              # device must show as "device", not "unauthorized"
```

On the phone: enable **Developer Options → USB debugging**, connect via USB, and accept the debugging prompt. The QA build `com.acmepizza.android.debug.qa` must already be installed on the device (the config uses `noReset: true` and an empty `app:` field, so the framework launches the installed app rather than reinstalling it).

### 4. Ollama + the language model

The conversation fallback uses **Ollama** running `qwen2.5:7b` locally (no llama model and no pip package involved):

```bash
brew install ollama                      # or download from ollama.com
ollama serve                             # start the server on http://localhost:11434
ollama pull qwen2.5:7b                    # one-time model download (~4.7 GB)
ollama list                              # confirm qwen2.5:7b is available
```

### 5. Enable the pre-commit hook (one-time, after cloning)

```bash
git config core.hooksPath .githooks
```

This runs `pytest unit_tests/` automatically before every commit. The hook is stored in `.githooks/` and works on Mac, Windows, and Linux.

---

### Pre-flight checks (every run)

Before starting a test, confirm the device and Ollama are ready:

```bash
adb devices                   # Android device connected with USB debugging
ollama serve                  # Ollama on http://localhost:11434 (leave running)
ollama list                   # confirm qwen2.5:7b is available
```

**Appium starts automatically** — if Appium is not already running the framework launches it, waits up to 30 seconds for it to be ready, and shuts it down when the test finishes. You can still start it manually first if you prefer:
```bash
appium                        # optional — auto-started if not running
```

**Physical audio loop** — the test uses the real audio path:
- Mac speakers play Ravi's voice → phone mic picks it up
- Phone speaker plays the agent's response → Mac mic captures it

Ensure phone speaker volume is turned up and the Mac microphone is not muted.

### Install summary

| Component | Installed by | Command |
|---|---|---|
| Python client libs (Appium client, Whisper, SR, EdgeTTS) | `requirements.txt` | `pip install -r requirements.txt` |
| Appium **server** + uiautomator2 driver | npm (manual) | `npm install -g appium` + `appium driver install uiautomator2` |
| Node.js (for Appium) | brew (manual) | `brew install node` |
| ADB / platform-tools | brew (manual) | `brew install android-platform-tools` |
| Ollama runtime + `qwen2.5:7b` model | brew + ollama (manual) | `brew install ollama`, `ollama pull qwen2.5:7b` |

---

## Windows Setup

### 1. Install Python dependencies

Use the Windows-specific requirements file — it excludes the macOS-only `pyobjc` packages:

```bat
pip install -r requirements-windows.txt
```

### 2. Install PyAudio

`PyAudio` (used by `SpeechRecognition`) requires PortAudio, which can't be installed via pip directly on Windows. Use one of these methods:

**Option A — pipwin (recommended):**
```bat
pip install pipwin
pipwin install pyaudio
```

**Option B — unofficial wheel:**
Download the pre-built `.whl` for your Python version from [Christoph Gohlke's site](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio), then:
```bat
pip install PyAudio‑0.2.14‑cp3x‑cp3x‑win_amd64.whl
```

### 3. Temp directory paths

No action needed — the code uses `tempfile.gettempdir()` which resolves automatically to `C:\Users\<you>\AppData\Local\Temp` on Windows. Directories are created on first run.

### 4. ADB on PATH

Install [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools) and add the folder to your system `PATH`, then verify:
```bat
adb devices
```

### 5. Appium server

Install Appium globally via npm (requires Node.js):
```bat
npm install -g appium
appium
```

### 6. Ollama + model

Download the Windows installer from [ollama.com](https://ollama.com/download), then in any shell:
```bat
ollama serve
ollama pull qwen2.5:7b
ollama list
```

### 7. Pre-commit hook

Run the same one-time setup command as on Mac:
```bat
git config core.hooksPath .githooks
```

The hook is a Python script so it runs natively on Windows without Git Bash. Use any shell (cmd, PowerShell, or Git Bash).

### 8. Physical audio loop

The setup is identical to macOS — Windows computer speakers → phone mic, phone speaker → Windows mic. Ensure:
- The correct microphone is selected as the default recording device in **Sound Settings → Recording**
- The `--mic` flag matches the Windows device name (run `python -c "import speech_recognition as sr; print(sr.Microphone.list_microphone_names())"` to list available mics)

---

## Running Tests

### Full test suite (all `scenarios/*.yaml`)
```bash
python run_suite.py
python run_suite.py --tag smoke                    # smoke-tagged scenarios only
python run_suite.py --scenario simple_pepperoni   # one scenario by file stem or name
python run_suite.py --mic "External Microphone"   # override microphone
python run_suite.py --config config/appium_config.testgrid.yaml   # use TestGrid config
```

### Single test run
```bash
python end_to_end_voice_test.py --full                            # default persona
python end_to_end_voice_test.py --full --persona rushed           # named persona file
python end_to_end_voice_test.py --full --scenario "customer who wants extra cheese"
python end_to_end_voice_test.py --full --cvv 123                  # override CVV
python end_to_end_voice_test.py --full --termination-trigger order_confirmed
python end_to_end_voice_test.py --full --config config/appium_config.testgrid.yaml
```

### Verify order only (app already on Order Complete screen)
```bash
python end_to_end_voice_test.py --verify-only --log logs/test_run_20260218_130913.txt
python end_to_end_voice_test.py --verify-only --items "1 Large Pepperoni Pizza" "1 Order of Breadsticks"
```

### Dialogue behavior tests (no order completion — tests Ava's conversational intent)
```bash
python run_dialogue_tests.py                          # all tests in dialogue_tests/agent_behavior.yaml
python run_dialogue_tests.py --test "Allergen"        # substring match on test name
python run_dialogue_tests.py --mic "External Microphone"
```

Each test navigates to Ava, asks the question (+ variants), and uses an Ollama LLM judge
to verify behavioral intent — no keywords, no brittle phrase matching.
HTML report saved to `reports/dialogue_<timestamp>.html`.

### Validate dialogue behavior against a recorded log (no device needed)
```bash
python test_dialogue.py                                          # auto-picks latest log
python test_dialogue.py --log logs/test_run_20260218_130913.txt
```

---

## Project Structure

```
.
├── run_suite.py                    # Suite runner — loads scenarios/*.yaml, single Appium session
├── end_to_end_voice_test.py        # Single-run entry point; conversation loop + persona prep
├── launch_and_invoke_voice.py      # All Appium navigation steps (launch, scroll, tap, verify, home)
├── verify_order.py                 # ORDER COMPLETE screen scraping + keyword matching
├── run_dialogue_tests.py           # Live dialogue intent tests — no order completion needed
├── test_dialogue.py                # Log-replay validator for dialogue behavior rules
│
├── scenarios/                      # YAML test definitions — add a file = new test case
│   ├── simple_pepperoni.yaml
│   ├── combo_with_sides.yaml
│   ├── modification_extra_cheese.yaml
│   ├── modifiers_with_pizza.yaml
│   ├── indecisive.yaml
│   └── large_order.yaml
│
├── dialogue_tests/                 # Agent behavior contract + framework tests
│   ├── agent_behavior.yaml         # Do's / don'ts for Ava — add rules here, no code changes
│
├── unit_tests/                     # All offline unit tests (no device, no Ollama needed)
│   ├── test_state_machine.py       # Conversation state machine + Ravi's deterministic responses
│   ├── test_verify_order.py        # Order verification helpers (modifier qty, keyword matching)
│   └── test_dialogue_framework.py  # Dialogue log parser + LLM-judge evaluator
│
├── personas/                       # Ravi's character profiles (plain-text system prompts)
│   ├── _template.txt               # Canonical template — copy this to create a new persona
│   ├── default.txt                 # Standard customer — pizza + garlic knots
│   ├── simple_pepperoni.txt        # Single-item order
│   ├── combo.txt                   # Pizza + breadsticks + 2-liter Pepsi
│   ├── rushed.txt                  # Customer in a hurry
│   ├── indecisive.txt              # Hesitant customer
│   ├── large_order.txt             # Party order
│   ├── extra_cheese.txt            # Mid-order modification (extra cheese)
│   └── modifiers_with_pizza.txt    # Multiple mid-order modifications
│
├── config/
│   └── appium_config.yaml          # Appium URL, device caps, Ollama model, screenshot dir
│
├── src/
│   ├── appium_driver.py            # AppiumDriver wrapper — session, find_element_safe, screenshots
│   ├── ollama_client.py            # Ollama HTTP client
│   ├── voice_ai.py                 # EdgeTTS speak_sync()
│   └── report_generator.py         # HTML report builder (per-scenario + suite summary)
│
├── logs/                           # Auto-generated conversation transcripts (git-ignored)
├── reports/                        # Auto-generated HTML reports (git-ignored)
├── RUNBOOK.md                      # Operational runbook — troubleshooting and tips
└── requirements.txt
```

---

## Scenario YAML Schema

```yaml
name: Simple Pepperoni Order        # required; used for --scenario filter and reports
description: >                      # human-readable description
  Customer orders one large pepperoni pizza.
persona: simple_pepperoni           # file stem from personas/ (default: "default")
termination_trigger: cvv            # "cvv" (default) or "order_confirmed"
cvv: "358"                          # CVV digits spoken when agent requests them
expected_items:                     # ground truth for verification
  - "1 Large Pepperoni Pizza"
tags:
  - smoke
```

`termination_trigger` values:
- `cvv` — agent asks for CVV → code speaks it → loop exits
- `order_confirmed` — saved card / Apple Pay / PayPal; exit on agent confirmation phrase

---

## Persona System

Personas are plain-text system prompts that define Ravi's character, order, and conversation behaviour.

**Two ways to supply a persona:**

| Method | Flag | Behaviour |
|---|---|---|
| Named persona file | `--persona rushed` | Loads `personas/rushed.txt` verbatim — no Ollama call |
| Free-text scenario | `--scenario "..."` | Ollama generates a persona on-the-fly |

To add a new persona: copy `personas/_template.txt`, fill in the order and conversation flow, save as `personas/<name>.txt`. No code changes needed.

---

## Configuration

`config/appium_config.yaml` is the single source of truth for all runtime settings:

| Setting | Default |
|---|---|
| Appium server URL | `http://localhost:4723` |
| App package | `<app-package>` |
| `noReset` | `true` (app state preserved between runs) |
| Screenshot directory | `<system temp>/screenshots` (resolved via `tempfile.gettempdir()`) |
| Ollama model | `qwen2.5:7b` |
| TTS voice | `en-US-JennyNeural` |

---

## Reports

All reports are saved to `reports/` (git-ignored).

**Order test reports** (`report_<timestamp>.html`) — generated by `run_suite.py`:
- Pass/fail result and score per scenario
- Phase statuses (navigation / conversation / verification)
- Matched, missing, and extra order items
- Screenshots captured during the run
- Full conversation transcript with `[DETERMINISTIC]` / `[OLLAMA]` turn tags

**Dialogue behavior reports** (`dialogue_<timestamp>.html`) — generated by `run_dialogue_tests.py`:
- Pass/fail per test rule and per question variant
- Ravi's question + Ava's captured response for each variant
- LLM judge verdict with `met_required` / `violated_forbidden` breakdown
