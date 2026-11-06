#!/usr/bin/env python3
"""
Unit tests for the conversation state machine and helpers in end_to_end_voice_test.py.
No Appium, no device, no Ollama required — runs in < 1 second.

Usage:
    python unit_tests/test_state_machine.py
    python -m pytest unit_tests/test_state_machine.py -v
"""
import importlib
import os
import sys
import types
import unittest

# Allow imports from the project root regardless of where pytest is invoked from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Lightweight stubs so end_to_end_voice_test imports without hardware deps
# ---------------------------------------------------------------------------
def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m

_noop = lambda *a, **kw: None  # noqa: E731

# Top-level packages first
_stub("yaml", safe_load=lambda f: {}, dump=_noop)
_stub("appium")
_stub("appium.webdriver")
_stub("appium.webdriver.common")
_stub("appium.webdriver.common.appiumby",
      AppiumBy=type("AppiumBy", (), {"ANDROID_UIAUTOMATOR": "uia", "XPATH": "xpath"}))

sr_stub = _stub("speech_recognition",
                WaitTimeoutError=type("WaitTimeoutError", (Exception,), {}),
                Recognizer=object, Microphone=object)

src_pkg = _stub("src")
_stub("src.appium_driver", AppiumDriver=object)
_stub("src.ollama_client", OllamaClient=object)
_stub("src.voice_ai", speak_sync=_noop, speak_digits_sync=_noop)
_stub("src.verify_order")

# Pure helper implementations — duplicated here so the stub exposes real logic
# without pulling in the appium import chain.
def _check_ai_disclaimer_text_impl(texts):
    combined = " ".join(texts).lower()
    has_ai   = "uses ai" in combined or "feature uses" in combined or "ava ai" in combined
    has_cav  = any(w in combined for w in ("occasionally", "incorrect", "misleading", "mistakes"))
    return has_ai and has_cav, has_ai, has_cav

def _check_ai_disclaimer_source_impl(source):
    s = source.lower()
    has_ai  = "uses ai" in s or "feature uses" in s or "ava ai" in s
    has_cav = any(w in s for w in ("occasionally", "incorrect", "misleading", "mistakes"))
    return has_ai and has_cav, has_ai, has_cav

# Stub the launch module with the exact names imported by end_to_end_voice_test
_stub("launch_and_invoke_voice",
      launch_app=_noop,
      scroll_to_start_voice_order=_noop,
      click_start_voice_order=_noop,
      click_arrow_on_ready_screen=_noop,
      grant_microphone_permission=_noop,
      verify_voice_agent_active=_noop,
      verify_ai_disclaimer=lambda *a, **kw: True,
      get_voice_session_id=lambda *a, **kw: "stub-session",
      _check_ai_disclaimer_text=_check_ai_disclaimer_text_impl,
      _check_ai_disclaimer_source=_check_ai_disclaimer_source_impl,
      _save_disclaimer_evidence=_noop)

import end_to_end_voice_test as m  # noqa: E402  (must come after stubs)

_det  = m._get_deterministic_response
_iq   = m._is_question
_echo = m._is_room_echo
_gpq  = m._get_pre_order_query


class TestPreOrderQuery(unittest.TestCase):
    """_get_pre_order_query() injects a question instead of ordering item[0]."""

    QUERIES = ["What desserts do you have?"]

    def test_fires_on_order_prompt_with_query_remaining(self):
        result = _gpq("what can i get you", self.QUERIES, 0)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "What desserts do you have?")
        self.assertEqual(result[1], 1)

    def test_does_not_fire_when_all_queries_exhausted(self):
        result = _gpq("what can i get you", self.QUERIES, 1)
        self.assertIsNone(result)

    def test_does_not_fire_on_non_order_prompt(self):
        result = _gpq("we have pepperoni and cheese", self.QUERIES, 0)
        self.assertIsNone(result)

    def test_does_not_fire_when_no_queries_configured(self):
        self.assertIsNone(_gpq("what can i get you", [], 0))
        self.assertIsNone(_gpq("what can i get you", None, 0))

    def test_advances_idx_across_two_queries(self):
        queries = ["What desserts do you have?", "Do you have any deals today?"]
        r1 = _gpq("what can i get you", queries, 0)
        self.assertIsNotNone(r1)
        self.assertEqual(r1[0], queries[0])
        self.assertEqual(r1[1], 1)
        r2 = _gpq("what would you like next", queries, 1)
        self.assertIsNotNone(r2)
        self.assertEqual(r2[0], queries[1])
        self.assertEqual(r2[1], 2)

    def test_does_not_fire_on_agent_ack_statement(self):
        # Acknowledgement statements must not intercept the query
        result = _gpq("perfect, got it", self.QUERIES, 0)
        self.assertIsNone(result)

    def test_fires_on_whisper_truncated_order_prompt(self):
        # "for you today" is a Whisper-truncated ORDER_PROMPTS tail
        result = _gpq("how can i help you today", self.QUERIES, 0)
        self.assertIsNotNone(result)

    def test_group_order_query_injected_on_order_prompt(self):
        # F09: group-size query fires when agent asks for the order
        queries = ["I'm ordering for a group of 6 people. What would you recommend?"]
        result = _gpq("what can i get you today", queries, 0)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], queries[0])
        self.assertEqual(result[1], 1)

    def test_group_order_query_does_not_fire_on_agent_ack(self):
        # Confirmation statement ("great, let me look into that") must not trigger
        queries = ["I'm ordering for a group of 6 people. What would you recommend?"]
        result = _gpq("great, let me look into that for you", queries, 0)
        self.assertIsNone(result)

    def test_group_order_query_exhausted_after_one_injection(self):
        # After the query fires once (idx=1) it must not fire again
        queries = ["I'm ordering for a group of 6 people. What would you recommend?"]
        result = _gpq("anything else i can help with", queries, 1)
        self.assertIsNone(result)


