# Project Pie — End-to-End Automation Plan

**App:** Acme Pizza Android (voice-led ordering via Google Cloud AI agent "Ava")
**Framework:** Appium + Python + Ollama (Ravi AI customer) + physical audio loop
**Last updated:** 2026-06-08
**Source doc:** Project Pie Production Scope & Use Cases

---

## Legend

| Symbol | Meaning |
| --- | --- |
| ✅ | Automated — scenario YAML exists and runs in CI |
| 🔲 | Planned — to be automated |
| 🚫 | Out of scope — excluded from this framework |
| **P0** | Required for first production launch |
| **P1** | Nice to have for first production launch |
| **P2** | Post-launch fast follow |
| **PX** | Out of scope for Project Pie |

---

## 1. Foundational — Voice Cart Building

Basic voice-led cart building available to both guest and loyal customers.

### 1.1 Happy Path (Positive)

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| F-01 | Single item order — large pepperoni pizza | Positive | P0 | ✅ | `simple_pepperoni.yaml` |
| F-02 | Multi-item combo order — pizza + breadsticks + 2-liter drink | Positive | P0 | ✅ | `combo_with_sides.yaml` |
| F-03 | Large party order — 6 items across multiple categories | Positive | P0 | ✅ | `large_order.yaml` |
| F-04 | Half-and-half pizza — different toppings each side | Positive | P0 | ✅ | `half_and_half_pizza.yaml` |
| F-05 | Mid-order single modifier — extra cheese after pizza confirmed | Positive | P0 | ✅ | `modification_extra_cheese.yaml` |
| F-06 | Mid-order multiple modifiers — extra sauce, well done, square cut, parmesan | Positive | P0 | ✅ | `modifiers_with_pizza.yaml` |
| F-07 | Hesitant customer with pauses before deciding | Positive | P0 | ✅ | `indecisive.yaml` |
| F-08 | Customer asks about menu items ("What desserts do you have?") then places order | Positive | P0 | ✅ | `menu_inquiry_dessert.yaml` |
| F-09 | Agent recommends order for a stated group size ("ordering for 6 people") | Positive | P0 | ✅ | `group_order.yaml` |
| F-10 | Customer states dietary restriction (vegetarian) and agent recommends accordingly | Positive | P0 | ✅ | `vegetarian_dietary_restriction.yaml` |
| F-11 | Customer requests delivery instead of carryout during voice session | Positive | P0 | ✅ | `delivery_request.yaml` |
| F-12 | Agent offers order summary before checkout (cart has 4+ items) | Positive | P1 | 🔲 | — |

### 1.2 Item Changes (Positive)

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| F-13 | Remove an item after it has been confirmed in cart | Positive | P0 | ✅ | `remove_item.yaml` |
| F-14 | Change item size (medium → large) after initial selection | Positive | P0 | ✅ | `change_size.yaml` |
| F-15 | Change quantity — "make that two large pepperonis instead of one" | Positive | P0 | ✅ | `change_quantity.yaml` |
| F-16 | Replace one topping with another after pizza confirmed | Positive | P0 | ✅ | `change_topping.yaml` |

### 1.3 Negative Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| F-17 | Customer requests an item not on the menu — agent informs politely | Negative | P0 | ✅ | `unavailable_item.yaml` |
| F-18 | Customer speech is unclear/garbled — agent asks to repeat | Negative | P0 | ✅ | `unclear_speech.yaml` |
| F-19 | Customer tries to re-order an item agent already said is unavailable | Negative | P0 | ✅ | `agent_behavior.yaml` (reorder rejected rule) |
| F-20 | Customer changes their mind after order review confirmation | Negative | P0 | ✅ | `change_mind_after_no.yaml` |

