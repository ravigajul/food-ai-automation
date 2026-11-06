# CLAUDE.md

End-to-end test automation for Acme Pizza Android voice ordering. An AI customer ("Ravi") navigates the app via Appium, speaks with the live voice agent through a **physical audio loop** (computer speakers → phone mic, phone speaker → Mac mic), and verifies the final order on the Order Complete screen.

## Prerequisites

```bash
appium                  # Appium server on http://localhost:4723
adb devices             # Android device with USB debugging
ollama serve            # Ollama on http://localhost:11434
ollama list             # confirm qwen2.5:7b is available
pip install -r requirements.txt
```

## Running Tests

```bash
python end_to_end_voice_test.py --full
python end_to_end_voice_test.py --full --persona rushed
python end_to_end_voice_test.py --full --scenario "customer who wants extra cheese"
python end_to_end_voice_test.py --full --cvv 123 --termination-trigger order_confirmed
python end_to_end_voice_test.py --verify-only --log logs/test_run_20260218_130913.txt
python run_suite.py
python run_suite.py --tag smoke
python run_suite.py --scenario simple_pepperoni --mic "External Microphone"
python run_suite.py --config config/appium_config.testgrid.yaml
python end_to_end_voice_test.py --full --config config/appium_config.testgrid.yaml
```

## Token Efficiency Rules

- **Never glob `.venv/`** — always scope to `src/**/*.py`, `*.py`, etc.
- **Grep before Read** — find the relevant section first, then read with offset/limit
- **Read in chunks** — use `offset` + `limit` on large files; don't read the whole file unless necessary
- **Parallel tool calls** — always fire independent reads/globs in the same message

## Critical Gotchas

- **QA app fixed demo orders** — ORDER COMPLETE always shows the same demo data regardless of conversation. Tests failing due to item mismatch are **correctly detecting a failure** — not a framework bug.
- **`expected_items` in YAML is ground truth** — verification never calls Ollama; uses keyword-matching at 60% threshold against scraped screen text.
- **`navigate_to_home()` before each scenario** — `run_suite.py` calls this at the start of every scenario; retries scroll up to 3× with 4 s pauses for the home banner to load.
- **Ollama model** — always use `_load_ollama_model()` from `config/appium_config.yaml`; never rely on `OllamaClient`'s hardcoded `llama3.2` default.
- **Extensibility** — see `extensibility_plan.md` in memory for the full feature roadmap (order_ahead done; loyalty PIN, Apple Pay, deal_genie, quick_reorder remaining).

## Whisper Transcription Gotchas (state machine bugs live here)

Whisper produces imperfect transcriptions. Every question-detection and keyword-match in the state machine must account for these:

### 1. Whisper omits `?` on questions
**Never use `"?" in agent_speech` as the sole question detector.**
Always call `_is_question(agent_speech, agent_lower)` — it checks `?`, question-starter words (`how`, `do`, `would`, `are`, `is`, `what`, `which`, …), and known question phrases (`does that`, `is that correct`, `how much`, `do you`, etc.).

Bad:
```python
if "?" in agent_speech and any(p in agent_lower for p in PHRASES):
```
Good:
```python
if _is_question(agent_speech, agent_lower) and any(p in agent_lower for p in PHRASES):
```

### 2. Whisper mis-transcribes proper nouns — use regex, not exact strings
"Pipa Dough" has been transcribed as: `pipa dough`, `pipa doe`, `pipa delo`, `pipa doo`, `pop a dough`, `Pipadot`, `Pop-a-Doh`, `Pompa Do`.
Use `_PIPA_D_RE` (defined in `end_to_end_voice_test.py`) — a compiled regex that catches all variants via three general patterns:
- `\bp\w{0,3}pa\s+d\w*\b` — space-separated: pipa/popa/pompa + any d-word
- `\bpop[-\s]a[-\s]d\w*\b` — split/hyphenated: pop a / pop-a + d-word
- `\bpipadot\b` — fully merged single word

Never add a new exact-string phrase for a Acme Pizza product name without also adding a regex fallback. If a new variant doesn't match, extend the regex — don't add a one-off string.

### 3. "would you like" / "do you want" are yes/no phrases — not option selectors
`last_offer` (the Ollama "pick one option" constraint) must only be set when actual choices are present.
Ambiguous phrases like `"would you like"` and `"do you want"` require `" or "` or a size/flavor word also in the speech.
Unambiguous choice phrases (`"which size"`, `"what flavor"`, `"which one"`, etc.) always set `last_offer`.

