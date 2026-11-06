# Conversation Flow — State Machine, Bypasses & Termination

`run_ai_customer_conversation()` tries handlers in this order each turn. **Ollama is only reached if all handlers above it return no match.**

## Handler Priority

CVV bypass → Payment bypass → State machine → Ollama

---

## Conversation State Tracking

The loop maintains three runtime state lists injected as hard constraints at the **top** of every Ollama prompt (before conversation history):

| Variable | Purpose |
| --- | --- |
| `rejected_items` | Items the agent said are unavailable — Ravi must never re-request them |
| `confirmed_updates` | Actions the agent already confirmed as done — Ravi must not repeat them |
| `last_offer` | Most recent agent offer/question — Ravi must pick a specific option, not give a vague answer |

Constraints are placed **before** conversation history so the LLM reads them first and doesn't anchor on prior dialogue.

---

## State Machine (`_get_deterministic_response()`)

Parses Ravi's item list from the persona's `**Your Order:**` section at conversation start. Tracks `items_ordered_idx` across turns.

When running via `run_suite.py`, the item list is built from **`expected_items` in the YAML** (ground truth). Falls back to parsing the persona's `**Your Order:**` section only when `expected_items` is not provided (standalone `--full` runs).

| Pattern | Trigger (agent speech) | Ravi's response |
| --- | --- | --- |
| **Turn 1 greeting** | Always (turn == 1) | `"Hi, I'd like to place an order please."` |
| **"Anything else?"** | `"anything else"`, `"what else"`, `"will that be all"`, `"is that all"`, etc. — and items remain | `"And {next item} please."` |
| **"Anything else?"** | Same — and all items ordered | `"No, that's all, thank you."` |
| **Order prompt** | `"what can i get you"`, `"what would you like"`, `"how can i help"`, etc. | `"I'd like {next item}."` |
| **Order review** | `"your order is"`, `"does that sound right"`, `"is that correct"`, `"let me repeat that back"`, etc. + `"?"` | `"Yes, that's right."` |
| **Short ack** | ≤ 10-word statement containing "got it", "perfect", "alright", "sounds good", etc. — no `"?"` | `"Okay, thanks."` |
| **Item added** | `"added"` in ≤ 12-word non-question statement | `"Okay, thanks."` (rule #7 — prevents "Yes, that's right." after an item-add confirmation) |
| **All items ordered + non-question** | All items served and agent statement has no `"?"` | `"Okay, thanks."` (rule #8 — prevents Ollama hallucinations on total/pricing statements) |

> **Rejection guard:** if `rejected_items` is non-empty the state machine returns `None` for all patterns — Ollama handles the turn with the rejection constraint block injected.

---

## Hard Bypasses

Run after state machine, before Ollama.

| Bypass | Trigger (agent speech) | Ravi's response | Loop action |
| --- | --- | --- | --- |
| **CVV** | `CVV_KEYWORD_RE` match (see below) + request word or `"?"` + `termination_trigger=="cvv"` | `"My CVV is {cvv}."` | `break` |
| **Payment confirmation** | Payment phrase (`"credit card ending"`, `"would you like to pay with"`, `"would you like to finalize"`, etc.) + `"?"` — **but NOT if agent is asking for a code** | `"Yes, please go ahead."` | `continue` |

**CVV keyword regex** (`CVV_KEYWORD_RE`) covers Whisper mis-transcriptions and alternative phrasings:
- `\bcvv\b`, `\bcvd\b`, `\bcdv\b`, `\bcvc\b`, `\bcbv\b`, `\bcv\b`
- `security code`, `card verification`, `verification code`
- `back of your card`, `back of the card`
- `three-digit`, `3-digit`, `number on the back`

**Payment bypass guard:** does NOT fire if agent is asking for a verification code — regex `r'\b(provide|enter|give|supply|share|tell me)\b.{0,40}\bcode\b'` in agent speech skips the payment bypass. This prevents payment bypass from consuming a CVV request with mis-transcribed keywords (e.g. "provide the CDV code for your card ending in 007?").

Both CVV and payment bypasses search `agent_lower + " " + agent_stripped` (punctuation-removed) so `"C.V.V."` with periods still matches `\bcvv\b`.

---

## Ollama Fallback (qwen2.5:7b, temperature=0.1, max 80 tokens)

Called only for genuinely ambiguous turns: agent clarifying questions about size/crust/toppings, unexpected responses, post-rejection re-ordering.

- A mandatory preamble is injected before every prompt (no quotes, no meta-commentary, answer-what-was-asked, 1–2 sentences max)
- `offer_trigger_phrases` includes `"do you want"`, `"do you prefer"`, `"which one"` etc. → sets `last_offer`; the `last_offer` block parses `"X or Y"` and injects `"Your choices are: 'X' OR 'Y'. Pick one."`
- Loop detection: if Ravi's last two responses are identical → injects `"CRITICAL: You just said X — give a COMPLETELY DIFFERENT answer."`
- History fed to Ollama has `[DETERMINISTIC]`/`[OLLAMA]` tags stripped to reduce noise
- Output is post-processed by `_clean_ravi_response()` to strip role prefixes or meta-commentary

Every Ravi turn in the log file is tagged `[DETERMINISTIC]` or `[OLLAMA]`.

---

## Termination Conditions

The loop exits when **any** of these occur (checked in order each turn):

| Trigger | Side | Condition |
| --- | --- | --- |
| Agent goodbye | Agent | `"exit"` or `"goodbye"` in agent speech |
| Order confirmed | Agent | Phrase match against `order_complete_phrases` list (e.g. `"order confirmed"`, `"thank you for your order"`) |
| CVV bypass | Agent | Agent asks for CVV + `termination_trigger == "cvv"` → code speaks CVV, listens for order confirmation (up to 90 s), then breaks |
| Ravi goodbye | Ravi | `"goodbye"` or `"thanks, bye"` in Ravi's response |
| Timeout | System | No speech detected within 45 s → `sr.WaitTimeoutError` |
| Keyboard interrupt | User | Ctrl+C |

> **Note:** `"payment"` and `"transfer"` alone do **not** terminate — they appear in mid-conversation phrases. Payment confirmation is handled by the payment bypass (`continue`, not `break`). CVV bypass is the only payment-related exit.
>
> **Note:** The old Ravi-side CVV check (`"cvv" in ravi_response`) has been removed. The agent-side bypass is the only CVV exit.

## `termination_trigger` — Payment Flow Variants

| Value | When to use | How it works |
| --- | --- | --- |
| `cvv` (default) | Credit card is the default payment | Agent asks for CVV → code bypasses Ollama and speaks the CVV from YAML/`--cvv` → loop exits |
| `order_confirmed` | Saved card, Apple Pay, PayPal, or any non-CVV payment | CVV bypass is disabled; loop exits only when agent says an `order_complete_phrases` phrase |

Set in scenario YAML (`termination_trigger: order_confirmed`) or via CLI (`--termination-trigger order_confirmed`).
If absent from a YAML file the default (`cvv`) is used.

## Dynamic Listen

- `ravi_just_spoke` flag: calibrate ambient noise only after Ravi speaks (skips calibration otherwise)
- `prev_agent_word_count` drives `pause_threshold` — ≤20 words → 1.5 s, >20 words → 1.8 s, unknown → 2.0 s (turn 1)