### 1.4 Edge Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| F-21 | Customer orders the same item twice — agent adds qty 2, not two separate lines | Edge | P0 | ✅ | `duplicate_item_order.yaml` |
| F-22 | Customer asks about dietary info (gluten-free crust) before committing to item | Edge | P0 | ✅ | `gluten_free_inquiry.yaml` |
| F-23 | Agent speech truncated mid-sentence by SR — state machine falls to Ollama correctly | Edge | P0 | ✅ | `unit_tests/test_state_machine.py::TestSRTruncationF23` |
| F-24 | Very long order (6+ items) — agent does not lose earlier items during session | Edge | P0 | ✅ | `unit_tests/test_state_machine.py::TestVeryLongOrderF24` |

---

## 2. Payment

Standard payment flow for credit/debit card. Tip flow applies to delivery orders only.

### 2.1 Saved Payment — CVV Flow (Positive)

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| P-01 | Loyal customer with saved card — agent requests CVV, Ravi speaks it, order placed | Positive | P0 | ✅ | `simple_pepperoni.yaml` (and most others) |
| P-02 | CVV requested with Whisper mis-transcription of keyword (e.g., "CDV") — still detected | Positive | P0 | ✅ | `unit_tests/test_state_machine.py::TestCvvKeywordRegex::test_cdv_variant` |

### 2.2 Guest / No Saved Payment (Positive)

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| P-03 | Guest customer — agent redirects to PJ payment page without asking for CVV | Positive | P0 | 🔲 | — |
| P-04 | Loyal customer with no saved payment — agent redirects to payment page | Positive | P0 | 🔲 | — |

### 2.3 Tip Flow — Delivery Orders

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| P-05 | Delivery order — agent asks for tip, customer says custom dollar amount | Positive | P0 | 🔲 | — |
| P-06 | Delivery order — agent offers tip as % options, customer selects one | Positive | P1 | 🔲 | — |
| P-07 | Delivery order — customer declines tip ("no tip, please") | Edge | P0 | 🔲 | — |

### 2.4 Negative Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| P-08 | Payment failure — agent silently redirects to checkout page without explaining | Negative | P0 | 🔲 | — |
| P-09 | Agent asks for CVV on a non-CVV payment method — code does not speak CVV | Negative | P0 | 🔲 | — |

### 2.5 Edge Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| P-10 | CVV keyword arrives split across two SR chunks — bypass still fires on second chunk | Edge | P0 | ✅ | `unit_tests/test_state_machine.py::TestCVVChunkSplitP10` |
| P-11 | Payment confirmation question arrives as two SR chunks — first chunk does not trigger "Okay thanks" | Edge | P0 | ✅ | `unit_tests/test_state_machine.py::TestRule8AllItemsOrdered::test_rule8_does_not_fire_on_truncated_charge_statement` |

---

## 3. Loyalty — Pipa Dough Redemption

Applies to loyal customers with accumulated Pipa Dough balance.

### 3.1 Positive Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| L-01 | Loyal customer — agent asks about Pipa Dough, customer applies full balance | Positive | P0 | ✅ | `unit_tests/test_state_machine.py::TestRule2bLoyalty::test_pipa_dough_how_much_apply` |
| L-02 | Loyal customer — agent asks about Pipa Dough, customer applies partial amount | Positive | P0 | ✅ | `unit_tests/test_state_machine.py::TestRule2bLoyalty::test_pipa_dough_how_much_apply` |
| L-03 | Loyal customer — agent tells customer their Pipa Dough balance on request | Positive | P0 | ✅ | `scenarios/loyalty_balance_inquiry.yaml` |
| L-04 | Loyal customer — customer declines to apply Pipa Dough, proceeds to CVV | Positive | P0 | ✅ | `scenarios/loyalty_decline_pipa_dough.yaml` + `unit_tests/test_state_machine.py::TestLoyaltyDeclineL04` |

### 3.2 Negative Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| L-05 | Pipa Dough balance too small to apply — agent clearly explains why it cannot be used | Negative | P0 | 🔲 | — |
| L-06 | Pipa Dough unavailable for this order type — agent informs customer | Negative | P0 | 🔲 | — |