Bad: setting `last_offer` for `"Would you like to add a tip?"`
Good: only set it for `"Would you like original or garlic parmesan?"`

### 4. "how much / how many" are quantity questions — not option selectors
Guard `last_offer` with `not re.search(r'\bhow (much|many)\b', agent_lower)`.
`"How much pipa dough would you like to use?"` is NOT an option-selection prompt.

### 5. Every new agent question type needs a deterministic handler
Agents ask off-script questions (loyalty, tips, gratuity) that Ollama will hallucinate on.
Add a deterministic rule to `_get_deterministic_response()` before letting Ollama handle it.
Current handlers: loyalty/pipa dough (Rule 2b), tip/gratuity (Rule 5b).

### 6. Echo-decay sleep must be BEFORE opening the mic, not inside it
`adjust_for_ambient_noise(source, duration=N)` consumes `N` seconds of live audio — any agent speech during calibration is lost. The old pattern (`duration=1.0` inside `with sr.Microphone()`) ate the first second of the agent's response, causing `[Agent speech too short — skipped]`.

**Correct pattern:**
```python
if ravi_just_spoke:
    time.sleep(0.8)           # echo decay — mic not open, no audio consumed
with sr.Microphone(...) as source:
    if ravi_just_spoke:
        adjust_for_ambient_noise(source, duration=0.2)  # threshold reset only
        ravi_just_spoke = False
    audio = recognizer.listen(...)
```
Total dead time is the same (~1 s), but only 0.2 s of agent audio is at risk instead of 1.0 s.

### 7. Payment statements are two-part sentences — SR captures the first half
Agent speech like `"A total of $25 will be charged to your card ending in 1234, and if that's correct, would you like to proceed?"` arrives in **two SR chunks**:
- Chunk 1: `"A total of $25 will be charged to your card ending in 1234"` — no `?`, looks like a statement
- Chunk 2: `"...and if that's correct, would you like to proceed?"` — the actual question

**Never let a catch-all rule (e.g. Rule #8 "all items ordered + non-question → Okay thanks") fire on payment/charge/card-ending phrases.** Guard those rules with `_PAYMENT_CONTEXT_RE` so the first chunk falls through to Ollama rather than triggering a premature "Okay, thanks." that interrupts the agent mid-sentence.

When adding ANY new catch-all or "statement after all items ordered" rule, ask: *"Could the agent say a payment question whose first half looks like this statement?"* If yes, add the payment phrases to the guard.

## Unit Test Suite (`unit_tests/`)

All unit tests live in `unit_tests/` — no device, no Ollama, no Appium needed.

| File | What it covers | Tests |
| --- | --- | --- |
| `test_state_machine.py` | Conversation state machine + Ravi's deterministic responses | ~86 |
| `test_verify_order.py` | Order verification helpers (modifier qty, keyword matching) | ~15 |
| `test_dialogue_framework.py` | Dialogue log parser + LLM-judge evaluator | ~22 |

```bash
python -m pytest unit_tests/ -q        # run all
python -m pytest unit_tests/ -v        # verbose
```

**Run before committing any change to `end_to_end_voice_test.py`, `verify_order.py`, or `src/ollama_client.py`.**
The pre-commit hook (`.git/hooks/pre-commit`) enforces `python -m pytest unit_tests/ -q` automatically.

When adding a new deterministic handler or changing question detection:
1. Add a test that would have caught the original bug (real Whisper output as the input)
2. Add a test that confirms existing flows still work (simple_pepperoni, combo happy path)
Add as a new top-level 
## Testing section in CLAUDE.md\n\n## Testing
- Always write unit tests for new functionality and bug fixes by default; do not wait to be reminded.
- After any code change, run the full test suite and confirm all tests pass before committing.
- When fixing bugs, add a regression test that would have caught the original bug.
Add as a new 
## Debugging Workflow section in CLAUDE.md\n\n## Debugging Workflow
- Before running tests or scripts, verify prerequisites: required services running, correct ChromeDriver/Chrome version match, ports free, and config files in expected state.
- When a bug recurs after a fix, check for orphan processes and stale in-flight code/buffers before assuming the fix is wrong.
- Use screenshots early when debugging UI/automation flows rather than guessing at locators.
Add as a new 
## Approach section in CLAUDE.md\n\n## Approach
- Prefer minimal-coding, simple designs (e.g., two branches over three) — propose the simplest working solution first.
- Do not introduce new external dependencies (e.g., Ollama, Puppeteer) without explicit user approval; check existing project tooling first (e.g., Playwright is already in use).
- When the user says 'continue' or 'do it', stop further analysis and take action.