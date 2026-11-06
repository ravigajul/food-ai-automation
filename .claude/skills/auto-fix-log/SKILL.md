---
name: auto-fix-log
description: >
  Monitors the latest execution log, diagnoses failures, and applies targeted fixes to
  source code and unit tests. Use when a test run failed or produced unexpected behaviour
  and you want the system to self-heal. Triggers on phrases like: "fix the log",
  "monitor and fix", "auto-fix the run", "fix any issues from the last run",
  "analyse the log and fix", "what went wrong and fix it", "self-heal".
---

# Auto-Fix Log Skill

You are a self-healing agent for the Acme Pizza voice ordering test framework.
Your job: read the latest (or specified) execution log, diagnose every anomaly, fix the
source code, add unit tests, run the suite, and commit only when green.

---

## Step 1 — Locate the log

```bash
# Latest log
ls -t <project-root>/logs/test_run_*.txt | head -1
```

If the user passed a specific log path or timestamp, use that instead.
Read the full log with the Read tool.

---

## Step 2 — Parse for anomalies

Work through the log line-by-line and build an anomaly list. Categorise each finding:

### Category A — `[OLLAMA]` on a turn that should be deterministic

Look for agent lines followed by `[OLLAMA]` Ravi lines. Flag any where:

| Agent speech contains | Expected handler | Wrong signal |
|---|---|---|
| pipa dough / pop-a-doh / popidow / pipa doe / pipa d-word variants | Rule 2b deterministic | `[OLLAMA]` |
| tip / gratuity / how much would you like to tip | Rule 5b deterministic | `[OLLAMA]` |
| anything else / will that be all / is that all | Rule 2 (next item or "No, that's all") | `[OLLAMA]` |
| does that work / does that sound right / is that correct + `?` | Review rule (Yes, that's right) | `[OLLAMA]` |
| schedule / nearest 15 / nearest slot | Schedule confirm rule | `[OLLAMA]` |
| what can i get / how can i help / what would you like | Order prompt rule (first item) | `[OLLAMA]` |
| added / got it + ≤12 words | Item-added ack (Rule 7) | `[OLLAMA]` |

For each mismatch, record:
- `agent_speech` — the exact agent line from the log
- `ravi_response` — what Ravi said
- `expected_rule` — which rule should have fired
- `root_cause` — mis-transcription variant? Missing phrase in phrase list? Guard too strict?

### Category B — Locator / Appium failures

Scan for Python tracebacks. Look for:
- `NoSuchElementException` — wrong selector or element missing
- `StaleElementReferenceException` — element went stale mid-interaction
- `TimeoutException` with an element description — element never appeared
- `is not clickable` — wrong element class (accessibility wrapper vs EditText)

Record: exception type, element description, and which function raised it.

### Category C — Loop / repeat patterns

Detect if any Ravi response appears 3+ times consecutively in the log — a stuck loop.
Also check for alternating identical responses (A-B-A-B with same text).

### Category D — Premature/wrong termination

- Test ended before `[Order placed confirmed]` → conversation died early
- Ravi said `"No, that's all, thank you."` when agent was asking about loyalty/Pipa Dough credits
  (agent phrase contained "how much" + a pipa-dough variant) → wrong rule fired

### Category E — Missing `[SCHEDULE CONFIRMED]` on order-ahead scenarios

For scenarios tagged `order_ahead`, confirm `[SCHEDULE CONFIRMED: agent mentioned 'HH:MM AM/PM']`
appears. If absent, the schedule-confirm regex didn't match.

---

## Step 3 — Diagnose root causes

For each anomaly, read the relevant source file to confirm the root cause before touching code.

Key source files:
- `end_to_end_voice_test.py` — state machine, phrase lists, bypass logic
- `launch_and_invoke_voice.py` — Appium navigation, pre-steps
- `verify_order.py` — ORDER COMPLETE scraping, locators

**For Category A (OLLAMA on deterministic turn):**

```bash
grep -n "PIPA_D_RE\|pipa.*dough\|loyalty\|tip.*rule\|Rule 2b\|Rule 5b\|ANYTHING_ELSE\|ORDER_PROMPTS\|REVIEW_PHRASES\|SCHEDULE_CONFIRM" \
  <project-root>/end_to_end_voice_test.py | head -40
```

Then read the relevant function around line numbers found.

Common root causes:
- New Whisper variant not covered by existing regex (e.g. `"Popidow"` not matching `_PIPA_D_RE`)
- Phrase in list but `_is_question()` guard blocking it when it shouldn't
- `last_offer` set incorrectly — state machine skipped because `rejected_items` non-empty
- New agent phrasing that doesn't match any existing phrase in `ANYTHING_ELSE` etc.

**For Category B (locator):**

Read the function that threw the exception. Check:
- Is the locator finding a `View` wrapper instead of the target widget?
- Is an implicit wait conflict causing a timeout? (`implicitly_wait(10)` vs short explicit timeout)
- Did the screen change between finding and interacting?

**For Category D (Pipa Dough question → "No, that's all"):**

This means `_PIPA_D_RE` didn't match the agent's phrasing. Extract the exact agent speech,
test the regex:

```python
import re
text = "<exact agent speech from log>"
_PIPA_D_RE = re.compile(
    r'\bp\w{0,3}pa\s+d\w*\b'
    r'|\bpop[-\s]a[-\s]d\w*\b'
    r'|\bpipadot\b',
    re.IGNORECASE
)
print(bool(_PIPA_D_RE.search(text)))  # should be True
```

If False, extend the regex — do NOT add a one-off string.

---

## Step 4 — Apply fixes

Apply the minimal targeted fix for each root cause. Follow the project rules:

### Fixing a phrase-list miss (Category A)

Grep to find the list, read surrounding context, then add the missing phrase:

```python
# Example: "nearest slot" not in SCHEDULE_CONFIRM_PHRASES
SCHEDULE_CONFIRM_PHRASES = [
    "does that work for you",
    "nearest 15",
    "nearest slot",        # ← add
    ...
]
```

**Always add the phrase that covers the general case, not the single Whisper output.**

### Fixing a regex miss (Category A/D)

Test the failing input first, then extend `_PIPA_D_RE` or `CVV_KEYWORD_RE` as appropriate.
Never add an exact-string fallback for a proper noun — always extend the regex.

### Fixing a guard that's too strict (Category A)

Read the guard condition. If `_is_question()` is blocking a phrase that's always a question,
add the phrase to `_QUESTION_STARTERS` or `_KNOWN_QUESTION_PHRASES` inside `_is_question()`.

### Fixing a locator (Category B)

Follow the appium-input-debug skill rules:
1. Prefer `android.widget.EditText` over `@content-desc` for input fields
2. Add lowercase locator before uppercase
3. Add `@clickable='true'` constraint when multiple matches exist

### Fixing wrong termination / rule-ordering (Category D)

If a catch-all rule (Rule 8 or "anything else" check) is swallowing a loyalty/pipa-dough
question, add a guard:

```python
# Guard: don't fire this rule if agent is asking about loyalty credits
if _PIPA_D_RE.search(agent_lower):
    return None  # fall through to Rule 2b
```

---

## Step 5 — Add unit tests

For **every fix**, add at least these three tests (see `.claude/rules/testing.md`):

| Test | Input | Expected |
|---|---|---|
| Should fire (full sentence) | Exact agent speech from the log | Correct deterministic response |
| Should NOT fire (truncated) | Same speech cut mid-sentence | `None` or different rule |
| Should NOT fire (wrong context) | Same phrase in a statement, no `?` | `None` or statement handler |

Test file: `unit_tests/test_state_machine.py`

Example template:
```python
def test_<phrase>_full_fires(self):
    r = self._step("<exact agent speech>")
    self.assertIsNotNone(r)
    self.assertEqual(r[0], "<expected Ravi response>")

def test_<phrase>_truncated_no_fire(self):
    r = self._step("<sentence cut before end>")
    self.assertIsNone(r)

def test_<phrase>_statement_no_fire(self):
    r = self._step("<same phrase as statement, not question>")
    if r is not None:
        self.assertNotEqual(r[0], "<deterministic response>")
```

---

## Step 6 — Run unit tests

```bash
cd <project-root> && python -m pytest unit_tests/ -v 2>&1 | tail -30
```

If any test fails:
1. Read the failure output
2. Fix the code or the test (code fix takes priority — tests exist to catch real bugs)
3. Re-run until all pass

Do NOT commit with failing tests.

---

## Step 7 — Commit

Only after all tests pass:

```bash
git add end_to_end_voice_test.py launch_and_invoke_voice.py verify_order.py unit_tests/test_state_machine.py unit_tests/test_verify_order.py
git status
git commit -m "<one-line imperative summary of what was fixed>"
```

Commit message format: `Fix <root cause>: <what changed>` — e.g.:
- `Fix Popidow variant not matching _PIPA_D_RE`
- `Fix schedule-confirm phrase missing 'nearest slot'`
- `Fix zip EditText locator finding View wrapper instead`

Do NOT add `Co-Authored-By` trailers.

---

## Step 8 — Report

Output a concise summary:

```
## Auto-Fix Report

**Log analysed:** logs/test_run_<timestamp>.txt
**Anomalies found:** <N>

| # | Category | Agent speech | Root cause | Fix applied |
|---|---|---|---|---|
| 1 | A — OLLAMA miss | "You also have $4,923 in Popidow..." | Popidow not matched by _PIPA_D_RE | Extended regex + Rule 2b test added |
| 2 | ... | ... | ... | ... |

**Tests:** <N> new, all passing
**Committed:** <sha> — <message>
```

If nothing to fix (log is clean), say so and do not commit.

---

## Anomaly Priority

Fix in this order:
1. Category D (wrong termination / loyalty-question swallowed) — breaks the whole conversation
2. Category B (locator failures) — hard crash
3. Category A (OLLAMA on deterministic) — correctness issue
4. Category C (loops) — reliability issue
5. Category E (missing schedule confirmation) — assertion gap only

---

## What NOT to do

- Do not add broad "catch-all" phrases that would break existing tests
- Do not add exact-string variants for Acme Pizza product names — extend the regex
- Do not create new helper scripts — edit existing files only
- Do not commit if any unit test is red
- Do not change test expectations to make tests pass — fix the code instead
