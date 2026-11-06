# Testing Rules

## Unit tests (`unit_tests/`)

All offline unit tests live in `unit_tests/` — no device, no Ollama, no Appium needed (~0.1s).

| File | What it covers |
| --- | --- |
| `test_state_machine.py` | State machine + Ravi's deterministic responses |
| `test_verify_order.py` | Modifier qty counting, keyword matching |
| `test_dialogue_framework.py` | Log parser + LLM judge evaluator |

**Every behaviour change must have a unit test before committing.**
The pre-commit hook runs `python -m pytest unit_tests/ -q` automatically.

When adding a new file to `unit_tests/`, add `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` at the top so it runs from any working directory.

---

## Modifier entries in `expected_items`

Items **without** a leading digit are modifiers — visible inside Show Details, not separate cart rows.

```yaml
expected_items:
  - "1 Large Pepperoni Pizza"   # cart item → counts as qty 1
  - "Extra Sauce"               # modifier  → qty 0, verified via Show Details text
  - "Well Done Bake"            # modifier  — NOT "Baked Well Done" (screen shows "Bake: Well Done")
  - "Square Cut"                # modifier
  - "Extra Parmesan Romano"     # modifier
```

`_parse_expected_total_qty()` sums only items with a leading digit. Modifiers contribute 0 — this matches the app's "1 ITEM" cart display.

Naming rule: use `"Well Done Bake"` not `"Baked Well Done"` — screen token is `"bake"` not `"baked"` (plural/singular matching only handles `+s`).

---

## Dialogue behavior tests (`dialogue_tests/agent_behavior.yaml`)

Add new Ava do's/don'ts as YAML entries — no code changes needed.

```yaml
- name: <label>
  ravi_says: "<primary question Ravi speaks>"
  ravi_variants:
    - "<alternate phrasing>"
  intent: >
    <what Ava MUST do — plain English, avoid brand-specific UI names>
  anti_intent: >
    <what Ava MUST NOT do — plain English>
  severity: error
```

**Intent wording rule:** describe behavior generically — e.g. *"redirects customer to check details themselves"* not *"says 'Show Details'"*. The LLM judge anchors to exact phrases; vague-but-accurate intent text handles any phrasing Ava might use.

Running live (launches app, one session per rule, all variants back-to-back):
```bash
python run_dialogue_tests.py
python run_dialogue_tests.py --test "Allergen"
```

**Session batching rule:** all variants for a rule run in **one** voice session, not one session per variant. Each session requires full app navigation (~15 s); batching avoids 45 s+ overhead for a 3-variant rule. Only start a new session if prior conversation state would pollute the next question.

Running offline against a log:
```bash
python test_dialogue.py --log logs/test_run_<timestamp>.txt
```

---

## Bidirectional tests for every new state machine phrase

Any new phrase added to `REVIEW_PHRASES`, `ANYTHING_ELSE`, `ORDER_PROMPTS`, `SCHEDULE_CONFIRM_PHRASES`, `ACK_ONLY_PHRASES`, or any other state machine list **must have tests in both directions**:

| Direction | What to test | Expected result |
| --- | --- | --- |
| **Should fire** | Full, complete agent sentence containing the phrase | Correct deterministic response |
| **Should NOT fire (partial)** | SR-truncated variant ending mid-thought | `None` (falls to Ollama) or at minimum semantically correct |
| **Should NOT fire (wrong context)** | Phrase appears in a different context (confirmation, statement, etc.) | `None` or different rule fires |

**Why this matters:** Whisper and `speech_recognition` frequently truncate agent speech at mid-sentence pauses. A phrase that looks complete in a test can appear truncated in a live run:

```
Complete:  "We have you down for the nearest 15 mins, does that work for you?"  → Rule 5a fires ✓
Truncated: "We have you down for the nearest 15."                               → should NOT fire ✗
```

Adding `"have you down"` to `REVIEW_PHRASES` passed all positive tests but fired prematurely on the truncated form — a bug only caught in a live run because no negative test existed.

**Template — always write these three tests together:**

```python
def test_new_phrase_full_sentence_fires(self):
    # ✅ should fire
    r = self._step("... [full agent sentence with phrase] ...")
    self.assertIsNotNone(r)
    self.assertEqual(r[0], "Expected response.")

def test_new_phrase_truncated_does_not_fire(self):
    # ❌ should NOT fire — SR cut off before sentence completes
    r = self._step("... [sentence ending mid-thought] ...")
    self.assertIsNone(r)   # falls to Ollama

def test_new_phrase_wrong_context_does_not_fire(self):
    # ❌ should NOT fire — phrase present but agent is making a statement, not asking
    r = self._step("... [phrase in a non-question context] ...")
    # Rule 6/7/8 may fire, but not the new rule
    if r is not None:
        self.assertNotEqual(r[0], "Expected response.")
```

This also applies to: new `CVV_KEYWORD_RE` variants, new `PAYMENT_CONFIRM_PHRASES` entries, new loyalty/tip phrase lists.

### Catch-all rules (Rule #8 and similar) need payment-truncation tests too

Rule #8 (`all items ordered + non-question → "Okay, thanks."`) is a **structural catch-all**, not a phrase list. Every time its conditions or guards change, write these three tests:

| Test | Input | Expected |
|---|---|---|
| Normal pricing statement | `"Your order total is eleven ninety nine."` | `"Okay, thanks."` (Rule #8 fires) |
| Truncated payment question — chunk 1 | `"A total of $25 would be charged to your card ending in 1234"` | `None` (payment guard blocks Rule #8) |
| Truncated payment question — another form | `"We'll charge your card ending in 5678"` | `None` |

**Why:** Payment questions are the most common two-part sentences in the ordering flow. SR captures the charge/card statement before the `"...and if that's correct?"` arrives. Without an explicit test for the truncated chunk, bugs only surface in live runs.

Any phrase containing `charged`, `charge to`, `card ending`, `credit card ending`, `finalize`, `confirm your order`, or `place your order` must NOT trigger Rule #8 — these are guarded by `_PAYMENT_CONTEXT_RE`.

---

## State machine bypass rules — always guard with `_is_question()`

Any bypass that pattern-matches agent speech must also check `_is_question()` before acting.

**Why:** `"I'll apply $1 of Pipa Doe"` contains `"apply"` — without the question guard, Ravi responds `"I'd like to apply one dollar please"` on a confirmation statement, creating an infinite loop.

For confirmation statements (not questions), add a separate handler that returns `"Okay, thanks."`:
```python
_confirmation_words = ["i've applied", "i'll apply", "applied", "will be applied"]
if any(w in agent_lower for w in _confirmation_words):
    return ("Okay, thanks.", items_ordered_idx)
```

---

## Appium UI text locators — always add lowercase variants first

XPATH `@text` matching is case-sensitive. Add lowercase before uppercase:

```python
locators = [
    (AppiumBy.XPATH, "//*[@text='Show details']"),       # actual app text
    (AppiumBy.XPATH, "//*[@text='Show Details']"),       # fallback
    (AppiumBy.XPATH, "//*[contains(@text,'Show details')]"),
    (AppiumBy.XPATH, "//*[contains(@text,'Show Details')]"),
]
```

---

## Screenshot rules — evidence at every exit

### 1. Screenshot at every branch exit — use `_ss()`

Every verification function must take a screenshot on **every** exit path — pass, fail, skip, and exception. Use the `_ss(driver, name)` helper in `verify_order.py` (swallows exceptions silently so it never breaks the test).

**Rule:** no `return` from a verification or navigation function without an `_ss()` call on that path. If a branch fires and the report shows nothing, that branch is missing a screenshot.

### 2. `SCREENSHOT_CAPTIONS` is a contract

`_build_screenshots()` in `src/report_generator.py` **only renders files whose stem is in `SCREENSHOT_CAPTIONS`**. A screenshot not in that list is silently dropped from the report even if the file exists on disk.

**Rule:** every `driver.take_screenshot("name")` call must have a matching `("name", "Caption")` entry in `SCREENSHOT_CAPTIONS` in the same commit. Treat them as inseparable.

This is **enforced automatically** by `unit_tests/test_screenshot_registry.py` (runs in pre-commit). The test statically scans all source files for literal `take_screenshot("name")` calls and fails if any stem is missing from `SCREENSHOT_CAPTIONS`. F-string screenshot names (e.g. `f"nav_retry_{n}"`) must be declared in `FSTRING_STEMS` inside the same test file.

### 3. Verify when the element is visible — not when convenient

Perform checks at the **earliest moment the target is guaranteed on screen**, not at a later convenient point in the flow. The AI disclaimer was checked post-conversation because it felt safe — but the app had already navigated away, causing multiple failed iterations.

For the disclaimer specifically: check on **Turn 1** (when Ava's first greeting fires) — that is the only window where it is guaranteed visible.

---

## Diagnosis rules — fix from the first run, not the second

### 4. Capture raw evidence on every matcher failure

Any function that does text matching must **save its full raw input to `logs/` on failure** — not just a snippet or a length count. The "run again to see what it said" loop is the most expensive iteration pattern in this codebase.

- `verify_ai_disclaimer` calls `_save_disclaimer_evidence(texts, source)` which writes `logs/disclaimer_texts_<ts>.json` and `logs/disclaimer_source_<ts>.xml`.
- Copy those files to `unit_tests/fixtures/` and write a unit test. The matcher is fixed once, verified offline, never regresses.
- **General rule:** when adding any new text matcher, add a corresponding failure log that prints every input string verbatim and saves to `logs/`.

### 5. Extract text-matching logic into pure testable functions

Any keyword or regex match used in live verification must be a **pure function testable without a device**.

Bad — inline and untestable:
```python
def verify_ai_disclaimer(driver, ...):
    combined = " ".join(texts).lower()
    if "uses ai" in combined:   # can't test without Appium session
        ...
```

Good — extracted and testable:
```python
def _check_ai_disclaimer_text(texts: list) -> tuple:
    combined = " ".join(texts).lower()
    ...

def verify_ai_disclaimer(driver, ...):
    passed, _, _ = _check_ai_disclaimer_text(texts)
```

When a matcher fails in a live run, the saved fixture updates the unit test — no device needed.

### 6. Never use silent `except: pass` in test infrastructure

`except Exception: pass` hides real errors and turns hard failures into mysterious soft failures. It appeared in three places and silently swallowed Appium errors and page_source failures.

**Rule:** always at minimum `except Exception as e: print(f"⚠️  {e}")`. Bare `except: pass` is only acceptable in genuine cleanup paths (e.g., a best-effort screenshot in a `finally` block).

### 7. Build diagnostic modes into the existing CLI — not print statements

When you need to understand what the app is showing without running a full test, use:

```bash
python end_to_end_voice_test.py --dump-screen
```

This navigates to the voice ordering screen, waits for Ava's greeting, dumps all visible texts + full `page_source` to `logs/dump_screen_<ts>.json`, and exits.

**Rule:** never add temporary `print` statements to production code to inspect live state. Add a `--flag` to the existing CLI instead. Modifying prod code to gather diagnostic data requires a commit, pollutes git history, and must be reverted.