### 3.3 Edge Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| L-07 | Pipa Dough covers exact cart total — no CVV needed, order completes | Edge | P0 | ✅ | `scenarios/loyalty_full_coverage.yaml` |
| L-08 | Whisper mis-transcribes "Pipa Dough" (e.g., "Pipa Doe") — regex matches correctly | Edge | P0 | ✅ | `unit_tests/test_state_machine.py::TestRule2bLoyalty` (Pipa Delo, Pop-a-Doh, Pompa Do, Puffa Do, pop-and-doh variants) |
| L-09 | "I'll apply $1 of Pipa Dough" statement (not a question) — state machine returns "Okay, thanks." | Edge | P0 | ✅ | `unit_tests/test_state_machine.py::TestRule2bLoyalty::test_pipa_dough_confirmation_statement_acks_not_applies` |

---

## 4. Image Ordering (Out of Scope)

Image ordering is excluded from end-to-end automation. The physical audio loop framework cannot drive camera or gallery interactions, and the QA app has no mechanism to pre-inject images programmatically. Manual QA or a dedicated image-injection harness would be required.

### 4.1 Positive Cases

| # | Test Case | Type | Priority | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| I-01 | Photo of a group of people — agent suggests correct pizza count | Positive | P0 | 🚫 | Requires camera/gallery automation |
| I-02 | Photo of group with explicit dietary note ("2 vegetarians") — agent recommends accordingly | Positive | P0 | 🚫 | Requires camera/gallery automation |
| I-03 | Photo of handwritten order note — agent adds items to cart and submits | Positive | P0 | 🚫 | Requires camera/gallery automation |

### 4.2 Negative Cases

| # | Test Case | Type | Priority | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| I-04 | Blurry or unrecognisable image — agent tells customer it cannot understand | Negative | P0 | 🚫 | Requires camera/gallery automation |

### 4.3 Edge Cases

| # | Test Case | Type | Priority | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| I-05 | Mixed dietary group (vegetarians + meat eaters) — agent accounts for all | Edge | P0 | 🚫 | Requires camera/gallery automation |

---

## 5. Deal Genie

After cart is complete, agent navigates to the Deal Genie screen and finds the best available deal.

### 5.1 Positive Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| D-01 | Cart complete — agent navigates to Deal Genie screen and applies best deal automatically | Positive | P0 | 🔲 | — |
| D-02 | Agent applies deal that reduces cart total — verify discount on Order Complete screen | Positive | P0 | 🔲 | — |
| D-03 | Agent does NOT upsell during ordering ("Would you like to add a dessert?") | Positive | P0 | 🔲 | — |

### 5.2 Negative Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| D-04 | No applicable deals exist — agent tells customer no deal is available | Negative | P1 | 🔲 | — |
| D-05 | Agent does not apply a deal it invented — only real corporate/local deals used | Negative | P0 | 🔲 | — |

### 5.3 Edge Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| D-06 | Agent suggests adding an item to qualify for a deal ("add a dessert for 20% off") after cart complete | Edge | P1 | 🔲 | — |

---

## 6. Quick Reorder

Loyal customers who have made at least one prior purchase can reorder their most recent order.

### 6.1 Positive Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| Q-01 | Loyal customer — agent shows last order, customer confirms, CVV entered, order placed | Positive | P0 | 🔲 | — |
| Q-02 | Loyal customer with no saved payment — agent redirects to payment page after quick reorder | Positive | P0 | 🔲 | — |

### 6.2 Negative Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| Q-03 | No previous order history — agent handles gracefully, falls back to standard ordering | Negative | P0 | 🔲 | — |

### 6.3 Edge Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| Q-04 | Previous order contained an item no longer available — agent notifies and offers alternatives | Edge | P0 | 🔲 | — |

---

## 7. Order Ahead

Customers place an order for a specific future date and time, even when the store is closed.

### 7.1 Positive Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| O-01 | Order ahead — carryout, zip 40014, first store, future time slot, single pizza | Positive | P0 | ✅ | `order_ahead_carryout.yaml` |
| O-02 | Order ahead — delivery, 1 hour ahead, single pizza, delivery type verified | Positive | P0 | ✅ | `order_ahead_delivery.yaml` |
| O-03 | Order ahead — carryout for a next-day slot (not just today) | Positive | P0 | 🔲 | — |
| O-04 | Agent confirms selected store can fulfil the scheduled order | Positive | P0 | 🔲 | — |

