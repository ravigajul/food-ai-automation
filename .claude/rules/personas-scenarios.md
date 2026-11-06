# Personas and Scenario YAML

---

## Persona System

Personas define Ravi's (the AI customer's) character, order, and conversation behaviour. They are plain-text system prompts fed to Ollama before every conversation turn.

### Persona Files (`personas/`)

| File | Description |
| --- | --- |
| `_template.txt` | Canonical template + authoring guide — copy this to create new personas |
| `default.txt` | Standard, polite customer — large pepperoni pizza + garlic knots |
| `simple_pepperoni.txt` | Minimal single-item order — one large pepperoni pizza only |
| `combo.txt` | Combo order — pizza + breadsticks + 2-liter Pepsi |
| `rushed.txt` | Customer in a hurry — two large pepperoni pizzas + Pepsi |
| `indecisive.txt` | Hesitant customer — eventually settles on pizza + breadsticks |
| `large_order.txt` | Party order — six pizzas, sides, and drinks |
| `extra_cheese.txt` | Modification flow — large pepperoni pizza + extra cheese requested after pizza is confirmed |

Add a new file (e.g. `personas/picky.txt`) to create a new persona — no code changes needed.

### Required Persona Structure

Use `personas/_template.txt` as the canonical starting point for any new persona.

Every persona file **must** follow this structure:

1. **Opening line** — who Ravi is and the scenario context
2. **`Your Order:`** — the specific items Ravi intends to order (explicit list, no improvising). **This section is machine-parsed by `_parse_items_from_persona()` at runtime** — each item must be on its own numbered line (`1. One large pepperoni pizza`) so the state machine can serve them deterministically.
3. **`Conversation Flow:`** — numbered steps: Greeting → Ordering → Review → No Extras → Payment → CVV note
   - Payment step says: "Yes, please go ahead." (bypassed by code anyway, but belt-and-suspenders)
   - CVV step says: "Handled automatically by the framework." — do NOT include CVV digits or logic here
4. **`Personality:`** — bullet points describing tone and behaviour
5. **`Critical Rules:`** — copy verbatim from `_template.txt`; do NOT shorten or remove any rule:
   - **NEVER BREAK CHARACTER** — garbled agent → "Sorry, could you say that again?" Never meta-comment.
   - **Answer what was asked** — respond to the agent's last sentence; do not redirect.
   - **ONE thing per turn** — 1–2 short sentences max.
   - **SPOKEN DIALOGUE ONLY** — no thoughts, no stage directions; do NOT put quotes around words.
   - **Never repeat yourself** — agent confirmed → "Okay, thanks." and move on.
   - **Accept order type** — don't raise delivery/pickup unless agent does.
   - **Never take the agent's role** — customer only.
   - **Payment** — agent asks to confirm card → "Yes, please go ahead."
   - **CVV — handled by code** — do not include CVV response logic in personas.
6. **`Example Responses:`** — 5–7 lines covering greeting, each ordering step, payment, and the fallback "Sorry, could you say that again?"

### Two Ways to Supply a Persona

| Method | Flag | Source |
| --- | --- | --- |
| Named persona file | `--persona rushed` | Loads `personas/rushed.txt` verbatim — **no Ollama call** |
| Free-text scenario | `--scenario "..."` | Ollama generates a persona on-the-fly using `PERSONA_GENERATOR_SYSTEM`; falls back to `default.txt` on failure |

Scenario YAML files reference a persona via the `persona:` key (file stem, no extension).
If omitted the suite runner defaults to `"default"`.

> **Rule:** `prepare_persona()` checks `persona_name` first. If a named persona file is specified, it is loaded directly — Ollama is **never called** regardless of whether a `description` is also present. Ollama persona generation is only triggered when `--scenario` is used with no `--persona` (CLI-only path).

---

## Scenario YAML Schema

```yaml
name: Human-readable name         # required; used for filtering and reports
description: >                    # required; passed to Ollama for persona generation
  What the customer wants to do.
persona: default                  # optional; file stem from personas/ (default: "default")
termination_trigger: cvv          # optional; "cvv" (default) or "order_confirmed"
                                  #   cvv            → code detects agent CVV request, speaks cvv, exits
                                  #   order_confirmed → saved card/Apple Pay/PayPal; exit on agent confirmation
cvv: "358"                        # optional; CVV digits spoken by code when agent requests them (default: "358")
expected_items:                   # required for deterministic verification
  - "1 Large Pepperoni Pizza"
  - "1 Order of Garlic Knots"
expected_delivery_type: Carryout  # required; Phase 4 asserts Overview shows "Carryout" or "Delivery"
expected_time: "11:00 AM"         # optional; Phase 4 asserts Overview scheduled time contains this value
                                  #   omit for ASAP orders (time is dynamic); set for order_ahead scenarios
                                  #   order_ahead scenarios use the dynamically-selected slot instead
tags:                             # optional; used with --tag flag
  - smoke
```

Verification stop words (ignored during matching): `a`, `an`, `the`, `with`, `and`, `or`, `of`, `for`, `on`, `in`, `order`, `pizza`, digits `0`–`9`, and spelled-out numbers `one`–`five`.

Size aliases normalised: `lg`/`lrg`→`large`, `md`/`med`→`medium`, `sm`→`small`, `xl`→`xlarge`.

**Modifier entries** (no leading digit): entries like `"Extra Cheese"` without a leading integer are treated as *modifiers*, not separate cart items. They are verified against the expanded "Show details" text (e.g. `Whole: Pepperoni, Extra Cheese`) but contribute **0** to the quantity cross-check total. All standalone cart items must have a leading integer (`"1 Large Pepperoni Pizza"`).
