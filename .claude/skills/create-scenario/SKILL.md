---
name: create-scenario
description: Creates a new Acme Pizza voice ordering test scenario YAML (and optionally a persona file). Use this skill when the user says "create scenario", "new scenario", "add scenario", "new test case", "add a test case", or describes a new ordering flow they want to test. Trigger even when the user provides partial details like an order or persona — fill defaults for the rest.
---

# create-scenario

Write `scenarios/<slug>.yaml` from the user's description in one shot. Infer everything you can — only ask if the expected items list is genuinely empty after inference.

## Step 1 — Infer all fields from the description

Extract the following from what the user said. Do NOT ask unless stated otherwise.

| Field | How to infer | Default if unclear |
|---|---|---|
| **Scenario name** | Title-case summary of the scenario | Derive from items + key detail |
| **Expected items** | Parse items from description (see rules below) | Ask ONE question only if nothing found |
| **Persona** | Named persona if user specified one; if description implies special behavior (rushed, indecisive, etc.) set `new_persona: true` | `default` |
| **Tags** | `smoke` | `smoke` |
| **Termination trigger** | `order_confirmed` if user says "saved card / apple pay / no CVV"; otherwise `cvv` | `cvv` |
| **CVV** | Use value if given | `358` |
| **New persona** | `true` only if user explicitly asks for a new persona or scenario clearly needs custom behavior | `false` |

### Item inference rules

Parse the user's description for these patterns and emit the correct `expected_items` format:

**Cart items** (need a leading digit — counted in cart total):
- Size + item name → `"1 Large Pepperoni Pizza"`, `"1 Medium BBQ Chicken Pizza"`, `"2 Orders of Garlic Knots"`
- Bare item without size → `"1 <Item>"` (assume quantity 1)

**Modifiers** (no leading digit — verified in Show Details only):
- Topping modifications: `"Extra Cheese"`, `"Extra Sauce"`, `"Light Sauce"`
- Bake: `"Well Done Bake"`, `"Light Bake"` (NOT "Baked Well Done" — screen token is "Bake:")
- Cut: `"Square Cut"`, `"Normal Cut"`
- Half-and-half: `"Left <Topping>"`, `"Right <Topping>"` (screen shows "Left: X" / "Right: Y")
- Any other customisation mentioned without a quantity

### Only ask if you're stuck

If you cannot identify even one cart item from the description, ask exactly one question:
> "What items should I add to `expected_items`? (e.g. `1 Large Pepperoni Pizza`, `Extra Cheese`)"

Do not ask about any other field.

## Step 2 — Derive the slug

`slug` = name lowercased, spaces → `_`, remove all non-alphanumeric-underscore characters.  
Example: `"Half and Half Pizza — Pepperoni Left"` → `half_and_half_pizza_pepperoni_left`

## Step 3 — Write the YAML

Write directly to `scenarios/<slug>.yaml`:

```yaml
name: <name>
description: >
  Customer orders <comma-joined item names without quantities>.
persona: <persona>
termination_trigger: <termination_trigger>
cvv: "<cvv>"
expected_items:
<items as YAML list, each quoted>
tags:
  - <tag>
```

Rules:
- `cvv` must always be a quoted string (`"358"`, not `358`)
- Omit `cvv` field entirely if `termination_trigger` is `order_confirmed`
- Preserve user casing on item names exactly

## Step 4 — New persona (only if inferred or requested)

If `new_persona` is true: read `personas/_template.txt`, then write `personas/<persona_slug>.txt` following the template exactly. Derive personality and conversation flow from the scenario name and items. Keep it minimal.

## Step 5 — Run unit tests

```bash
python -m pytest unit_tests/ -v 2>&1 | tail -5
```

Output exactly one line: `scenarios/<slug>.yaml written. Tests: <N> passed.`  
If tests fail, show only the failure lines.