### 7.2 Negative Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| O-05 | Requested pickup time is in the past — agent rejects and asks for a valid time | Negative | P0 | 🔲 | — |
| O-06 | Store closed at requested time — agent informs customer and suggests available slots | Negative | P0 | 🔲 | — |

### 7.3 Edge Cases

| # | Test Case | Type | Priority | Status | Scenario File |
| --- | --- | --- | --- | --- | --- |
| O-07 | Order ahead at the exact store closing time boundary | Edge | P0 | 🔲 | — |

---

## 8. Offer Stacking (P2 — Post-Launch)

| # | Test Case | Type | Priority | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| OS-01 | Apply a single 1-time coupon code on top of an active deal | Positive | P2 | 🚫 | Not scoped for production launch |
| OS-02 | Apply two coupons simultaneously alongside an active deal | Positive | P2 | 🚫 | Not scoped for production launch |

---

## Summary

| Feature Area | Total | ✅ Automated | 🔲 To Automate | 🚫 Out of Scope |
| --- | --- | --- | --- | --- |
| Foundational — Voice Cart | 24 | 23 | 1 | 0 |
| Payment | 11 | 4 | 7 | 0 |
| Loyalty — Pipa Dough | 9 | 7 | 2 | 0 |
| Image Ordering | 5 | 0 | 0 | 5 |
| Deal Genie | 6 | 0 | 6 | 0 |
| Quick Reorder | 4 | 0 | 4 | 0 |
| Order Ahead | 7 | 2 | 5 | 0 |
| Offer Stacking | 2 | 0 | 0 | 2 |
| **Total** | **68** | **36** | **25** | **7** |

---

## Implementation Priority Order

✅ = done as of 2026-06-08

1. ~~**P0 Foundational** — F-01–F-11, F-13–F-24~~ ✅ All done (F-12 is P1, deferred)
2. ~~**P0 Payment** — P-01, P-02, P-10, P-11~~ ✅ Done; **remaining**: guest/no-saved-payment redirect (P-03, P-04), payment failure (P-08), CVV-suppression on wrong trigger (P-09), tip flow (P-05, P-07)
3. ~~**P0 Loyalty** — L-01–L-04, L-07–L-09~~ ✅ Done; **remaining**: Pipa Dough balance too small (L-05), unavailable for order type (L-06)
4. **P0 Order Ahead gaps** — next-day slot (O-03), store confirmation (O-04), past-time rejection (O-05), store closed (O-06), boundary case (O-07)
5. **P0 Deal Genie** — navigation + deal applied (D-01, D-02), no upsell guard (D-03), no invented deals (D-05)
6. **P0 Quick Reorder** — happy path + CVV (Q-01), no saved payment (Q-02), no prior history (Q-03), unavailable item in prior order (Q-04)
7. **P1 items** — order summary before checkout (F-12), tip % options (P-06), no applicable deals (D-04), upsell-to-qualify suggestion (D-06)
8. **P2 / Post-launch** — Offer Stacking (OS-01, OS-02)
9. **Out of scope** — Image Ordering (I-01–I-05), Offer Stacking (OS-01–OS-02)

---

## Notes for Automation

- All new scenarios requiring loyalty/guest context need test accounts pre-configured in `config/appium_config.yaml`.
- Image Ordering is excluded — the audio-loop framework cannot drive camera/gallery interactions and the QA app has no image injection API.
- Deal Genie scenarios require a cart whose items qualify for at least one active corporate deal in the QA environment.
- Quick Reorder scenarios (Q-01–Q-04) require a loyal account with at least one prior completed order in the QA environment.
- Payment failure (P-08) requires the QA app to support a simulated failure mode or a designated test card number.
- Negative speech cases (F-17, F-18) are best handled via a new `unclear_speech` persona with deliberate pauses and hedging phrases.
- Every new state machine phrase added for a new scenario must have a bidirectional unit test: one should-fire test and one truncated-should-not-fire test in `unit_tests/test_state_machine.py`.

---

