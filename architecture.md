# Architecture — Acme Pizza Android Voice Ordering Test Suite

## Overview

An end-to-end test framework that exercises the Acme Pizza Android voice ordering flow.
An AI customer ("Ravi") navigates the app via Appium, speaks with the live in-app voice agent
through a **physical audio loop** (Mac speakers → phone mic, phone speaker → Mac mic), and
verifies the final order on the Order Complete screen.

---

## System Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              macOS Host                                     │
│                                                                             │
│  ┌─────────────────┐    ┌──────────────────┐    ┌────────────────────────┐ │
│  │   run_suite.py  │───►│  AppiumDriver    │───►│  Appium Server         │ │
│  │   (orchestrator)│    │  (src/)          │    │  localhost:4723        │ │
│  └────────┬────────┘    └──────────────────┘    └──────────┬─────────────┘ │
│           │                                                │               │
│           │              ┌──────────────────┐             │ USB/ADB       │
│           │              │  Ollama Server   │             ▼               │
│           │              │  localhost:11434  │   ┌─────────────────────┐  │
│           │              │  qwen2.5:7b       │   │  Android Device     │  │
│           │              └────────┬─────────┘   │  Acme Pizza QA app │  │
│           │                       │ REST API     │  com.acmepizza      │  │
│           │                       │              │  .android.debug.qa  │  │
│  ┌────────▼──────────────┐        │              └──────────┬──────────┘  │
│  │  end_to_end_voice_    │        │                         │             │
│  │  test.py              │◄───────┘              Physical Audio Loop:    │
│  │  (conversation loop)  │                       Mac speakers → phone mic │
│  └────────┬──────────────┘                       Phone speaker → Mac mic  │
│           │                                                               │
│     Edge TTS (edge-tts)  ──► /tmp/pizza_voice_test/*.mp3                 │
│     SpeechRecognition    ◄── Mac microphone input                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Module Map

```
pizza-voice-test/
│
├── run_suite.py                  # Suite orchestrator — loads YAMLs, runs N scenarios
├── end_to_end_voice_test.py      # Conversation loop — Ravi's AI brain
├── launch_and_invoke_voice.py    # Appium navigation — home → voice agent
├── verify_order.py               # Order Complete screen scraper + item matcher
│
├── src/
│   ├── appium_driver.py          # AppiumDriver wrapper (YAML config, helpers)
│   ├── scenario_monitor.py       # Background logcat + activity health monitor
│   ├── report_generator.py       # HTML report generator (single + multi-scenario)
│   ├── voice_ai.py               # VoiceAI — Edge TTS synthesis (speak_sync)
│   ├── ollama_client.py          # OllamaClient — REST wrapper for local Ollama
│   ├── voice_agent.py            # (reserved)
│   ├── customer_agent.py         # (reserved)
│   └── pages/
│       └── voice_ordering_page.py
│
├── config/
│   └── appium_config.yaml        # Appium caps, timeouts, TTS voice, Ollama model
│
├── scenarios/                    # Test scenario definitions
│   ├── simple_pepperoni.yaml
│   ├── combo_with_sides.yaml
│   └── modification_extra_cheese.yaml
│
├── personas/                     # Ravi's character + order scripts
│   ├── _template.txt             # Canonical authoring guide
│   ├── default.txt
│   ├── simple_pepperoni.txt
│   ├── combo.txt
│   ├── rushed.txt
│   ├── indecisive.txt
│   ├── large_order.txt
│   └── extra_cheese.txt
│
└── logs/                         # Per-run conversation transcripts
    └── test_run_YYYYMMDD_HHMMSS.txt
```

---

## Suite Execution Flow

```
run_suite.py
     │
     ├─ load_scenarios(scenarios/*.yaml)
     │    ├─ filter: --scenario <stem|name>
     │    └─ filter: --tag <tag>
     │
     ├─ launch_app()  →  AppiumDriver (single session, reused for all scenarios)
     │
     └─ for each scenario:
          │
          ├─ PRE-FLIGHT
          │    └─ prepare_persona(scenario["persona"])
          │         ├─ named file  → load personas/<name>.txt  (no Ollama call)
          │         └─ free-text   → Ollama generates persona on-the-fly
          │
          ├─ ScenarioMonitor.start()   (background threads: logcat + activity poll)
          │
          ├─ PHASE 1 — Navigation
          │    ├─ navigate_to_home(driver)
          │    ├─ scroll_to_start_voice_order()  [retry ×3, 4s gaps]
          │    ├─ click_start_voice_order()
          │    ├─ click_arrow_on_ready_screen()
          │    └─ verify_voice_agent_active()
          │
          ├─ PHASE 2 — Conversation
          │    └─ run_ai_customer_conversation(...)  → log_file
          │
          ├─ PHASE 3 — Verification
          │    ├─ _log_has_payment_failure(log_file)?
          │    │    YES → mark failed, skip verify
          │    │    NO  → verify_order(driver, expected_items, log_file)
          │    └─ phase_statuses: { navigation, conversation, verification }
          │
          ├─ ScenarioMonitor.stop() + get_findings()
          │
          └─ navigate_to_home()  (between scenarios)
               │
               └─ [repeat for next scenario]
     │
     └─ generate_report(all_results)  →  HTML report  [always runs, even on interrupt]
          driver.stop()
```

---

## Conversation Loop (`end_to_end_voice_test.py`)

Each turn follows a strict handler priority chain. Ollama is only called if all deterministic handlers return no match.

```
Agent speech arrives (via Mac mic + SpeechRecognition)
           │
           ▼
┌──────────────────────────────────────────────┐
│  1. CVV Bypass                               │
│     CVV_KEYWORD_RE match + request word      │
│     + termination_trigger == "cvv"           │
│     → speak "My CVV is {cvv}."  then break   │
└──────────────────┬───────────────────────────┘
                   │ no match
                   ▼
┌──────────────────────────────────────────────┐
│  2. Payment Bypass                           │
│     payment phrase + "?" in agent speech     │
│     (guard: NOT asking for a code)           │
│     → speak "Yes, please go ahead."  continue│
└──────────────────┬───────────────────────────┘
                   │ no match
                   ▼
┌──────────────────────────────────────────────┐
│  3. State Machine (_get_deterministic_       │
│     response)                                │
│                                              │
│  Tracks: items_ordered_idx, rejected_items,  │
│          confirmed_updates, last_offer       │
│                                              │
│  Patterns (in priority order):               │
│   • Turn 1 greeting → "Hi, I'd like..."     │
│   • "Anything else?" + items remain          │
│     → "And {next item} please."              │
│   • "Anything else?" + all done              │
│     → "No, that's all, thank you."           │
│   • Order prompt → "I'd like {next item}."  │
│   • Order review → "Yes, that's right."     │
│   • Short ack (≤10 words, no ?) → "Okay."  │
│   • "added" statement → "Okay, thanks."     │
│   • All items done + non-question → "Okay." │
│                                              │
│  Skipped entirely if rejected_items set      │
└──────────────────┬───────────────────────────┘
                   │ no match
                   ▼
┌──────────────────────────────────────────────┐
│  4. Ollama Fallback (qwen2.5:7b)             │
│     temp=0.1, max_tokens=80                  │
│                                              │
│  Injected constraints (top of prompt):       │
│   • rejected_items  — never re-request       │
│   • confirmed_updates — don't repeat         │
│   • last_offer — pick specific option        │
│                                              │
│  Loop detection: identical last 2 responses  │
│   → inject "give a COMPLETELY DIFFERENT..."  │
│                                              │
│  Output cleaned by _clean_ravi_response()    │
└──────────────────────────────────────────────┘
           │
           ▼
  Ravi speaks via Edge TTS (speak_sync)
  → /tmp/pizza_voice_test/<hash>.mp3
  → afplay (macOS) plays through speakers
  → phone mic picks up audio  [physical loop]
```

### Termination Conditions

| Trigger | Condition |
|---|---|
| Agent goodbye | `"exit"` or `"goodbye"` in agent speech |
| Order confirmed | Phrase matches `order_complete_phrases` list |
| CVV bypass | Agent asks for CVV + `termination_trigger == "cvv"` |
| Ravi goodbye | `"goodbye"` or `"thanks, bye"` in Ravi's response |
| Timeout | No speech within 45 s (`sr.WaitTimeoutError`) |
| Keyboard interrupt | Ctrl+C |

---

## Order Verification (`verify_order.py`)

```
verify_order(driver, expected_items, log_file)
     │
     ├─ Navigate to Order Complete screen (Appium)
     │    ├─ Overview tab  → order number, payment card, totals
     │    └─ Order Details tab → individual items (scrolled fully)
     │
     ├─ Scrape all text + content-desc elements from screen
     │
     ├─ Keyword matching (60% threshold)
     │    ├─ Normalise size aliases: lg→large, md→medium, sm→small
     │    ├─ Strip stop words: a, an, the, of, order, digits, ...
     │    └─ Score each expected_item against scraped text
     │
     └─ Return: { passed, score, matched_items, missing_items,
                  extra_items, reasoning, overview }
```

No Ollama call during verification — keyword matching only.
`expected_items` from the scenario YAML is always ground truth.

---

## Background Monitoring (`src/scenario_monitor.py`)

Two threads run in parallel with each scenario:

| Thread | What it does |
|---|---|
| **Logcat thread** | `adb logcat` pipe; flags lines matching crash/ANR/exception patterns; tags each finding to the active phase |
| **Health thread** | Polls `current_activity` every 5 s; records activity changes; warns if app leaves foreground |

Findings are attached to the result dict and surfaced in the HTML report's Health Monitor section.

---

## Configuration (`config/appium_config.yaml`)

| Section | Key settings |
|---|---|
| `appium` | `server_url: http://localhost:4723` |
| `capabilities` | `appPackage`, `appActivity`, `noReset: true`, `automationName: UiAutomator2` |
| `timeouts` | `implicit_wait: 10`, `explicit_wait: 15` |
| `test` | `screenshot_dir: /tmp/screenshots`, `audio_dir: /tmp/pizza_voice_test` |
| `voice_ai` | `tts_voice: en-US-JennyNeural` |
| `ollama` | `base_url: http://localhost:11434`, `model: qwen2.5:7b` |

---

## Scenario YAML Schema

```yaml
name: Simple Pepperoni             # required; used for filtering and reports
persona: simple_pepperoni          # optional; file stem from personas/ (default: "default")
termination_trigger: cvv           # "cvv" (default) | "order_confirmed"
cvv: "358"                         # optional; spoken when agent requests CVV
expected_items:                    # ground truth for verification
  - "1 Large Pepperoni Pizza"
tags:
  - smoke
```

---

## Persona System

Personas are plain-text system prompts that define Ravi's character and order script.

```
personas/_template.txt   ← canonical authoring guide
personas/<name>.txt      ← loaded verbatim; no Ollama call
                          ← machine-parsed sections:
                             "Your Order:" → items_ordered_idx state machine
```

Free-text scenario path (CLI `--scenario "..."` only):
Ollama generates a conforming persona from `PERSONA_GENERATOR_SYSTEM` prompt,
then falls back to `default.txt` on failure.

---

## External Dependencies

| Dependency | Role |
|---|---|
| Appium Server (localhost:4723) | UiAutomator2 driver for Android UI control |
| ADB / Android device | USB-connected device running QA build |
| Ollama (localhost:11434, qwen2.5:7b) | Ravi's AI brain for ambiguous turns; optional persona generation |
| edge-tts | Neural TTS — synthesises Ravi's speech to MP3 |
| SpeechRecognition + Google STT | Transcribes phone speaker audio captured by Mac mic |
| afplay (macOS) | Plays MP3 through Mac speakers into phone mic |

---

## Output Artifacts

| Artifact | Location | Contents |
|---|---|---|
| Conversation log | `logs/test_run_YYYYMMDD_HHMMSS.txt` | Full transcript with `[DETERMINISTIC]`/`[OLLAMA]` tags |
| Screenshots | `/tmp/screenshots/*.png` | Step-by-step screen captures, cleared per scenario |
| HTML report | `reports/` (or configurable) | Summary table + per-scenario phases, health monitor, embedded screenshots |