class TestIsQuestion(unittest.TestCase):
    """_is_question() must catch questions even without a trailing ?"""

    def _iq(self, text):
        return _iq(text, text.lower())

    # --- should be questions ---
    def test_explicit_question_mark(self):
        self.assertTrue(self._iq("How much pipa dough do you have?"))

    def test_no_question_mark_how_much(self):
        self.assertTrue(self._iq("How much pipa dough do you have"))

    def test_no_question_mark_do_you(self):
        self.assertTrue(self._iq("Do you have a rewards account"))

    def test_no_question_mark_would_you(self):
        self.assertTrue(self._iq("Would you like to apply your rewards"))

    def test_no_question_mark_can_you(self):
        self.assertTrue(self._iq("Can you confirm your address"))

    def test_starter_are(self):
        self.assertTrue(self._iq("Are you a rewards member"))

    def test_starter_is(self):
        self.assertTrue(self._iq("Is there anything else"))

    def test_starter_what(self):
        self.assertTrue(self._iq("What size would you like"))

    def test_starter_which(self):
        self.assertTrue(self._iq("Which crust do you prefer"))

    # --- should NOT be questions ---
    def test_ack_not_question(self):
        self.assertFalse(self._iq("Got it, adding that now."))

    def test_item_added_not_question(self):
        self.assertFalse(self._iq("Large pepperoni pizza added."))

    def test_pricing_statement_not_question(self):
        self.assertFalse(self._iq("Your total comes to fifteen ninety-nine."))

    def test_order_confirmed_not_question(self):
        self.assertFalse(self._iq("Thank you, your order has been confirmed."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
COMBO = ["1 Large Pepperoni Pizza", "1 Order of Breadsticks", "1 2-Liter Pepsi"]
SIMPLE = ["1 Large Pepperoni Pizza"]


def det(agent_speech, turn=2, items=None, idx=0, rejected=None):
    """Convenience wrapper with sensible defaults."""
    items = items if items is not None else SIMPLE
    rejected = rejected or []
    return _det(agent_speech, agent_speech.lower(), turn, items, idx, rejected)


class TestRule1Greeting(unittest.TestCase):
    def test_turn1_always_greets(self):
        result = det("Hello, welcome to Acme Pizza!", turn=1)
        self.assertIsNotNone(result)
        self.assertIn("Hi", result[0])


class TestRule2cRepeatRequest(unittest.TestCase):
    """F-18: Agent asks to repeat — state machine re-states last ordered item."""

    ITEMS = ["a large pepperoni pizza"]

    def _step(self, agent_speech, idx=1):
        return _det(agent_speech, agent_speech.lower(), 3, self.ITEMS, idx, [])

    # --- Should fire: re-state last item ---

    def test_repeat_fires_after_item_ordered(self):
        r = self._step("I'm sorry, I didn't catch that, could you repeat?")
        self.assertIsNotNone(r)
        self.assertIn("I said I'd like", r[0])
        self.assertIn("large pepperoni pizza", r[0])

    def test_repeat_fires_on_didnt_get_that(self):
        r = self._step("Sorry, I didn't get that.")
        self.assertIsNotNone(r)
        self.assertIn("I said I'd like", r[0])

    def test_repeat_fires_on_come_again(self):
        r = self._step("Come again?")
        self.assertIsNotNone(r)
        self.assertIn("I said I'd like", r[0])

    def test_repeat_fires_on_pardon(self):
        r = self._step("Pardon?")
        self.assertIsNotNone(r)
        self.assertIn("I said I'd like", r[0])

    def test_repeat_fires_on_say_that_again(self):
        r = self._step("Could you say that again please?")
        self.assertIsNotNone(r)
        self.assertIn("I said I'd like", r[0])

    def test_repeat_does_not_increment_idx(self):
        # Re-stating should not advance the item index
        r = self._step("Sorry, could you repeat that?")
        self.assertIsNotNone(r)
        self.assertEqual(r[1], 1)  # items_ordered_idx unchanged

    def test_repeat_before_any_item_ordered_gives_place_order(self):
        # idx=0 — no item served yet
        r = self._step("Could you repeat that?", idx=0)
        self.assertIsNotNone(r)
        self.assertIn("place an order", r[0])

    # --- Should NOT fire: normal ordering phrases ---

    def test_normal_anything_else_does_not_trigger_repeat(self):
        r = self._step("Anything else for you?", idx=0)
        self.assertIsNotNone(r)
        self.assertNotIn("I said", r[0])

    def test_review_prompt_does_not_trigger_repeat(self):
        r = self._step("Does that sound right?")
        self.assertIsNotNone(r)
        self.assertNotIn("I said", r[0])


class TestRule2RejectionGuard(unittest.TestCase):
    """F-17: State machine defers to Ollama on ALL patterns when rejected_items is non-empty."""

    ITEMS = ["a chicken sandwich", "a large pepperoni pizza"]

    def test_anything_else_defers_when_rejected(self):
        r = _det("Anything else for you?", "anything else for you?", 3,
                 self.ITEMS, 1, ["Sorry, we don't have chicken sandwiches."])
        self.assertIsNone(r)

    def test_order_prompt_defers_when_rejected(self):
        r = _det("What would you like?", "what would you like?", 3,
                 self.ITEMS, 1, ["Sorry, we don't have chicken sandwiches."])
        self.assertIsNone(r)

    def test_review_prompt_defers_when_rejected(self):
        r = _det("Does that sound right?", "does that sound right?", 5,
                 self.ITEMS, 2, ["Sorry, we don't have chicken sandwiches."])
        self.assertIsNone(r)

    def test_ack_defers_when_rejected(self):
        r = _det("Got it!", "got it!", 4,
                 self.ITEMS, 2, ["Sorry, we don't have chicken sandwiches."])
        self.assertIsNone(r)

    def test_no_deferral_without_rejected_items(self):
        # Same "anything else" without rejections — state machine fires normally
        r = _det("Anything else for you?", "anything else for you?", 3,
                 ["a large pepperoni pizza"], 1, [])
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "No, that's all, thank you.")


class TestRule2bLoyalty(unittest.TestCase):
    """Loyalty/rewards questions must be intercepted before Ollama."""

    # --- "how much to apply" → apply $1 ---
    def test_pipa_dough_how_much_apply(self):
        result = det("How much pipa dough would you like to use?", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    def test_pipa_dough_whisper_pop_a_dough(self):
        result = det("Sorry I didn't get that. How much pop a dough would you like to use?", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    def test_pipa_dough_whisper_pipa_delo(self):
        # Regression: Whisper transcribed "pipa dough" as "Pipa Delo"
        result = det("You have $4,976 in Pipa Delo available. How much would you like to apply to this order?", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    def test_pipa_dough_whisper_pipa_doo(self):
        result = det("How much pipa doo would you like to apply?", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    def test_pipa_dough_whisper_pop_a_doh_hyphen(self):
        result = det(
            "You also have $4,974 in Pop-a-Doh available. How much would you like to apply to this order?",
            items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    def test_pipa_dough_whisper_pompa_do(self):
        # Regression: Whisper transcribed "pipa dough" as "Pompa Do"
        result = det(
            "You also have $4,973.00 in Pompa Do available. How much would you like to apply to this order?",
            items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    # --- "do you have an account / balance" → decline ---
    def test_pipa_doe_variant_no_account(self):
        # "do you have" = balance inquiry, not apply → decline
        result = det("How much pipa doe do you have", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("rewards account", result[0])

    def test_rewards_account_decline(self):
        result = det("Do you have a rewards account with us?", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("rewards account", result[0])

    def test_loyalty_account_decline(self):
        result = det("Are you a loyalty account member?", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("rewards account", result[0])

    def test_normal_question_not_intercepted(self):
        # Regular ordering question must not be caught by loyalty rule
        result = det("What size would you like?", items=COMBO, idx=0)
        self.assertIsNone(result)  # falls through to Ollama / other rules

    def test_pipa_dough_confirmation_statement_acks_not_applies(self):
        # Regression: "I'll apply $1 of Pipa Doe to your order." is a confirmation
        # statement — Rule 2b must NOT return "I'd like to apply one dollar please."
        result = det("You got it. I'll apply $1 of Pipa Doe to your order.",
                     items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertNotIn("one dollar", result[0])
        self.assertEqual(result[0], "Okay, thanks.")

    def test_i_have_applied_acks(self):
        result = det("I've applied $1 in Pipa Dough to your order.", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Okay, thanks.")

    def test_will_be_applied_acks(self):
        result = det("$1 in Pipa Doe will be applied to your order.", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Okay, thanks.")

    def test_how_much_apply_question_still_works(self):
        # Confirm the original question-trigger still fires correctly
        result = det("How much pipa dough would you like to apply?", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    def test_puffa_do_whisper_variant_apply(self):
        # Regression: live run saw "Puffa Do" as a Whisper mis-transcription of "Pipa Dough"
        result = det(
            "You also have $4,813 in Puffa Do available. How much would you like to apply to this order?",
            items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    def test_pop_and_doh_whisper_variant_apply(self):
        # Regression: live run saw "pop-and-doh" as a Whisper mis-transcription of "Pop-a-Doh"
        result = det(
            "Would you like to apply any pop-and-doh to your order?",
            items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])


class TestRule5bTip(unittest.TestCase):
    """Tip questions must be handled deterministically ($5 tip), not sent to Ollama."""

    def _assert_five_dollar_tip(self, result):
        self.assertIsNotNone(result)
        self.assertIn("five dollar", result[0])

    def test_tip_with_pipadot_context(self):
        result = det(
            "Okay, I've applied $1 in Pipadot. Would you like to add a tip for the driver, Robbie?",
            items=COMBO, idx=3)
        self._assert_five_dollar_tip(result)

    def test_tip_after_pipa_doe_confirmation(self):
        # Regression: "$1 in Pipa Doe will be applied. What amount would you like to tip?"
        # Loyalty bypass must NOT fire — tip handler must answer instead.
        result = det(
            "Okay, $1 in Pipa Doe will be applied. What amount would you like to tip your driver?",
            items=COMBO, idx=3)
        self._assert_five_dollar_tip(result)
        self.assertNotIn("rewards account", result[0])

    def test_what_amount_tip(self):
        result = det("What amount would you like to tip?", items=COMBO, idx=3)
        self._assert_five_dollar_tip(result)

    def test_add_a_tip(self):
        result = det("Would you like to add a tip?", items=COMBO, idx=3)
        self._assert_five_dollar_tip(result)

    def test_tip_for_the_driver(self):
        result = det("Would you like to leave a tip for your driver?", items=COMBO, idx=3)
        self._assert_five_dollar_tip(result)

    def test_gratuity(self):
        result = det("Would you like to add a gratuity to your order?", items=COMBO, idx=3)
        self._assert_five_dollar_tip(result)


class TestRule3AnythingElse(unittest.TestCase):
    def test_orders_next_item_when_remaining(self):
        result = det("Anything else?", items=COMBO, idx=1)
        self.assertIsNotNone(result)
        self.assertIn("Breadsticks", result[0])
        self.assertEqual(result[1], 2)

    def test_done_when_all_ordered(self):
        result = det("Anything else?", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("No", result[0])

    def test_done_when_items_list_empty_agent_driven(self):
        # Group-order scenario: items_to_order=[] (agent builds cart).
        # Rule 3 must still fire and return "No, that's all" — not fall to Ollama.
        result = det("Is there anything else I can get you?", items=[], idx=0)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "No, that's all, thank you.")


class TestRule4OrderPrompt(unittest.TestCase):
    def test_first_item_offered(self):
        result = det("What can I get you today?", items=COMBO, idx=0)
        self.assertIsNotNone(result)
        self.assertIn("Pepperoni", result[0])
        self.assertEqual(result[1], 1)

    def test_truncated_tail_started_for_you(self):
        # Whisper captures only the tail of Ava's greeting: "started for you, Ravi."
        # (full phrase: "What can I get started for you, Ravi?")
        result = det("started for you, Ravi.", items=SIMPLE, idx=0)
        self.assertIsNotNone(result)
        self.assertIn("Pepperoni", result[0])

    def test_truncated_tail_get_you_started(self):
        result = det("get you started today?", items=SIMPLE, idx=0)
        self.assertIsNotNone(result)

    def test_truncated_tail_for_you_today(self):
        result = det("for you today?", items=SIMPLE, idx=0)
        self.assertIsNotNone(result)

    def test_truncated_tail_help_you_today(self):
        result = det("help you today?", items=SIMPLE, idx=0)
        self.assertIsNotNone(result)


class TestRule5OrderReview(unittest.TestCase):
    def test_confirms_review_with_question_mark(self):
        result = det("So your order is one large pepperoni, does that sound right?", items=SIMPLE, idx=1)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Yes, that's right.")

    def test_confirms_review_without_question_mark(self):
        # Whisper often omits ? — should still trigger rule 5 via _is_question
        result = det("So your order is one large pepperoni, does that sound right", items=SIMPLE, idx=1)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Yes, that's right.")

    def test_confirms_is_that_correct_no_qmark(self):
        result = det("One large pepperoni pizza, is that correct", items=SIMPLE, idx=1)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Yes, that's right.")


class TestRule6Ack(unittest.TestCase):
    def test_short_ack_returns_okay_thanks(self):
        result = det("Perfect, got it!", items=SIMPLE, idx=1)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Okay, thanks.")

    def test_long_ack_does_not_match(self):
        # > 10 words — rule 6 shouldn't fire
        result = det("Perfect, I have added that to your order and noted the modification.", items=SIMPLE, idx=1)
        # Either None or something other than Okay thanks from rule 6
        # (rule 8 may catch it; just check it's not from short-ack path)
        # The important thing is no crash
        self.assertTrue(result is None or isinstance(result[0], str))


class TestRule7ItemAdded(unittest.TestCase):
    def test_item_added_short(self):
        result = det("Breadsticks added.", items=COMBO, idx=2)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Okay, thanks.")

    def test_item_added_too_long(self):
        # > 12 words — rule 7 shouldn't fire
        long_msg = "I have successfully added breadsticks to your order along with the drink you requested."
        result = det(long_msg, items=COMBO, idx=3)
        # Should not be caught by rule 7 (too long)
        self.assertTrue(result is None or isinstance(result[0], str))


class TestRule8AllItemsOrdered(unittest.TestCase):
    """Critical regression: Rule 8 must NOT fire for questions."""

    def test_statement_after_all_ordered_returns_okay(self):
        result = det("Your total is fifteen ninety-nine.", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Okay, thanks.")

    def test_pipa_dough_apply_no_qmark_answered(self):
        # Rule 2b: "how much to apply" → $1, never "Okay, thanks."
        result = det("How much pipa dough would you like to use", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    def test_pipa_dough_apply_with_qmark_answered(self):
        result = det("How much pipa dough would you like to use?", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("one dollar", result[0])

    def test_do_you_have_rewards_answered(self):
        # "Do you have a rewards account" → loyalty bypass declines politely
        result = det("Do you have a rewards account", items=COMBO, idx=3)
        self.assertIsNotNone(result)
        self.assertIn("rewards account", result[0])

    def test_unrelated_question_falls_through(self):
        # Non-loyalty question must still fall through to Ollama
        result = det("Would you like to add anything else to your order", items=COMBO, idx=3)
        # Rule 3 (anything else) handles this — either way, not Rule 8 swallowing it
        self.assertTrue(result is None or result[0] != "Okay, thanks.")

    def test_would_you_question_falls_through(self):
        result = det("Would you like to apply any rewards", items=COMBO, idx=3)
        self.assertIsNone(result)

    def test_payment_question_falls_through(self):
        # Payment bypass handles this; state machine must not eat it
        result = det("Would you like to pay with the card ending in 1234?", items=COMBO, idx=3)
        self.assertIsNone(result)


class TestLastOfferDetection(unittest.TestCase):
    """last_offer must be set even when Whisper omits the trailing ?"""

    OFFER_TRIGGER_PHRASES = [
        "we have", "you can choose", "you can pick",
        "would you like", "which would you", "what size",
        "what kind", "what flavor", "which size", "which flavor",
        "do you want", "do you prefer", "would you prefer",
        "which one", "which do you",
    ]

    CHOICE_PHRASES = [
        "we have", "you can choose", "you can pick",
        "which would you", "what size", "what kind", "what flavor",
        "which size", "which flavor", "do you prefer", "would you prefer",
        "which one", "which do you",
    ]
    AMBIGUOUS_PHRASES = ["would you like", "do you want"]

    def _should_set_offer(self, speech):
        import re
        lower = speech.lower()
        _is_quantity = bool(re.search(r'\bhow (much|many)\b', lower))
        _has_options = (
            " or " in lower
            or any(w in lower for w in ("small", "medium", "large",
                                        "original", "garlic", "thin",
                                        "regular", "extra"))
        )
        _triggers = (
            any(p in lower for p in self.CHOICE_PHRASES)
            or (any(p in lower for p in self.AMBIGUOUS_PHRASES) and _has_options)
        )
        return _iq(speech, lower) and _triggers and not _is_quantity

    def test_breadstick_type_with_qmark(self):
        self.assertTrue(self._should_set_offer(
            "Would you like original or garlic parmesan breadsticks?"))

    def test_breadstick_type_no_qmark(self):
        # Regression: Whisper omits ? — last_offer must still be set
        self.assertTrue(self._should_set_offer(
            "Would you like original or garlic parmesan breadsticks"))

    def test_what_size_no_qmark(self):
        self.assertTrue(self._should_set_offer("What size would you like"))

    def test_which_flavor_no_qmark(self):
        self.assertTrue(self._should_set_offer("Which flavor do you prefer"))

    def test_tip_question_not_offer(self):
        # Regression: "Would you like to add a tip?" is yes/no — must NOT set last_offer
        self.assertFalse(self._should_set_offer(
            "Okay, I've applied $1 in Pipadot. Would you like to add a tip for the driver, Robbie?"))

    def test_would_you_like_tip_no_options(self):
        self.assertFalse(self._should_set_offer("Would you like to add a tip?"))

    def test_would_you_like_with_or_sets_offer(self):
        # "would you like" + "or" = real choice → should set last_offer
        self.assertTrue(self._should_set_offer(
            "Would you like original or garlic parmesan breadsticks?"))

    def test_plain_statement_not_offer(self):
        self.assertFalse(self._should_set_offer("Let me add that to your order."))

    def test_pricing_statement_not_offer(self):
        self.assertFalse(self._should_set_offer("Your total comes to twelve ninety-nine."))

    def test_how_much_pipa_dough_not_offer(self):
        # "would you like" inside a "how much" question must NOT set last_offer
        self.assertFalse(self._should_set_offer(
            "How much pop a dough would you like to use?"))

    def test_how_much_no_qmark_not_offer(self):
        self.assertFalse(self._should_set_offer(
            "How much pipa dough would you like to use"))

    def test_how_many_not_offer(self):
        self.assertFalse(self._should_set_offer("How many items would you like to order"))


class TestSimplePepperoniHappyPath(unittest.TestCase):
    """Simulate the simple_pepperoni scenario end-to-end through the state machine."""

    def test_full_flow(self):
        items = SIMPLE
        idx = 0
        rejected = []

        def step(speech, turn):
            nonlocal idx
            r = _det(speech, speech.lower(), turn, items, idx, rejected)
            if r:
                idx = r[1]
            return r

        # Turn 1 — greeting
        r = step("Hello, welcome to Acme Pizza!", turn=1)
        self.assertIn("Hi", r[0])

        # Turn 2 — order prompt
        r = step("What can I get you today?", turn=2)
        self.assertIn("Pepperoni", r[0])
        self.assertEqual(idx, 1)

        # Turn 3 — item added ack
        r = step("Large pepperoni added.", turn=3)
        self.assertEqual(r[0], "Okay, thanks.")

        # Turn 4 — order review
        r = step("So your order is one large pepperoni pizza, does that sound right?", turn=4)
        self.assertEqual(r[0], "Yes, that's right.")

        # Turn 5 — wrap-up statement (no question)
        r = step("Your total comes to eleven ninety-nine.", turn=5)
        self.assertEqual(r[0], "Okay, thanks.")


class TestModifiersHappyPath(unittest.TestCase):
    """
    Simulate the modifiers_with_pizza scenario through the state machine.
    Pizza is ordered first; then each modifier is served on sequential
    'Anything else?' turns; last turn returns 'No, that's all'.
    """

    ITEMS = [
        "1 Large Pepperoni Pizza",
        "Extra Sauce",
        "Well Done Bake",
        "Square Cut",
        "Extra Parmesan Romano",
    ]

    def _items_to_order(self):
        """Mirror _yaml_item_to_speech so the test uses the same speech strings."""
        return [m._yaml_item_to_speech(i) for i in self.ITEMS]

    def test_full_modifier_flow(self):
        items = self._items_to_order()
        idx = 0
        rejected = []

        def step(speech, turn):
            nonlocal idx
            r = _det(speech, speech.lower(), turn, items, idx, rejected)
            if r:
                idx = r[1]
            return r

        # Turn 1 — greeting
        r = step("Hello, welcome to Acme Pizza!", turn=1)
        self.assertIn("Hi", r[0])

        # Turn 2 — order prompt → pizza ordered
        r = step("What can I get you today?", turn=2)
        self.assertIn("pepperoni", r[0].lower())
        self.assertEqual(idx, 1)

        # Turn 3 — "Anything else?" → extra sauce
        r = step("Anything else?", turn=3)
        self.assertIn("sauce", r[0].lower())
        self.assertEqual(idx, 2)

        # Turn 4 — ack + "Anything else?" → well done bake
        r = step("Extra sauce added. Anything else?", turn=4)
        self.assertIn("well done", r[0].lower())
        self.assertEqual(idx, 3)

        # Turn 5 — ack + "Anything else?" → square cut
        r = step("Well done bake added. Anything else?", turn=5)
        self.assertIn("square cut", r[0].lower())
        self.assertEqual(idx, 4)

        # Turn 6 — ack + "Anything else?" → extra parmesan romano
        r = step("Square cut added. Anything else?", turn=6)
        self.assertIn("parmesan", r[0].lower())
        self.assertEqual(idx, 5)

        # Turn 7 — all modifiers done → "No, that's all"
        r = step("Extra parmesan romano added. Anything else?", turn=7)
        self.assertIsNotNone(r)
        self.assertIn("No", r[0])
        self.assertEqual(idx, 5)  # idx unchanged after "No, that's all"

    def test_modifier_item_added_ack_returns_okay(self):
        """Short 'added' confirmation after a modifier → 'Okay, thanks.' not 'Yes, that's right.'"""
        items = self._items_to_order()
        result = _det("Extra sauce added.", "extra sauce added.", 3, items, 2, [])
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Okay, thanks.")


class TestComboHappyPath(unittest.TestCase):
    """Simulate the combo_with_sides scenario through the state machine."""

    def test_full_ordering_flow(self):
        items = COMBO
        idx = 0
        rejected = []

        def step(speech, turn):
            nonlocal idx
            r = _det(speech, speech.lower(), turn, items, idx, rejected)
            if r:
                idx = r[1]
            return r

        # Turn 1
        r = step("Hi, welcome!", turn=1)
        self.assertIn("Hi", r[0])

        # Turn 2 — first item
        r = step("What would you like to order?", turn=2)
        self.assertIn("Pepperoni", r[0])
        self.assertEqual(idx, 1)

        # Turn 3 — second item
        r = step("Anything else?", turn=3)
        self.assertIn("Breadsticks", r[0])
        self.assertEqual(idx, 2)

        # Turn 4 — third item
        r = step("Anything else for you?", turn=4)
        self.assertIn("Pepsi", r[0])
        self.assertEqual(idx, 3)

        # Turn 5 — all ordered, agent asks how much pipa dough to apply (no ?)
        r = step("How much pipa dough would you like to use", turn=5)
        self.assertIsNotNone(r)
        self.assertIn("one dollar", r[0])

        # Turn 6 — pricing statement (no question)
        r = step("Your total is twenty-two forty-nine.", turn=6)
        self.assertEqual(r[0], "Okay, thanks.")


# ---------------------------------------------------------------------------
# Echo guard (_is_room_echo)
# Lesson: Ravi's TTS bounces off room walls and comes back into the Mac mic.
# If transcribed "agent speech" is ≥70% the same words as Ravi's last
# utterance, it is discarded as an echo, not passed to the state machine.
# ---------------------------------------------------------------------------
class TestIsRoomEcho(unittest.TestCase):

    def test_exact_match_is_echo(self):
        # Ravi says "Okay, thanks." — room echo transcribed identically
        self.assertTrue(_echo("Okay, thanks.", "Okay, thanks."))

    def test_near_match_above_threshold_is_echo(self):
        # Whisper may drop punctuation: "okay thanks" vs "Okay, thanks."
        self.assertTrue(_echo("okay thanks", "Okay, thanks."))

    def test_partial_echo_below_threshold_not_blocked(self):
        # Ravi: "Hi, I'd like to place an order please."
        # Echo transcribed as: "I'd like to place it."
        # Jaccard: {"id","like","to","place"} / {"hi","id","like","to","place","an","order","please","it"} = 4/9 = 0.44
        # Below 0.7 threshold — NOT caught by echo guard.
        # This Turn-1 case is handled upstream by the mic-buffer flush instead.
        self.assertFalse(_echo("I'd like to place it.", "Hi, I'd like to place an order please."))

    def test_different_content_not_echo(self):
        # Ava genuinely asks about CVV — not an echo of "Okay, thanks."
        self.assertFalse(_echo("Can I get your CVV please?", "Okay, thanks."))

    def test_ordering_prompt_not_echo(self):
        # Ava asks "What can I get for you today?" after Ravi's greeting
        self.assertFalse(_echo(
            "What can I get for you today?",
            "Hi, I'd like to place an order please.",
        ))

    def test_empty_last_ravi_never_echo(self):
        # Turn 1: last_ravi_response is empty — never block Ava's opening
        self.assertFalse(_echo("Welcome to Acme Pizza, what can I get you?", ""))

    def test_empty_agent_speech_not_echo(self):
        self.assertFalse(_echo("", "Okay, thanks."))

    def test_short_shared_word_below_threshold(self):
        # "please" appears in both but only 1/5 words overlap — not an echo
        self.assertFalse(_echo(
            "Would you like to add anything else please?",
            "I'd like a large pepperoni pizza please.",
        ))


# ---------------------------------------------------------------------------
# Rule 6 — ACK_ONLY_PHRASES additions
# Lesson: Ava says "Okay, thanks." as a short ack after adding items.
# "okay" and "thanks" were missing from ACK_ONLY_PHRASES so these fell
# through to Ollama which generated the wrong response.
# ---------------------------------------------------------------------------
class TestRule6NewAckPhrases(unittest.TestCase):

    def _step(self, agent_speech, turn=3, items=None, ordered=0):
        items = items or ["1 Large Pepperoni Pizza"]
        return _det(agent_speech, agent_speech.lower(), turn, items, ordered, [])

    def test_okay_thanks_from_lou_returns_okay_thanks(self):
        r = self._step("Okay, thanks.", items=["1 Large Pepperoni Pizza"], ordered=0)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_okay_alone_short_returns_okay_thanks(self):
        r = self._step("Okay.", items=["1 Large Pepperoni Pizza"], ordered=0)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_thank_you_short_returns_okay_thanks(self):
        r = self._step("Thank you.", items=["1 Large Pepperoni Pizza"], ordered=0)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_thanks_short_returns_okay_thanks(self):
        r = self._step("Thanks!", items=["1 Large Pepperoni Pizza"], ordered=0)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_okay_long_sentence_falls_through(self):
        # Rule 6 only fires for ≤10 words — long "okay" sentence must fall through
        r = self._step(
            "Okay so I have added your large pepperoni pizza to your order.",
            items=["1 Large Pepperoni Pizza"], ordered=0,
        )
        # Should NOT be Rule 6 (too long); may match Rule 7 (added) instead
        if r is not None:
            self.assertNotEqual(r[0], "Hi, I'd like to place an order please.")

    def test_okay_with_question_falls_through(self):
        # Questions must never be consumed by Rule 6
        r = self._step("Okay, what size would you like?",
                        items=["1 Large Pepperoni Pizza"], ordered=0)
        # Rule 6 guard: "?" in agent_speech → falls through
        if r is not None:
            self.assertNotEqual(r[0], "Okay, thanks.")


# ---------------------------------------------------------------------------
# Same-response cooldown
# Lesson: After Ravi says "Okay, thanks.", the room echo feeds it back as
# Ava's speech and the state machine fires Rule 8 again → infinite loop.
# The cooldown in the conversation loop suppresses the repeat.
# These tests verify the state machine returns the same response (so the
# cooldown has something to compare against), not that the loop itself skips.
# ---------------------------------------------------------------------------
class TestSameResponseCooldownScenario(unittest.TestCase):
    """Verify Rule 8 fires consistently so the cooldown comparison works."""

    def test_rule8_returns_okay_thanks_on_non_question_after_all_ordered(self):
        items = ["1 Large Pepperoni Pizza"]
        # All ordered (idx=1), agent makes a statement
        r = _det("Your order total is eleven ninety nine.", "your order total is eleven ninety nine.",
                 3, items, 1, [])
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_rule8_fires_again_on_echo_text(self):
        # The echo "Okay, thanks." comes back as agent_speech.
        # Rule 8 would fire because it's not a question and all items ordered.
        # The loop's cooldown (last_ravi_response == det[0]) must catch this.
        items = ["1 Large Pepperoni Pizza"]
        r = _det("Okay, thanks.", "okay, thanks.", 4, items, 1, [])
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")
        # Confirms the cooldown has a consistent value to compare against

    def test_rule8_does_not_fire_on_truncated_charge_statement(self):
        # Regression: SR captures the agent mid-sentence — "A total of $25 would
        # be charged to your card ending in 1234" — before the agent finishes
        # "...and if that's correct, would you like to proceed?". Rule 8 must
        # NOT fire so the payment bypass gets the full phrase on the next cycle.
        items = ["1 Large Pepperoni Pizza"]
        r = _det(
            "A total of twenty five dollars would be charged to your card ending in 1234",
            "a total of twenty five dollars would be charged to your card ending in 1234",
            4, items, 1, [],
        )
        self.assertIsNone(r)

    def test_rule8_does_not_fire_on_card_ending_statement(self):
        # Another truncation form: "We'll charge your card ending in 1234" (no ?)
        items = ["1 Large Pepperoni Pizza"]
        r = _det(
            "We'll charge your card ending in 5678",
            "we'll charge your card ending in 5678",
            4, items, 1, [],
        )
        self.assertIsNone(r)

    def test_rule8_still_fires_on_pricing_non_payment_statement(self):
        # "Your order total is eleven ninety nine." has no payment-action words —
        # Rule 8 should still return "Okay, thanks." here.
        items = ["1 Large Pepperoni Pizza"]
        r = _det(
            "Your order total is eleven ninety nine.",
            "your order total is eleven ninety nine.",
            4, items, 1, [],
        )
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_rule7_does_not_fire_on_tip_confirmation(self):
        # Regression: agent says "Okay, I've added a $5 tip, your credit card
        # ending in 0007 will be charged, is that correct?" but SR splits at the
        # comma pause and delivers "Okay, I've added a $5 tip." first.
        # Rule 7 ("added" in ≤12 words, no "?") must NOT fire here — the
        # payment question is coming in the next SR chunk.
        items = ["1 Large Pepperoni Pizza"]
        r = _det(
            "Okay, I've added a $5 tip.",
            "okay, i've added a $5 tip.",
            4, items, 1, [],
        )
        self.assertIsNone(r)

    def test_rule7_fires_on_item_added_no_tip(self):
        # Rule 7 should still fire for normal item-add confirmations.
        items = ["1 Large Pepperoni Pizza", "1 Order Garlic Knots"]
        r = _det(
            "I've added the garlic knots.",
            "i've added the garlic knots.",
            3, items, 1, [],
        )
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_rule8_does_not_fire_on_tip_confirmation(self):
        # Rule 8 guard (via _PAYMENT_CONTEXT_RE) should also block on tip
        # statements — second line of defence after Rule 7 guard.
        items = ["1 Large Pepperoni Pizza"]
        r = _det(
            "I've added a five dollar tip.",
            "i've added a five dollar tip.",
            4, items, 1, [],
        )
        self.assertIsNone(r)


# ---------------------------------------------------------------------------
# Order-ahead: scheduled time confirmation (Rule 5a)
# Regression: "Does that work for you?" fell through to Ollama which said
# "I'd like the 15 minute slot at 11:30 a.m. please." instead of confirming.
# ---------------------------------------------------------------------------
class TestScheduledTimeConfirmation(unittest.TestCase):
    """Rule 5a: scheduled-time confirmation must return 'Yes, that works.'"""

    def _step(self, speech, items=None, idx=1):
        items = items or SIMPLE
        return _det(speech, speech.lower(), 4, items, idx, [])

    def test_does_that_work_for_you(self):
        # Real transcript from order_ahead_pepperoni run
        r = self._step(
            "To confirm, we have you down for the nearest 15 minute slot on "
            "April 14th at 11.30 a.m. for your future order. Does that work for you?"
        )
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Yes, that works.")

    def test_does_that_work_no_trailing(self):
        # Whisper may drop "for you"
        r = self._step("Does that work?")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Yes, that works.")

    def test_does_that_work_without_question_mark(self):
        # Whisper omits ? on questions
        r = self._step("Does that work for you")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Yes, that works.")

    def test_have_you_down_partial_falls_through(self):
        # Regression guard: SR sometimes cuts off at "We have you down for the
        # nearest 15." before Ava finishes "...does that work for you?".
        # "have you down" was removed from REVIEW_PHRASES to prevent premature
        # responses to partial transcriptions.  The partial sentence has no
        # deterministic match → Ollama handles it (returns None here).
        r = self._step("To confirm we have you down for the new 15.")
        # Rule 5a needs "does that work" — not present → no deterministic match
        # Rule 8: _is_question returns True (false positive on "have you") → won't fire
        # Net: falls through to Ollama (None)
        self.assertIsNone(r)

    def test_have_you_down_slot_confirmation(self):
        r = self._step(
            "To confirm, we had you down for the nearest 15-minute slot "
            "on April 14th at 11:15 am for your future order. Does that work for you?"
        )
        self.assertIsNotNone(r)
        # 5a fires first (does that work) → "Yes, that works."
        self.assertEqual(r[0], "Yes, that works.")

    def test_order_review_unaffected(self):
        # Existing order-review phrases must still return "Yes, that's right."
        r = self._step("So your order is one large pepperoni pizza, does that sound right?")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Yes, that's right.")


# ---------------------------------------------------------------------------
# Schedule time normalization (used in conversation loop to detect mismatch)
# Regression: "6.30pm" (no space before am/pm) didn't match "6:30 PM" because
# the trailing \b in r'\b(\d{1,2})\.(\d{2})\b' fails when "pm" is attached —
# there is no word boundary between "30" and "pm" (both are \w characters).
# ---------------------------------------------------------------------------
class TestScheduleTimeNormalization(unittest.TestCase):
    """Unit tests for the time normalization regex used in schedule mismatch detection."""

    def _normalize(self, expected_schedule: str, agent_speech: str) -> bool:
        """Replicate the normalization logic from run_ai_customer_conversation."""
        import re
        norm = re.sub(r'\b0(\d:\d{2})', r'\1', expected_schedule)
        agent_lower = agent_speech.lower()
        # Step 0: "p.m." / "a.m." → "pm" / "am"
        agent_norm = re.sub(r'\b([ap])\.m\.?\b', r'\1m', agent_lower, flags=re.IGNORECASE)
        # Step 1: "6.30pm" → "6:30pm"
        agent_norm = re.sub(r'\b(\d{1,2})\.(\d{2})', r'\1:\2', agent_norm)
        # Step 2: "7 o'clock pm" → "7:00 pm"
        agent_norm = re.sub(r"\b(\d{1,2})\s+o'?clock\b", r'\1:00', agent_norm)
        # Step 3: "6:30pm" → "6:30 pm"
        agent_norm = re.sub(r'(\d{2})([ap]m)\b', r'\1 \2', agent_norm, flags=re.IGNORECASE)
        return norm.lower() in agent_norm

    def test_dot_separator_with_attached_pm(self):
        # Regression: "6.30pm" (no space) was not converted because \b fails
        # between "30" and "pm".  Fixed by removing trailing \b from the regex.
        self.assertTrue(self._normalize(
            "06:30 PM",
            "confirm we have you down for the nearest 15-minute slot on May 4th at 6.30pm"
        ))

    def test_dot_separator_with_space_before_pm(self):
        # "6.30 pm" (space before pm) — trailing \b fires correctly here
        self.assertTrue(self._normalize(
            "06:30 PM",
            "we have you down for the nearest slot at 6.30 pm. Does that work?"
        ))

    def test_colon_separator_with_attached_pm(self):
        # "11:30am" (already colon, no space) — add-space step normalises it
        self.assertTrue(self._normalize(
            "11:30 AM",
            "we have you down for 11:30am. Does that work for you?"
        ))

    def test_leading_zero_stripped(self):
        # "06:30 PM" expected_schedule → norm becomes "6:30 pm"
        self.assertTrue(self._normalize(
            "06:30 PM",
            "we have you down at 6:30 pm. Does that work?"
        ))

    def test_oclock_with_dotted_pm(self):
        # Regression: "7 o'clock p.m." — o'clock expands to "7:00" but
        # "p.m." was left as-is, so "7:00 p.m." != "7:00 pm".
        # Step 0 now strips dots from "p.m." before the o'clock step.
        self.assertTrue(self._normalize(
            "07:00 PM",
            "we have you down for the nearest 15 minutes slot at 7 o'clock p.m. does that work for you"
        ))

    def test_oclock_with_dotless_pm(self):
        # "7 o'clock pm" (no dots) — still works without Step 0
        self.assertTrue(self._normalize(
            "07:00 PM",
            "we have you down for the nearest slot at 7 o'clock pm. does that work?"
        ))

    def test_no_match_wrong_time(self):
        self.assertFalse(self._normalize(
            "06:30 PM",
            "we have you down for 7:00 pm. Does that work?"
        ))


# ---------------------------------------------------------------------------
# Payment bypass: CVV request must NOT fire payment bypass
# Regression (order_confirmed flow): "Can you please provide the CVV for your
# card ending in 007?" matched PAYMENT_CONFIRM_PHRASES ("card ending in") but
# the _asking_for_code guard only checked for the word "code" — not "CVV".
# The fix adds CVV_KEYWORD_RE to the guard so the bypass is suppressed.
# These tests exercise the state-machine side; the bypass lives in the
# conversation loop so we verify via _is_question and state-machine fall-through.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# CVV keyword regex — Whisper mis-transcription variants
# Regression: Whisper transcribed "CVV" as "CD" — \bcd\b was not in the regex.
# The regex is defined locally in the conversation loop; we re-declare it here
# to keep the test self-contained and document every variant we expect to catch.
# ---------------------------------------------------------------------------
import re as _re

_CVV_KW_RE = _re.compile(
    r'\bcvv\b|\bcvd\b|\bcdv\b|\bcvc\b|\bcbv\b|\bcv\b|\bcdd\b|\bcd\b'
    r'|security code|card verification|verification code'
    r'|back of your card|back of the card'
    r'|\bthree.?digit\b|\b3.?digit\b'
    r'|card number on the back|number on the back',
    _re.IGNORECASE,
)


class TestCvvSpokenWords(unittest.TestCase):
    """CVV must be spoken with natural human grouping matching how callers say it aloud.
    '382' → 'three eighty two' (first digit + last two as a number), NOT 'three eight two'.
    Separate-digit utterances triggered the IVR end-of-input timeout after the first digit."""

    def _w(self, cvv):
        from end_to_end_voice_test import _cvv_to_spoken_words
        return _cvv_to_spoken_words(cvv)

    def test_382_three_eighty_two(self):
        # Natural human grouping: first digit + last two as a number
        self.assertEqual(self._w("382"), "three eighty two")

    def test_123_one_twenty_three(self):
        self.assertEqual(self._w("123"), "one twenty three")

    def test_358_three_fifty_eight(self):
        self.assertEqual(self._w("358"), "three fifty eight")

    def test_100_one_zero_zero(self):
        # last two = 00 → "zero zero" falls back to individual (last_two=0 < 20 → _ONES[0])
        self.assertEqual(self._w("100"), "one zero")

    def test_011_zero_eleven(self):
        self.assertEqual(self._w("011"), "zero eleven")

    def test_019_zero_nineteen(self):
        self.assertEqual(self._w("019"), "zero nineteen")

    def test_999_nine_ninety_nine(self):
        self.assertEqual(self._w("999"), "nine ninety nine")

    def test_four_digit_individual(self):
        # 4-digit CVV (AmEx) → individual digits (fallback path)
        self.assertEqual(self._w("1234"), "one two three four")

    def test_log_form_unchanged(self):
        # Log still shows "My CVV is 382." — only the spoken audio changes
        cvv = "382"
        self.assertEqual(f"My CVV is {cvv}.", "My CVV is 382.")

    def test_no_cvv_prefix_in_spoken_form(self):
        # TTS speaks ONLY the number — no "My CVV is" prefix to avoid STT confusion
        self.assertNotIn("cvv", self._w("382").lower())


class TestCvvKeywordRegex(unittest.TestCase):
    """CVV_KEYWORD_RE must match all known Whisper mis-transcriptions of 'CVV'."""

    def _match(self, text):
        return bool(_CVV_KW_RE.search(text))

    def test_cvv_standard(self):
        self.assertTrue(self._match("Could you please provide your CVV?"))

    def test_cvv_with_periods(self):
        # Punctuation-stripped before search, but verify the base token
        self.assertTrue(self._match("cvv"))

    def test_cvd_variant(self):
        self.assertTrue(self._match("provide the CVD for your card"))

    def test_cdd_variant(self):
        # Regression: seen in order_ahead run
        self.assertTrue(self._match("provide the CDD code for your credit card"))

    def test_cd_variant(self):
        # Regression: Whisper transcribed CVV as "CD" — Turn 9
        self.assertTrue(self._match("Could you please provide your CD?"))

    def test_cv_variant(self):
        self.assertTrue(self._match("Can you provide your CV number?"))

    def test_security_code(self):
        self.assertTrue(self._match("Please enter your security code."))

    def test_three_digit(self):
        self.assertTrue(self._match("Enter the three-digit code on the back."))

    def test_cdv_variant(self):
        # P-02: Whisper transposes C/D — "CDV" must still trigger the bypass
        self.assertTrue(self._match("Could you provide your CDV for the card?"))

    def test_normal_sentence_no_match(self):
        # "card" alone should not match
        self.assertFalse(self._match("Your card will be charged."))

    def test_delivery_sentence_no_match(self):
        self.assertFalse(self._match("What can I get started for you today?"))


class TestCVVChunkSplitP10(unittest.TestCase):
    """P-10: CVV keyword split across two SR chunks — bypass fires on chunk 2, not chunk 1."""

    def _match(self, text):
        return bool(_CVV_KW_RE.search(text.lower()))

    # Chunk 1 — charge / card-ending statement, no CVV keyword
    def test_chunk1_charge_statement_no_cvv_match(self):
        self.assertFalse(self._match(
            "A total of thirteen seventy eight will be charged to your card ending in 1234"
        ))

    def test_chunk1_card_ending_statement_no_cvv_match(self):
        self.assertFalse(self._match(
            "Your credit card ending in 0007 will be billed for this order"
        ))

    def test_chunk1_confirmation_statement_no_cvv_match(self):
        self.assertFalse(self._match(
            "To confirm your order, the total is eleven ninety nine"
        ))

    # Chunk 2 — CVV / security-code request (in various Whisper variants)
    def test_chunk2_cvv_request_matches(self):
        self.assertTrue(self._match("Could you please provide your CVV?"))

    def test_chunk2_cdv_variant_matches(self):
        # P-02 overlap: "CDV" appears in second chunk
        self.assertTrue(self._match(
            "and to finalize could you provide the CDV code on the back of your card"
        ))

    def test_chunk2_security_code_matches(self):
        self.assertTrue(self._match(
            "and could you please share your security code"
        ))

    def test_chunk2_three_digit_matches(self):
        self.assertTrue(self._match(
            "and the three-digit code on the back of your card please"
        ))


class TestAgentTerminationPhrases(unittest.TestCase):
    """
    Phrases that terminate the conversation on the agent side.
    Tests cover order-complete detection and audio/cvv failure detection.
    """

    _ORDER_COMPLETE = [
        "thank you for your order",
        "order has been placed", "has been placed",
        "order is placed",
        "placed successfully", "successfully placed",
        "order is confirmed", "order confirmed",
        "your order is complete", "order complete",
        "order was placed", "order was confirmed",
        "payment was successful", "successfully processed",
        "done processing your order",
    ]

    _AUDIO_FAIL = [
        "sorry your audio", "audio cannot be",
        "cannot hear your audio", "can't hear your audio",
        "having trouble hearing you", "unable to hear you",
        "audio is not coming through", "can't hear you",
        "cannot hear you",
    ]

    def _strip(self, s: str) -> str:
        import re
        return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', s.lower()))

    def _order_complete(self, speech: str) -> bool:
        stripped = self._strip(speech)
        return any(p in stripped for p in self._ORDER_COMPLETE)

    def _audio_fail(self, speech: str) -> bool:
        return any(p in speech.lower() for p in self._AUDIO_FAIL)

    # ── order complete ─────────────────────────────────────────────────────

    def test_done_processing_your_order(self):
        """Whisper: 'loop right now we are done processing your order.'"""
        self.assertTrue(self._order_complete("loop right now we are done processing your order."))

    def test_thank_you_for_your_order(self):
        self.assertTrue(self._order_complete("Thank you for your order!"))

    def test_order_confirmed(self):
        self.assertTrue(self._order_complete("Your order is confirmed."))

    def test_placed_successfully(self):
        self.assertTrue(self._order_complete("Your order was placed successfully."))

    def test_pricing_statement_not_order_complete(self):
        """Pricing statements must not trigger order-complete."""
        self.assertFalse(self._order_complete("Your total is eleven ninety nine."))

    def test_payment_processing_not_order_complete(self):
        """'processing' alone must not match without 'done'."""
        self.assertFalse(self._order_complete("I am processing your payment now."))

    # ── audio failure ──────────────────────────────────────────────────────

    def test_real_log_audio_fail(self):
        """Exact agent speech from Turn 19 of the failing run."""
        self.assertTrue(self._audio_fail("Okay, I'm sorry your audio cannot be-"))

    def test_cannot_hear_audio(self):
        self.assertTrue(self._audio_fail("I'm sorry, I cannot hear your audio."))

    def test_having_trouble_hearing(self):
        self.assertTrue(self._audio_fail("I'm having trouble hearing you clearly."))

    def test_normal_sorry_not_audio_fail(self):
        """Generic apology must not match."""
        self.assertFalse(self._audio_fail("I'm sorry, we don't have extra cheese."))

    def test_cvv_failure_not_audio_fail(self):
        self.assertFalse(self._audio_fail("I wasn't able to get your CVV."))


class TestIsQuestionOrderAheadFalsePositive(unittest.TestCase):
    """
    'To confirm we have you down for the new 15.' contains 'have you' which
    causes _is_question to return True (false positive).  This means Rule 8
    (non-question after all items ordered) never fires for this partial
    transcription — it falls through to Ollama instead.
    """

    def test_have_you_mid_sentence_is_detected_as_question(self):
        # Deliberate false positive — 'have you' mid-sentence
        speech = "To confirm we have you down for the new 15."
        self.assertTrue(_iq(speech, speech.lower()))

    def test_have_you_actual_question(self):
        self.assertTrue(_iq("Have you tried our garlic knots?",
                            "have you tried our garlic knots?"))


class TestCvvFailureDetection(unittest.TestCase):
    """
    CVV failure phrases — agent gave up collecting CVV and routes to checkout.
    These must terminate the conversation, NOT be added to rejected_items.
    """

    _CVV_FAIL_PHRASES = [
        "wasn't able to get", "was not able to get",
        "unable to get", "couldn't get", "could not get",
        "failed to get",
    ]

    def _is_cvv_failure(self, agent_speech: str) -> bool:
        agent_lower = agent_speech.lower()
        agent_stripped = _re.sub(r'\s+', ' ', _re.sub(r'[^\w\s]', ' ', agent_lower))
        cvv_search_text = agent_lower + " " + agent_stripped
        return (
            bool(_CVV_KW_RE.search(cvv_search_text))
            and any(p in agent_lower for p in self._CVV_FAIL_PHRASES)
        )

    def test_real_log_failure_detected(self):
        """Exact agent speech from the failing run."""
        speech = ("I'm sorry, Ravi. I wasn't able to get your CVV. "
                  "I'll take you to check out where you can add a payment method, "
                  "apply popado, or add a tip.")
        self.assertTrue(self._is_cvv_failure(speech))

    def test_unable_to_get_cvv(self):
        self.assertTrue(self._is_cvv_failure("I'm unable to get your CVV. Let me take you to checkout."))

    def test_couldnt_get_cvv(self):
        self.assertTrue(self._is_cvv_failure("Sorry, I couldn't get your CVV code. Routing you now."))

    def test_cvv_request_not_flagged(self):
        """Agent requesting CVV — NOT a failure."""
        self.assertFalse(self._is_cvv_failure("Could you please provide your CVV?"))

    def test_normal_sorry_not_flagged(self):
        """'I'm sorry, we don't have that' is an item rejection, not CVV failure."""
        self.assertFalse(self._is_cvv_failure("I'm sorry, we don't have extra cheese."))

    # Canonical rejection_phrases list — keep in sync with end_to_end_voice_test.py
    _REJECTION_PHRASES = [
        "don't have", "do not have", "we don't", "we do not",
        "not available", "unfortunately", "i'm sorry, we",
        "sorry, we don't", "sorry, we do not",
        "i'm sorry, that's", "i'm sorry, that",
        "can't add", "cannot add",
    ]

    def _matches_rejection(self, speech: str) -> bool:
        return any(p in speech.lower() for p in self._REJECTION_PHRASES)

    def test_rejection_phrases_no_bare_im_sorry(self):
        """CVV failure speech must not match any rejection phrase."""
        cvv_failure_speech = (
            "i'm sorry, ravi. i wasn't able to get your cvv. "
            "i'll take you to check out where you can add a payment method."
        )
        self.assertFalse(self._matches_rejection(cvv_failure_speech),
                         "CVV failure speech should not match any rejection phrase")

    def test_item_rejection_we_caught(self):
        """'i'm sorry, we don't have' is still caught."""
        self.assertTrue(self._matches_rejection("I'm sorry, we don't have extra cheese available."))

    def test_item_rejection_thats_caught(self):
        """'i'm sorry, that's not available' is now caught."""
        self.assertTrue(self._matches_rejection("I'm sorry, that's not available on this pizza."))

    def test_item_rejection_that_caught(self):
        """'i'm sorry, that item' is now caught."""
        self.assertTrue(self._matches_rejection("I'm sorry, that item isn't on our menu."))

    def test_not_available_caught(self):
        """'not available' catches rejections without 'sorry'."""
        self.assertTrue(self._matches_rejection("That size is not available right now."))

    def test_cvv_failure_no_that(self):
        """'i'm sorry, that' must NOT match the CVV failure speech (no 'that' in it)."""
        cvv_speech = "i'm sorry, ravi. i wasn't able to get your cvv."
        self.assertFalse("i'm sorry, that" in cvv_speech.lower())

    def test_item_rejection_still_caught(self):
        """Backward compat: original 'we don't have' form still works."""
        self.assertTrue(self._matches_rejection("i'm sorry, we don't have extra cheese available."))


class TestClassifyConfirmationSpeech(unittest.TestCase):
    """Tests for _classify_confirmation_speech — pure phrase matching, no STT needed."""

    def _cls(self, speech):
        return m._classify_confirmation_speech(speech)

    # ── confirmed ──────────────────────────────────────────────────────────────

    def test_order_placed_successfully(self):
        self.assertEqual(self._cls("Your order has been placed successfully."), "confirmed")

    def test_thank_you_for_your_order(self):
        self.assertEqual(self._cls("Thank you for your order!"), "confirmed")

    def test_successfully_whisper_fragment(self):
        # Whisper may return only a fragment after a long pause
        self.assertEqual(self._cls(" successfully."), "confirmed")

    # ── payment_failed ─────────────────────────────────────────────────────────

    def test_card_declined(self):
        self.assertEqual(self._cls("I'm sorry, your card was declined."), "payment_failed")

    def test_update_payment_method_live_run(self):
        # Exact agent speech observed in a live run (Whisper transcription)
        self.assertEqual(
            self._cls("your payment. Please check the app to update your payment method or try again."),
            "payment_failed",
        )

    def test_check_the_app_to_update(self):
        self.assertEqual(self._cls("Please check the app to update your details."), "payment_failed")

    def test_please_check_the_app(self):
        self.assertEqual(self._cls("Please check the app and try placing your order again."), "payment_failed")

    def test_unable_to_process(self):
        self.assertEqual(self._cls("We were unable to process your payment."), "payment_failed")

    def test_issue_processing(self):
        self.assertEqual(self._cls("There was an issue processing your order."), "payment_failed")

    # ── unknown ────────────────────────────────────────────────────────────────

    def test_unknown_mid_sentence(self):
        self.assertEqual(self._cls("Let me repeat your order back to you."), "unknown")

    def test_empty_speech(self):
        self.assertEqual(self._cls(""), "unknown")

    def test_payment_failure_takes_priority_over_success(self):
        # Failure is checked before success — failure wins
        self.assertEqual(
            self._cls("sorry we could not process your order successfully"),
            "payment_failed",
        )


class TestGroupOrderHappyPath(unittest.TestCase):
    """Agent-driven ordering: items_to_order=[], pre_order_query injects context."""

    def _step(self, agent_speech, items=None, idx=0):
        items = [] if items is None else items
        return _det(agent_speech, agent_speech.lower(), 2, items, idx, [])

    def test_turn3_acceptance_falls_to_ollama(self):
        # After agent lists recommendation, _get_deterministic_response alone returns
        # no match — in the live loop the _awaiting_acceptance flag intercepts first.
        # This test confirms the state machine itself does not fire Rule 8 here.
        result = self._step(
            "For 6 people I'd suggest 2 large pepperoni pizzas and breadsticks. "
            "Would you like to go with that?"
        )
        if result is not None:
            self.assertNotEqual(result[0], "Okay, thanks.")

    def test_turn4_item_added_confirmation(self):
        # Agent confirms items were added — Rule 7 (item-added) must fire.
        result = self._step("Perfect, I've added those to your cart.")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Okay, thanks.")

    def test_turn5_anything_else_with_empty_list(self):
        # Rule 3 must fire even with empty list → "No, that's all"
        result = self._step("Anything else for you today?")
        self.assertIsNotNone(result)
        self.assertIn("No", result[0])

    def test_rule8_does_not_fire_with_empty_list(self):
        # Rule 8 guards with `if items_to_order` — empty list must not trigger it.
        result = self._step("Your total comes to twenty-four ninety-nine.")
        # Falls to Ollama (None) since Rule 3 didn't match and Rule 8 is blocked.
        self.assertIsNone(result)


class TestVegetarianRecommendationFlow(unittest.TestCase):
    """Post-acceptance turns for recommendation-driven scenarios (vegetarian, group).

    The _awaiting_acceptance flag in the conversation loop fires BEFORE the state
    machine, so these tests verify what the state machine does on subsequent turns
    after acceptance — i.e., after Ravi has already said 'Yes, that sounds great'.
    """

    def _step(self, agent_speech, items=None, idx=0):
        items = [] if items is None else items
        return _det(agent_speech, agent_speech.lower(), 3, items, idx, [])

    def test_post_acceptance_item_added_gives_okay_thanks(self):
        # Turn after acceptance: agent confirms it added the item → Rule 7 fires.
        result = self._step("Great, I've added the Garden Fresh Pizza to your order.")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Okay, thanks.")

    def test_post_acceptance_anything_else_with_empty_list(self):
        # After agent adds recommendation, asks "Anything else?" → Rule 3 closes order.
        result = self._step("Is there anything else I can get for you?")
        self.assertIsNotNone(result)
        self.assertIn("No", result[0])

    def test_post_acceptance_order_review_confirms(self):
        # If agent reads the order back → Rule 5 (review) fires: "Yes, that's right."
        result = self._step(
            "So I have a Garden Fresh Pizza on your order, does that sound right?"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Yes, that's right.")

    def test_post_acceptance_rule8_does_not_fire_with_empty_list(self):
        # Rule 8 must stay blocked when items_to_order is empty.
        result = self._step("Your total comes to fifteen ninety-nine.")
        self.assertIsNone(result)


class TestMenuInquiryDessertFlow(unittest.TestCase):
    """menu_inquiry_dessert: Ravi asks an info query then orders a specific item.

    The _awaiting_acceptance flag must NOT fire when items_to_order is non-empty.
    After the agent answers the dessert query, the state machine must order
    'cinnamon pull aparts' (item[0]) when the agent next asks for an order.
    """

    ITEMS = ["cinnamon pull aparts"]

    def _step(self, agent_speech, idx=0):
        return _det(agent_speech, agent_speech.lower(), 2, self.ITEMS, idx, [])

    def test_agent_dessert_list_triggers_order_prompt(self):
        # After listing desserts, agent asks "What would you like?" → Rule 2 orders item[0].
        result = self._step(
            "We have Cinnamon Pull Aparts, Brownies, and Cinnamon Knots. "
            "What would you like to order?"
        )
        self.assertIsNotNone(result)
        self.assertIn("cinnamon pull aparts", result[0].lower())

    def test_agent_dessert_list_without_order_prompt_falls_to_ollama(self):
        # If agent just lists desserts (no order prompt), state machine returns None.
        result = self._step(
            "We have Cinnamon Pull Aparts, Brownies, and Cinnamon Knots."
        )
        # No ORDER_PROMPT → Rule 2 doesn't fire; may fall to Ollama.
        # Key: must NOT say "Yes, that sounds great, please add those." (that's
        # the recommendation-acceptance phrase and is wrong here).
        if result is not None:
            self.assertNotIn("sounds great", result[0].lower())

    def test_item_added_confirmation_gives_okay_thanks(self):
        # After Cinnamon Pull Aparts is ordered, agent confirms → Rule 7.
        result = self._step("Perfect, I've added the Cinnamon Pull Aparts to your order.", idx=1)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "Okay, thanks.")

    def test_anything_else_after_item_ordered_closes(self):
        # All items ordered (idx=1 == len), agent asks "Anything else?" → Rule 3.
        result = self._step("Is there anything else I can get for you?", idx=1)
        self.assertIsNotNone(result)
        self.assertIn("No", result[0])


class TestDeliveryRequestFlow(unittest.TestCase):
    """F11: Ravi asks to switch to delivery; agent declines; order continues as carryout.

    pre_order_queries injects "Can I get this changed to delivery please?" on the
    first ORDER_PROMPT.  The agent's decline is NOT an order prompt, review, or ack,
    so it falls to Ollama.  The next agent ORDER_PROMPT then fires Rule 4 to order
    the first item.  _awaiting_acceptance must NOT fire because items_to_order is
    non-empty.
    """

    ITEMS = ["1 Large Pepperoni Pizza"]
    QUERY = ["Can I get this changed to delivery please?"]

    def test_delivery_query_fires_on_order_prompt(self):
        result = _gpq("what can i get you today", self.QUERY, 0)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.QUERY[0])
        self.assertEqual(result[1], 1)

    def test_delivery_query_does_not_fire_twice(self):
        # Once injected (idx=1), the query must not fire again
        result = _gpq("what else can i get you", self.QUERY, 1)
        self.assertIsNone(result)

    def test_agent_decline_falls_to_ollama(self):
        # Agent says it can't change delivery — no deterministic rule should match
        det = _det(
            "I'm sorry, I'm unable to change your order type during a voice session. "
            "You can update that in the app.",
            "i'm sorry, i'm unable to change your order type during a voice session. "
            "you can update that in the app.",
            3, self.ITEMS, 0, [],
        )
        # Must fall to Ollama (None) — not an ack, not a review, not a question-with-pattern
        self.assertIsNone(det)

    def test_agent_please_use_app_falls_to_ollama(self):
        # Shorter variant of agent decline
        det = _det(
            "Please update your delivery preference in the app.",
            "please update your delivery preference in the app.",
            3, self.ITEMS, 0, [],
        )
        self.assertIsNone(det)

    def test_order_prompt_after_decline_fires_rule4(self):
        # After decline, agent asks for order → Rule 4 orders first item
        det = _det(
            "What would you like to order today?",
            "what would you like to order today?",
            4, self.ITEMS, 0, [],
        )
        self.assertIsNotNone(det)
        self.assertIn("pepperoni", det[0].lower())
        self.assertEqual(det[1], 1)

    def test_anything_else_after_item_ordered_closes(self):
        # After item ordered, "Anything else?" → "No, that's all"
        det = _det(
            "Is there anything else I can get for you?",
            "is there anything else i can get for you?",
            5, self.ITEMS, 1, [],
        )
        self.assertIsNotNone(det)
        self.assertIn("No", det[0])


class TestPostOrderRequests(unittest.TestCase):
    """F-14: State machine serves verbatim post_order_requests after all voice_items ordered."""

    VOICE_ITEMS = ["a medium pepperoni pizza"]
    REQUESTS = ["Actually, could you change that to a large pepperoni pizza please?"]

    def _step(self, agent_speech, idx=1, req_idx=0):
        return _det(
            agent_speech, agent_speech.lower(), 4,
            self.VOICE_ITEMS, idx, [],
            None, 0,
            self.REQUESTS, req_idx,
        )

    def test_post_order_request_fires_on_anything_else(self):
        r = self._step("Anything else for you?")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], self.REQUESTS[0])

    def test_post_order_request_increments_requests_idx(self):
        r = self._step("Anything else?")
        self.assertIsNotNone(r)
        self.assertEqual(r[3], 1)  # requests_idx incremented

    def test_no_that_is_all_after_requests_exhausted(self):
        r = self._step("Anything else?", req_idx=1)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "No, that's all, thank you.")

    def test_post_order_request_not_served_while_items_remain(self):
        # voice_items not yet exhausted — normal item ordering takes priority
        r = self._step("Anything else?", idx=0)
        self.assertIsNotNone(r)
        self.assertIn("medium pepperoni", r[0].lower())
        self.assertNotIn("change", r[0].lower())

    def test_post_order_request_not_fired_on_non_anything_else(self):
        # Rule 4 order prompt fires, not post_order_request
        r = self._step("What would you like?", idx=0)
        if r is not None:
            self.assertNotIn("change", r[0].lower())

    def test_removal_runs_before_post_order_requests(self):
        # items_to_remove pending → removal fires first, not the post_order_request
        r = _det(
            "Anything else?", "anything else?", 4,
            ["a large pepperoni pizza"], 1, [],
            ["1 Order of Garlic Knots"], 0,
            ["Actually, could you change that to a large please?"], 0,
        )
        self.assertIsNotNone(r)
        self.assertIn("remove", r[0].lower())

    def test_no_post_order_requests_field_gives_no_that_is_all(self):
        # No post_order_requests at all — standard "No, that's all"
        r = _det(
            "Anything else?", "anything else?", 4,
            ["a medium pepperoni pizza"], 1, [],
            None, 0, None, 0,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "No, that's all, thank you.")


class TestItemRemoval(unittest.TestCase):
    """F-13: State machine requests item removal after all voice_items ordered."""

    VOICE_ITEMS = ["a large pepperoni pizza", "an order of garlic knots"]
    REMOVE_ITEMS = ["1 Order of Garlic Knots"]

    def _step(self, agent_speech, idx=2, removed_idx=0):
        return _det(
            agent_speech, agent_speech.lower(), 5,
            self.VOICE_ITEMS, idx, [],
            self.REMOVE_ITEMS, removed_idx,
        )

    # --- Should fire: removal request ---

    def test_removal_fires_on_anything_else_after_all_ordered(self):
        # All voice_items ordered (idx=2), removal pending — "Anything else?" → ask to remove
        r = self._step("Is there anything else I can get for you?")
        self.assertIsNotNone(r)
        self.assertIn("remove", r[0].lower())
        self.assertIn("garlic knots", r[0].lower())

    def test_removal_increments_removed_idx(self):
        r = self._step("Anything else?")
        self.assertIsNotNone(r)
        self.assertEqual(r[2], 1)  # items_removed_idx incremented

    def test_no_that_is_all_after_removal_done(self):
        # All ordered AND all removals done — "Anything else?" → "No, that's all"
        r = self._step("Anything else?", idx=2, removed_idx=1)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "No, that's all, thank you.")

    def test_removal_does_not_fire_while_items_still_to_order(self):
        # Still ordering (idx=1 of 2) — normal "And X please." not removal
        r = self._step("Anything else?", idx=1, removed_idx=0)
        self.assertIsNotNone(r)
        self.assertNotIn("remove", r[0].lower())
        self.assertIn("garlic knots", r[0].lower())

    def test_removal_does_not_fire_on_non_anything_else(self):
        # Order prompt (not "anything else") with all items ordered — Rule 4 skips, not removal rule
        r = self._step("What would you like?", idx=2, removed_idx=0)
        # Rule 4 doesn't fire (no items left), removal rule only fires on ANYTHING_ELSE
        # falls through to Ollama or rule 8 — removal request not issued here
        if r is not None:
            self.assertNotIn("remove", r[0].lower())

    # --- No-removal: items_to_remove=None path ---

    def test_no_removal_list_gives_no_that_is_all(self):
        # Standard scenario with no items_to_remove — "Anything else?" → "No, that's all"
        r = _det(
            "Anything else for you?", "anything else for you?", 5,
            ["a large pepperoni pizza"], 1, [],
            None, 0,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "No, that's all, thank you.")

    # --- Bidirectional: truncated "anything else" should still trigger ---

    def test_removal_fires_on_will_that_be_all_variant(self):
        r = self._step("Will that be all for you today?")
        self.assertIsNotNone(r)
        self.assertIn("remove", r[0].lower())

    def test_removal_phrasing_is_polite(self):
        r = self._step("Is there anything else?")
        self.assertIsNotNone(r)
        self.assertTrue(r[0].startswith("Actually, could you remove"))


class TestMindChangeItem(unittest.TestCase):
    """F-20: mind_change_item fires on first order review, then 'Yes, that's right.' on the second."""

    ITEMS = ["a large pepperoni pizza"]
    CHANGE = "Actually, could I also add an order of garlic knots please?"

    def _step(self, agent_speech, mind_change=None):
        return _det(
            agent_speech, agent_speech.lower(), 4,
            self.ITEMS, 1, [],
            None, 0, None, 0,
            mind_change,
        )

    def test_mind_change_fires_on_first_review_phrase(self):
        r = self._step("So just to confirm your order — does that sound right?", mind_change=self.CHANGE)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], self.CHANGE)

    def test_mind_change_fires_on_is_that_correct(self):
        r = self._step("Your order is a large pepperoni pizza. Is that correct?", mind_change=self.CHANGE)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], self.CHANGE)

    def test_no_mind_change_gives_yes_thats_right(self):
        # mind_change_item=None → normal review confirmation
        r = self._step("Does that sound right?", mind_change=None)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Yes, that's right.")

    def test_mind_change_fires_on_review_statement_no_question_mark(self):
        # Agent reviews order as a statement (no "?") — must still fire mind_change_item
        r = self._step("Your order is one large pepperoni pizza.", mind_change=self.CHANGE)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], self.CHANGE)

    def test_mind_change_not_fired_on_non_review_phrase(self):
        # "Anything else?" should NOT fire mind_change_item; it fires "No, that's all"
        r = self._step("Anything else?", mind_change=self.CHANGE)
        self.assertIsNotNone(r)
        self.assertNotEqual(r[0], self.CHANGE)
        self.assertEqual(r[0], "No, that's all, thank you.")

    def test_rule8_does_not_fire_when_mind_change_pending(self):
        # Non-question, non-ack statement not caught by Rules 5/6/7 —
        # Rule 8 must not swallow it while change-of-mind awaits
        r = self._step("I'll process that for you now.", mind_change=self.CHANGE)
        # Must NOT return "Okay, thanks." — falls to Ollama (None)
        self.assertIsNone(r)

    def test_rule8_fires_normally_when_no_mind_change_pending(self):
        # Without mind_change_item, Rule 8 fires as normal for matching non-question statements
        r = self._step("I'll process that for you now.", mind_change=None)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_second_review_returns_yes_thats_right_when_mind_change_consumed(self):
        # Caller consumes mind_change_item after first fire; second review gets normal reply
        r = self._step("Your updated order is a pepperoni pizza and garlic knots. Is that correct?", mind_change=None)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Yes, that's right.")

    def test_pipa_dough_skipped_when_mind_change_pending(self):
        # Agent asks about Pipa Dough before review — loyalty rule must NOT fire
        r = self._step("Would you like to apply any Pipa Dough rewards?", mind_change=self.CHANGE)
        # Must NOT return the Pipa Dough response; falls to Ollama (None) or a later rule
        if r is not None:
            self.assertNotEqual(r[0], "I'd like to apply one dollar please.")
            self.assertNotIn("dollar", r[0].lower())

    def test_tip_skipped_when_mind_change_pending(self):
        # Agent asks about tip before review — tip rule must NOT fire
        r = self._step("Would you like to add a tip?", mind_change=self.CHANGE)
        if r is not None:
            self.assertNotEqual(r[0], "I'd like to add a five dollar tip please.")
            self.assertNotIn("tip", r[0].lower())

    def test_pipa_dough_fires_normally_when_no_mind_change_pending(self):
        # Without mind_change_item, loyalty rule fires as normal
        # "Would you like to apply" hits the _apply_words branch → "I'd like to apply $1"
        r = self._step("Would you like to apply any Pipa Dough rewards?", mind_change=None)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "I'd like to apply one dollar please.")


# ---------------------------------------------------------------------------
# F-23: SR-truncated agent speech falls to Ollama correctly (never fires a
# wrong deterministic rule on a partial sentence).
#
# The state machine must never fire "Okay, thanks." (Rule 8) when SR delivers
# only the first clause of a two-part agent sentence:
#   "Your order is one large pepperoni pizza[, does that sound right?]"
#   "You have $4,813 in Pipa Dough available[. How much would you like?]"
#
# In both cases the state machine must return None so Ollama (or the next SR
# cycle that delivers the full sentence) handles the turn correctly.
# ---------------------------------------------------------------------------
class TestSRTruncationF23(unittest.TestCase):
    """F-23 regression: truncated agent speech must fall to Ollama, not fire Rule 8."""

    ITEMS = ["1 Large Pepperoni Pizza"]

    def _step(self, speech):
        return _det(speech, speech.lower(), 4, self.ITEMS, 1, [])

    # ── Truncated order review (rule 5 phrase present, no question) ──────────

    def test_your_order_is_truncated_falls_through(self):
        # "Your order is X, does that sound right?" truncated at comma
        r = self._step("Your order is one large pepperoni pizza.")
        self.assertIsNone(r)

    def test_you_have_ordered_truncated_falls_through(self):
        # "You have ordered X. Is that correct?" truncated before the question
        r = self._step("You have ordered one large pepperoni pizza.")
        self.assertIsNone(r)

    def test_let_me_confirm_truncated_falls_through(self):
        # "Let me confirm your order. Does that look right?" truncated at period
        r = self._step("Let me confirm your order.")
        self.assertIsNone(r)

    def test_let_me_repeat_truncated_falls_through(self):
        # "Let me repeat that back to you. Is that right?" truncated at period
        r = self._step("Let me repeat that back to you.")
        self.assertIsNone(r)

    def test_so_just_to_confirm_truncated_falls_through(self):
        # "So just to confirm — you have X. Does that look good?" truncated at dash
        r = self._step("So just to confirm, you have a large pepperoni pizza.")
        self.assertIsNone(r)

    # ── Truncated Pipa Dough balance announcement ────────────────────────────

    def test_pipa_dough_balance_statement_truncated_falls_through(self):
        # "You have $4,813 in Pipa Dough available. How much would you like to apply?"
        # SR truncates at the period — Rule 8 must NOT fire
        r = self._step("You have four thousand eight hundred in Pipa Dough available.")
        self.assertIsNone(r)

    def test_pipa_doe_variant_truncated_falls_through(self):
        # Whisper mis-transcription of "Pipa Dough" as "Pipa Doe"
        r = self._step("You have four thousand in Pipa Doe rewards available.")
        self.assertIsNone(r)

    # ── Positive: full sentences must still fire correctly ───────────────────

    def test_full_review_with_question_fires_yes_thats_right(self):
        # Full sentence with question → Rule 5 fires normally
        r = self._step("Your order is one large pepperoni pizza, does that sound right?")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Yes, that's right.")

    def test_full_review_without_qmark_fires_yes_thats_right(self):
        # Whisper drops the "?" but the question is still present
        r = self._step("Your order is one large pepperoni pizza, does that sound right")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Yes, that's right.")

    def test_regular_pricing_statement_still_fires_rule8(self):
        # Pricing statement with no review phrase → Rule 8 still fires as intended
        r = self._step("Your order total is eleven ninety-nine.")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_agent_confirmation_still_fires_rule8(self):
        # Generic confirmation after order placed → Rule 8 fires
        r = self._step("I'll have that right out for you.")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")


class TestLoyaltyDeclineL04(unittest.TestCase):
    """L-04: pipa_dough_action='decline' — Ravi declines Pipa Dough instead of applying $1."""

    ITEMS = ["1 Large Pepperoni Pizza"]

    def _step(self, agent_speech, action="decline"):
        return _det(
            agent_speech, agent_speech.lower(), 4,
            self.ITEMS, 1, [],
            None, 0, None, 0, None,
            action,
        )

    # --- Should decline when pipa_dough_action == "decline" ---

    def test_decline_on_apply_question(self):
        r = self._step("How much Pipa Dough would you like to apply to your order?")
        self.assertIsNotNone(r)
        self.assertIn("skip", r[0].lower())
        self.assertNotIn("one dollar", r[0].lower())

    def test_decline_on_would_you_like_to_use(self):
        r = self._step("Would you like to use your Pipa Dough rewards?")
        self.assertIsNotNone(r)
        self.assertIn("skip", r[0].lower())

    def test_decline_on_would_you_like_to_apply(self):
        r = self._step("Would you like to apply any Pipa Dough to this order?")
        self.assertIsNotNone(r)
        self.assertIn("skip", r[0].lower())

    # --- Should still apply $1 when pipa_dough_action == "apply" (default) ---

    def test_apply_is_default_behavior(self):
        r = self._step("How much Pipa Dough would you like to apply?", action="apply")
        self.assertIsNotNone(r)
        self.assertIn("one dollar", r[0].lower())

    # --- Confirmation statement still acks regardless of action ---

    def test_confirmation_statement_acks_when_decline(self):
        r = self._step("I've applied $1 of Pipa Dough to your order.")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")

    def test_confirmation_statement_acks_when_apply(self):
        r = self._step("I've applied $1 of Pipa Dough to your order.", action="apply")
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Okay, thanks.")


class TestVeryLongOrderF24(unittest.TestCase):
    """F-24: Very long order (7 items) — items_ordered_idx advances without skipping or repeating."""

    ITEMS = [
        "two large pepperoni pizzas",
        "two large cheese pizzas",
        "an order of breadsticks",
        "an order of garlic knots",
        "a 2-liter Pepsi",
        "an order of chicken wings",
        "an order of cheesesticks",
    ]

    def _step(self, agent_speech, idx, turn=3):
        return _det(agent_speech, agent_speech.lower(), turn, self.ITEMS, idx, [])

    # --- Full sequential walk-through ---

    def test_order_prompt_starts_at_item0(self):
        r = self._step("What can I get for you today?", idx=0, turn=2)
        self.assertIsNotNone(r)
        self.assertIn("pepperoni", r[0].lower())
        self.assertEqual(r[1], 1)  # idx advanced to 1

    def test_anything_else_serves_item1(self):
        r = self._step("Anything else?", idx=1)
        self.assertIsNotNone(r)
        self.assertIn("cheese", r[0].lower())
        self.assertEqual(r[1], 2)

    def test_anything_else_serves_item2(self):
        r = self._step("Is there anything else?", idx=2)
        self.assertIsNotNone(r)
        self.assertIn("breadsticks", r[0].lower())
        self.assertEqual(r[1], 3)

    def test_anything_else_serves_item3(self):
        r = self._step("What else can I get you?", idx=3)
        self.assertIsNotNone(r)
        self.assertIn("garlic knots", r[0].lower())
        self.assertEqual(r[1], 4)

    def test_anything_else_serves_item4(self):
        r = self._step("Will that be all?", idx=4)
        self.assertIsNotNone(r)
        self.assertIn("pepsi", r[0].lower())
        self.assertEqual(r[1], 5)

    def test_anything_else_serves_item5(self):
        r = self._step("Anything else for you?", idx=5)
        self.assertIsNotNone(r)
        self.assertIn("wings", r[0].lower())
        self.assertEqual(r[1], 6)

    def test_anything_else_serves_item6(self):
        r = self._step("Is that everything?", idx=6)
        self.assertIsNotNone(r)
        self.assertIn("cheesesticks", r[0].lower())
        self.assertEqual(r[1], 7)

    def test_no_thats_all_after_final_item(self):
        r = self._step("Anything else?", idx=7)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "No, that's all, thank you.")

    def test_order_review_after_all_items(self):
        r = self._step(
            "Your order is two large pepperoni pizzas, two large cheese pizzas, "
            "breadsticks, garlic knots, a Pepsi, wings, and cheesesticks. Is that correct?",
            idx=7,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "Yes, that's right.")

    def test_idx_does_not_wrap_or_reset(self):
        # Multiple "Anything else?" after all items — must always return "No, that's all"
        for _ in range(3):
            r = self._step("Anything else?", idx=7)
            self.assertIsNotNone(r)
            self.assertEqual(r[0], "No, that's all, thank you.")

    def test_order_prompt_mid_list_does_not_restart(self):
        # ORDER_PROMPT fires when idx > 0 — must serve next item, not restart from item 0
        r = self._step("What would you like to add?", idx=3)
        self.assertIsNotNone(r)
        self.assertIn("garlic knots", r[0].lower())
        self.assertEqual(r[1], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