## Long-Term Plan — CI/CD Integration & Parallel Execution

### Phase 1 — CI/CD on a Single Device (Near-Term)

Run the existing serial suite automatically in CI against the one USB-connected Android device, with no changes to the audio loop or framework.

| # | Action | Outcome |
| --- | --- | --- |
| 1 | Add a GitHub Actions (or Jenkins) workflow that triggers on every PR merge to `main` | Every merge runs the smoke suite automatically on the connected device |
| 2 | Smoke suite (`--tag smoke`) runs on PR; full regression suite runs on a nightly schedule | Fast PR feedback; full coverage overnight |
| 3 | Upload the HTML report and screenshots as CI artifacts after each run | Shareable, persistent test evidence with no local access required |
| 4 | Post a Slack or email notification with pass/fail counts and a link to the report | Team visibility without log-diving |
| 5 | Gate PR merge on smoke suite pass using a required status check | Broken voice flows block merge automatically |
| 6 | Store device UDID, Appium URL, and test account credentials in GitHub Actions secrets | No credentials committed to the repo |

**Pre-requisite:** The Mac running CI must remain connected to the Android device and have Appium + Ollama running as background services (e.g., `launchd` plist or `systemd` unit).

### Phase 2 — Cloud Device Farm (Single Device, No Physical Loop)

Move from the physical audio loop to a cloud device farm so CI can run unattended without Mac hardware.

| # | Action | Outcome |
| --- | --- | --- |
| 1 | Switch `--config` to `config/appium_config.testgrid.yaml` (already scaffolded) pointing at BrowserStack App Automate or AWS Device Farm | Zero scenario code changes; only the config switches |
| 2 | Replace the physical mic/speaker loop with pre-recorded `.wav` files injected via `adb shell` or the device farm's audio injection API | Removes the Mac audio hardware dependency entirely |
| 3 | Host Ollama (Ravi's LLM) on a persistent cloud instance; point `appium_config.yaml` at its URL | Cloud CI workers have no local Ollama; one shared instance handles all runs |
| 4 | Run smoke suite on every PR; regression suite nightly — now fully serverless | No always-on Mac required |

### Phase 3 — Continuous Quality Gates

Add observability and safety nets on top of the single-device cloud pipeline before introducing parallelism.

| # | Action | Outcome |
| --- | --- | --- |
| 1 | Integrate dialogue quality scores (LLM-judge via `run_dialogue_tests.py`) into the CI pipeline | Agent behaviour regressions caught per-build, not just order placement |
| 2 | Track pass-rate trends over time in a dashboard (Grafana + InfluxDB or Datadog) | Detect flakiness and regressions before they compound |
| 3 | Auto-quarantine flaky scenarios (fail rate > 20% over last 10 runs) into a separate suite | Main suite stays green; flaky tests are investigated in isolation |
| 4 | Add contract tests between the voice agent API and the Appium harness | Agent API changes are caught before they break end-to-end scenarios |

### Phase 4 — Multi-Device Parallel Execution

Scale horizontally once the single-device cloud pipeline is stable. The physical audio loop (Mac speakers → phone mic) is the key cross-talk constraint — parallelism requires solving it first.

| # | Action | Outcome |
| --- | --- | --- |
| 1 | On cloud device farm: spin up N Appium sessions concurrently; audio injection is already per-session, so no cross-talk risk | True horizontal scale — no local hardware limit |
| 2 | Extend `run_suite.py` with `--workers N`; distribute the scenario list across N processes using `multiprocessing.Pool` | N scenarios run simultaneously |
| 3 | Tag scenarios `parallelizable: true/false` in YAML to exclude account-state-dependent flows from parallel runs | Prevents session state conflicts for scenarios sharing a logged-in account |
| 4 | Merge per-worker HTML reports into a single consolidated report at suite end | One report for the full parallel run |
| 5 | For local physical devices: assign one USB audio interface channel per device to eliminate cross-talk | Enables 2–3 parallel devices on local hardware as a fallback |

**Target:** 10+ cloud sessions in parallel → full regression suite in under 10 minutes.
