# Project Structure

## Entry Points

| File | Purpose |
|---|---|
| `run_suite.py` | Runs all `scenarios/*.yaml` in one Appium session; generates HTML report in `reports/` |
| `end_to_end_voice_test.py` | Single-run CLI; owns the conversation state machine |
| `run_dialogue_tests.py` | Live dialogue intent tests (no order needed); LLM-as-judge via Ollama |
| `test_dialogue.py` | Offline log-replay validator for dialogue behavior rules |

## Test Infrastructure

- `unit_tests/` — all offline unit tests (~0.1 s, no device/Ollama)
  - `test_state_machine.py` — state machine + Ravi's deterministic responses
  - `test_verify_order.py` — modifier qty counting, keyword matching
  - `test_dialogue_framework.py` — log parser, LLM judge evaluator
- Pre-commit hook: `python -m pytest unit_tests/ -q` — blocks commit on failure

## Dialogue Behavior Contract

- `dialogue_tests/agent_behavior.yaml` — do's/don'ts for Ava; add rules here, no code needed
  - Each rule has: `ravi_says`, `ravi_variants`, `intent`, `anti_intent` (live LLM judge)
  - Also has keyword fallback fields for offline log-replay
- `unit_tests/test_dialogue_framework.py` — tests the parser and LLM judge with mocked Ollama

## Scenarios and Personas

- `scenarios/*.yaml` — YAML test cases (`expected_items`, `persona`, `termination_trigger`, `cvv`, `tags`)
  - Modifier entries (no leading digit) = verified via Show Details, NOT counted in cart qty
- `personas/*.txt` — Ravi's character profiles

## Key Source Files

| File | Purpose |
|---|---|
| `verify_order.py` | ORDER COMPLETE scraping; `click_show_details` uses lowercase-first locators |
| `launch_and_invoke_voice.py` | All Appium navigation steps |
| `src/appium_driver.py` | `AppiumDriver` wrapper class |
| `src/ollama_client.py` | Ollama interface; `evaluate_dialogue_intent()` for LLM judging |
| `config/appium_config.yaml` | Appium caps, Ollama model, device settings |

## Config

- App type: Native Android (not React Native)
- Package: `com.acmepizza.android.debug.qa`
- Main activity: `com.acmepizza.android.MainActivity`
- Appium server: `http://localhost:4723`
- Ollama: `http://localhost:11434`, model loaded via `_load_ollama_model()` from config
