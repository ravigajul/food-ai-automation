# Extensibility Plan — Adding New Features

## Current Limitations

| Area | Limitation | Features Blocked |
|---|---|---|
| Navigation | Hardcoded to "Start Voice Order" | Quick Reorder, Order Ahead, Deal Genie, Image Ordering |
| Termination triggers | Only `cvv` and `order_confirmed` | Loyalty PIN, scheduled order confirmation |
| Payment bypass | Only credit card phrase detection | Loyalty points, Apple Pay, PayPal |
| Verification | Only ORDER COMPLETE screen | Loyalty points used, deal applied, scheduled time |
| YAML schema | No pre/post step hooks | Any feature needing non-voice navigation steps |

---

## Planned Changes (none implemented yet)

### Change 1 — YAML Schema Extension

New optional fields (all backward compatible):

```yaml
feature: voice_order              # voice_order | quick_reorder | order_ahead | deal_genie | image_order
payment_method: card              # card (default) | loyalty | apple_pay | paypal
loyalty_pin: "1234"               # spoken when agent asks for loyalty PIN
scheduled_time: "7:30 PM"         # for order_ahead
deal_code: "SAVE20"               # for deal_genie / offer_stacking
verification_type: order_complete # order_complete (default) | loyalty_applied | deal_applied | scheduled_confirmed
pre_conversation_steps:
  - navigate_quick_reorder
  - select_first_order
post_conversation_steps:
  - confirm_scheduled_time
extra_assertions:
  - loyalty_points_redeemed
  - deal_discount_applied
```

### Change 2 — Navigation Dispatch (`launch_and_invoke_voice.py`)

Replace hardcoded "Start Voice Order" with a dispatch function:

```python
def navigate_to_feature(driver, feature, pre_steps=None):
    navigate_to_home(driver)
    dispatchers = {
        "voice_order":   _navigate_voice_order,    # existing
        "quick_reorder": _navigate_quick_reorder,  # NEW
        "order_ahead":   _navigate_order_ahead,    # NEW
        "deal_genie":    _navigate_deal_genie,     # NEW
        "image_order":   _navigate_image_order,    # NEW
    }
    dispatchers.get(feature, _navigate_voice_order)(driver)
    for step in (pre_steps or []):
        PRE_STEP_REGISTRY[step](driver)
```

### Change 3 — Extended Termination Triggers (`end_to_end_voice_test.py`)

| Trigger | Behavior |
|---|---|
| `cvv` | Existing — code speaks CVV, exits |
| `order_confirmed` | Existing — exits on agent confirmation phrase |
| `loyalty_pin` | NEW — speaks `loyalty_pin` from YAML when agent asks for PIN (mirrors CVV regex) |
| `scheduled_confirmed` | NEW — exits on scheduling phrase ("scheduled for", "order set for") |

### Change 4 — Payment Method Bypass Table

```python
PAYMENT_BYPASS_PHRASES = {
    "card":      ["credit card ending", "would you like to pay with", ...],  # existing
    "loyalty":   ["redeem your points", "use your rewards", "apply points"],
    "apple_pay": ["apple pay", "confirm with face id", "pay with apple"],
    "paypal":    ["paypal", "confirm via paypal"],
}
```

### Change 5 — Pluggable Verification (`verify_order.py`)

```python
VERIFICATION_STRATEGIES = {
    "order_complete":      verify_order_complete,   # existing
    "loyalty_applied":     verify_loyalty_applied,  # NEW
    "deal_applied":        verify_deal_applied,     # NEW
    "scheduled_confirmed": verify_scheduled_order,  # NEW
}
```

### Change 6 — Page Objects (`src/pages/`)

Build incrementally as features land:

```
src/pages/
  home_page.py           # refactor from launch_and_invoke_voice
  voice_order_page.py    # existing flow
  quick_reorder_page.py
  order_ahead_page.py
  deal_genie_page.py
  loyalty_page.py
```

---

## Implementation Order

1. Change 1 (YAML schema) — additive, no risk
2. Change 2 (Navigation dispatch) — everything downstream depends on this
3. Change 5 (Verification strategies) — needed for any new feature
4. Change 3 (Termination triggers) — loyalty PIN, scheduled order
5. Change 4 (Payment method) — Apple Pay, PayPal, loyalty
6. Change 6 (Page objects) — refactor as needed per feature

---

## Feature Notes

**Quick Reorder** — Home → "Order Again" → select previous order; `termination_trigger: order_confirmed`

**Order Ahead** — Standard voice flow; agent asks about scheduled time; new state machine pattern for time prompt; `termination_trigger: scheduled_confirmed`

**Deal Genie** — Home → "Deal Genie"; agent may offer deals during ordering; `verification_type: deal_applied`

**Loyalty Redemption** — During payment, agent asks to apply points/PIN; `termination_trigger: loyalty_pin`; `extra_assertions: [loyalty_points_redeemed]`

**Image Ordering** — Camera-based, no voice loop; dedicated page object; `feature: image_order`

**Offer Stacking** — Voice order with multi-offer `last_offer` parsing; `extra_assertions: [deal_discount_applied]`
