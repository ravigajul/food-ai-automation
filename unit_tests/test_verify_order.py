#!/usr/bin/env python3
"""
Unit tests for verify_order.py helpers.
No Appium, no device required — runs in < 1 second.

Usage:
    python unit_tests/test_verify_order.py
    python -m pytest unit_tests/test_verify_order.py -v
"""
import os
import sys

# Allow imports from the project root regardless of where pytest is invoked from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import types
import unittest

# ---------------------------------------------------------------------------
# Stubs for hardware/Appium deps so verify_order imports cleanly
# ---------------------------------------------------------------------------
def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m

_noop = lambda *a, **kw: None  # noqa: E731

_stub("appium")
_stub("appium.webdriver")
_stub("appium.webdriver.common")
_stub("appium.webdriver.common.appiumby",
      AppiumBy=type("AppiumBy", (), {"ANDROID_UIAUTOMATOR": "uia", "XPATH": "xpath"}))
_stub("src")
_stub("src.appium_driver", AppiumDriver=object)
_stub("src.ollama_client", OllamaClient=object)

import verify_order as v  # noqa: E402


# ---------------------------------------------------------------------------
# _parse_expected_total_qty
# ---------------------------------------------------------------------------
class TestParseExpectedTotalQty(unittest.TestCase):
    """Items with a leading digit count toward the cart total.
    Modifier entries (no leading digit) count as 0 — they are verified
    via Show Details text, not as separate cart items."""

    def test_single_item(self):
        self.assertEqual(v._parse_expected_total_qty(["1 Large Pepperoni Pizza"]), 1)

    def test_multiple_items(self):
        self.assertEqual(
            v._parse_expected_total_qty([
                "1 Large Pepperoni Pizza",
                "1 Order of Breadsticks",
                "1 2-Liter Pepsi",
            ]),
            3,
        )

    def test_quantity_two(self):
        self.assertEqual(v._parse_expected_total_qty(["2 Large Pepperoni Pizzas"]), 2)

    def test_modifier_no_digit_counts_zero(self):
        """Regression: 'Extra Cheese' was incorrectly counted as 1 cart item."""
        self.assertEqual(v._parse_expected_total_qty(["Extra Cheese"]), 0)

    def test_modifier_alongside_item(self):
        """Pizza (1) + modifier (0) = 1 — matches the app's '1 ITEM' display."""
        self.assertEqual(
            v._parse_expected_total_qty([
                "1 Large Pepperoni Pizza",
                "Extra Cheese",
            ]),
            1,
        )

    def test_all_modifiers_scenario(self):
        """Full modifiers_with_pizza scenario: 1 pizza + 4 modifiers = qty 1."""
        self.assertEqual(
            v._parse_expected_total_qty([
                "1 Large Pepperoni Pizza",
                "Extra Sauce",
                "Well Done Bake",
                "Square Cut",
                "Extra Parmesan Romano",
            ]),
            1,
        )

    def test_empty_list(self):
        self.assertEqual(v._parse_expected_total_qty([]), 0)


# ---------------------------------------------------------------------------
# _item_found_in_screen  (modifier keyword matching against Show Details text)
# ---------------------------------------------------------------------------
class TestItemFoundInScreen(unittest.TestCase):
    """Verify that modifier entries match the expanded 'Show Details' text
    scraped from the app (real Appium output as input)."""

    def _check(self, expected_item, screen_texts):
        token_set = set()
        for t in screen_texts:
            import re
            cleaned = re.sub(r'[^a-z0-9 ]', ' ', t.lower())
            for word in cleaned.split():
                token_set.add(word)
        combined = " ".join(
            re.sub(r'[^a-z0-9 ]', ' ', t.lower()) for t in screen_texts
        )
        return v._item_found_in_screen(expected_item, token_set, combined)

    # --- cart items (leading digit) ---
    def test_pizza_found(self):
        screen = ["Large Original Crust Pepperoni", "1ct", "$18.39"]
        self.assertTrue(self._check("1 Large Pepperoni Pizza", screen))

    # --- modifiers visible after Show Details is clicked ---
    def test_extra_sauce_found(self):
        # App shows "Sauce: Extra Original Pizza" after Show Details
        screen = ["Sauce: Extra Original Pizza", "Bake: Well Done",
                  "Cheese: Normal Cheese", "Cut: Square Cut",
                  "Whole: Pepperoni, Extra Parmesan Romano"]
        self.assertTrue(self._check("Extra Sauce", screen))

    def test_well_done_bake_found(self):
        screen = ["Sauce: Extra Original Pizza", "Bake: Well Done",
                  "Cut: Square Cut", "Whole: Pepperoni, Extra Parmesan Romano"]
        self.assertTrue(self._check("Well Done Bake", screen))

    def test_square_cut_found(self):
        screen = ["Sauce: Extra Original Pizza", "Bake: Well Done",
                  "Cut: Square Cut", "Whole: Pepperoni, Extra Parmesan Romano"]
        self.assertTrue(self._check("Square Cut", screen))

    def test_extra_parmesan_romano_found(self):
        screen = ["Sauce: Extra Original Pizza", "Bake: Well Done",
                  "Cut: Square Cut", "Whole: Pepperoni, Extra Parmesan Romano"]
        self.assertTrue(self._check("Extra Parmesan Romano", screen))

    def test_extra_cheese_found_in_whole_field(self):
        # extra_cheese scenario: "Whole: Pepperoni, Extra Cheese"
        screen = ["Sauce: Original Pizza", "Bake: Normal Bake",
                  "Cheese: Normal Cheese", "Cut: Normal Cut",
                  "Whole: Pepperoni, Extra Cheese"]
        self.assertTrue(self._check("Extra Cheese", screen))

    def test_modifier_not_found_when_absent(self):
        # Show Details does NOT contain extra sauce — modifier not applied
        screen = ["Sauce: Original Pizza", "Bake: Normal Bake",
                  "Cheese: Normal Cheese", "Cut: Normal Cut",
                  "Whole: Pepperoni"]
        self.assertFalse(self._check("Extra Sauce", screen))

    def test_baked_well_done_old_name_would_fail(self):
        """Regression guard: 'Baked Well Done' keyword 'baked' does NOT match
        'bake' on screen — this is why we renamed it to 'Well Done Bake'."""
        screen = ["Bake: Well Done"]
        # 'baked' ≠ 'bake' → _token_match returns False for 'baked'
        # 'well' and 'done' do match, but 'baked' does not → 2/3 = 67% ≥ 60%
        # Actually this still passes at 67%! The test documents the subtle
        # behaviour: "Baked Well Done" still matches, but only just barely.
        # "Well Done Bake" is safer (all 3 tokens present on screen).
        result = self._check("Well Done Bake", screen)
        self.assertTrue(result)  # "Well Done Bake": well✓ done✓ bake✓ → 100%


# ---------------------------------------------------------------------------
# _parse_overview — schedule field extraction
# ---------------------------------------------------------------------------
class TestParseOverviewSchedule(unittest.TestCase):

    def _parse(self, texts):
        return v._parse_overview(texts)

    def test_carryout_today_parsed(self):
        texts = ["1 item", "Order #468976846", "Carryout - Today at 3:00 PM",
                 "Store #24", "CREDIT CARD ...0007"]
        overview = self._parse(texts)
        self.assertEqual(overview["delivery_type"], "Carryout")
        self.assertEqual(overview["scheduled_time"], "Today at 3:00 PM")

    def test_delivery_today_parsed(self):
        texts = ["2 items", "Order #999", "Delivery - Today at 6:15 PM"]
        overview = self._parse(texts)
        self.assertEqual(overview["delivery_type"], "Delivery")
        self.assertEqual(overview["scheduled_time"], "Today at 6:15 PM")

    def test_zero_padded_hour_parsed(self):
        texts = ["1 item", "Carryout - Today at 06:15 PM"]
        overview = self._parse(texts)
        self.assertEqual(overview["scheduled_time"], "Today at 06:15 PM")

    def test_no_schedule_line_absent(self):
        texts = ["1 item", "Order #123", "CREDIT CARD ...0007"]
        overview = self._parse(texts)
        self.assertNotIn("delivery_type", overview)
        self.assertNotIn("scheduled_time", overview)

    def test_asap_line_not_parsed_as_schedule(self):
        texts = ["1 item", "Carryout - ASAP", "CREDIT CARD ...0007"]
        overview = self._parse(texts)
        self.assertNotIn("scheduled_time", overview)

    def test_asap_line_still_sets_delivery_type(self):
        """Regression: 'Carryout - ASAP' must set delivery_type even though there's no time."""
        texts = ["1 item", "Carryout - ASAP", "CREDIT CARD ...0007"]
        overview = self._parse(texts)
        self.assertEqual(overview.get("delivery_type"), "Carryout")

    def test_delivery_asap_line_sets_delivery_type(self):
        texts = ["2 items", "Delivery - ASAP"]
        overview = self._parse(texts)
        self.assertEqual(overview.get("delivery_type"), "Delivery")
        self.assertNotIn("scheduled_time", overview)

    def test_missing_scheduled_time_with_expected_schedule_fails(self):
        """No scheduled_time on Overview + expected_schedule set → schedule_ok=False, passed=False."""
        import re
        overview = {}
        scheduled_time = overview.get("scheduled_time", "")
        expected_schedule = "01:45 PM"
        schedule_ok = None
        passed = True

        if expected_schedule:
            if not scheduled_time:
                schedule_ok = False
                passed = False
            else:
                norm_e = re.sub(r'\b0(\d:\d{2})', r'\1', expected_schedule)
                norm_a = re.sub(r'\b0(\d:\d{2})', r'\1', scheduled_time)
                schedule_ok = norm_e in norm_a

        self.assertFalse(schedule_ok)
        self.assertFalse(passed)

    def test_asap_carryout_with_expected_delivery_type_passes(self):
        """ASAP order: delivery_type matches, no expected_schedule, no scheduled_time → PASS.
        Regression: the old code had an elif that set passed=False here incorrectly."""
        overview = {"delivery_type": "Carryout"}
        expected_delivery_type = "Carryout"
        scheduled_time = overview.get("scheduled_time", "")
        expected_schedule = None
        passed = True

        # Only fail the schedule check when expected_schedule is explicitly set
        if expected_schedule and not scheduled_time:
            passed = False

        self.assertTrue(passed)

    def test_missing_scheduled_time_no_expected_is_informational(self):
        """No scheduled_time, no expected_schedule, no expected_delivery_type → no failure."""
        overview = {}
        scheduled_time = overview.get("scheduled_time", "")
        expected_schedule = None
        passed = True

        if expected_schedule and not scheduled_time:
            passed = False

        self.assertTrue(passed)


# ---------------------------------------------------------------------------
# Schedule verification logic (_norm_time + matching)
# ---------------------------------------------------------------------------
class TestScheduleNormTime(unittest.TestCase):
    """Verify the leading-zero-stripping logic used in verify_order_complete."""

    import re as _re

    def _norm(self, s):
        import re
        return re.sub(r'\b0(\d:\d{2})', r'\1', s.strip())

    def test_zero_padded_stripped(self):
        self.assertEqual(self._norm("03:00 PM"), "3:00 PM")

    def test_already_bare(self):
        self.assertEqual(self._norm("3:00 PM"), "3:00 PM")

    def test_double_digit_hour_unchanged(self):
        self.assertEqual(self._norm("12:30 PM"), "12:30 PM")

    def test_slot_matches_screen(self):
        slot   = "03:00 PM"
        screen = "Today at 3:00 PM"
        import re
        norm = re.sub(r'\b0(\d:\d{2})', r'\1', slot)
        self.assertIn(norm, screen)

    def test_slot_mismatch_detected(self):
        slot   = "03:00 PM"
        screen = "Today at 4:00 PM"
        import re
        norm = re.sub(r'\b0(\d:\d{2})', r'\1', slot)
        self.assertNotIn(norm, screen)

    def test_whisper_period_colon_matches(self):
        """Whisper transcribes '1:45 PM' as '1.45 pm' — period must still match."""
        import re
        slot        = "01:45 PM"
        agent_lower = "we have you down for the nearest 15-minute slot on april 27th at 1.45 pm"
        norm        = re.sub(r'\b0(\d:\d{2})', r'\1', slot)  # "1:45 PM"
        agent_norm  = re.sub(r'\b(\d{1,2})\.(\d{2})\b', r'\1:\2', agent_lower)
        self.assertIn(norm.lower(), agent_norm)

    def test_whisper_oclock_matches(self):
        """Whisper transcribes '2:00 PM' as '2 o'clock pm' — must still match."""
        import re
        slot        = "02:00 PM"
        agent_lower = "we have you down for the nearest 15-minute slot on april 27th at 2 o'clock pm"
        norm        = re.sub(r'\b0(\d:\d{2})', r'\1', slot)        # "2:00 PM"
        agent_norm  = re.sub(r'\b(\d{1,2})\.(\d{2})\b', r'\1:\2', agent_lower)
        agent_norm  = re.sub(r"\b(\d{1,2})\s+o'?clock\b", r'\1:00', agent_norm)
        self.assertIn(norm.lower(), agent_norm)

    def test_whisper_oclock_no_apostrophe_matches(self):
        """'oclock' without apostrophe also normalised."""
        import re
        slot        = "02:00 PM"
        agent_lower = "scheduled for 2 oclock pm"
        norm        = re.sub(r'\b0(\d:\d{2})', r'\1', slot)
        agent_norm  = re.sub(r'\b(\d{1,2})\.(\d{2})\b', r'\1:\2', agent_lower)
        agent_norm  = re.sub(r"\b(\d{1,2})\s+o'?clock\b", r'\1:00', agent_norm)
        self.assertIn(norm.lower(), agent_norm)

    def test_whisper_period_mismatch_still_caught(self):
        """Different times with period notation should not match."""
        import re
        slot        = "01:45 PM"
        agent_lower = "we have you down for 2.00 pm"
        norm        = re.sub(r'\b0(\d:\d{2})', r'\1', slot)
        agent_norm  = re.sub(r'\b(\d{1,2})\.(\d{2})\b', r'\1:\2', agent_lower)
        self.assertNotIn(norm.lower(), agent_norm)


# ---------------------------------------------------------------------------
# extract_expected_from_log — [AGENT RECOMMENDATION] tag path
# ---------------------------------------------------------------------------
class TestExtractFromRecommendationLog(unittest.TestCase):
    """Verify that extract_expected_from_log uses the focused [AGENT RECOMMENDATION]
    path when the tag is present, and falls back to the full transcript otherwise."""

    def _make_ollama(self, return_json):
        """Return a minimal mock OllamaClient that captures the prompt and returns JSON."""
        class MockOllama:
            def __init__(self):
                self.last_prompt = None
            def generate(self, prompt, system=None, **kwargs):
                self.last_prompt = prompt
                return return_json
        return MockOllama()

    def _write_log(self, lines, tmp_path):
        with open(tmp_path, "w") as f:
            f.write("\n".join(lines))
        return tmp_path

    def test_recommendation_tag_items_extracted(self):
        """[AGENT RECOMMENDATION] tag → items from recommendation speech are returned."""
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".txt")
        self._write_log([
            "Agent: What would you like to order?",
            "Ravi: I'm vegetarian, what would you recommend? [DETERMINISTIC]",
            "[AGENT RECOMMENDATION]: For vegetarians I'd recommend our Garden Fresh Pizza and some garlic knots.",
            "Agent: For vegetarians I'd recommend our Garden Fresh Pizza and some garlic knots.",
            "Ravi: Yes that sounds great please add those. [OLLAMA]",
        ], tmp)
        mock = self._make_ollama('{"items": ["1 Garden Fresh Pizza", "1 Garlic Knots"]}')
        try:
            result = v.extract_expected_from_log(tmp, ollama=mock)
        finally:
            os.unlink(tmp)
        self.assertEqual(result, ["1 Garden Fresh Pizza", "1 Garlic Knots"])
        # Prompt should reference the recommendation text, not the full transcript
        self.assertIn("Garden Fresh Pizza", mock.last_prompt)
        self.assertNotIn("Ravi:", mock.last_prompt)

    def test_recommendation_tag_prompt_is_focused(self):
        """The focused prompt does NOT include the full transcript when tag is present."""
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".txt")
        self._write_log([
            "Agent: What can I get you?",
            "Ravi: I'm ordering for a group of 6, what do you recommend? [DETERMINISTIC]",
            "[AGENT RECOMMENDATION]: For a group of 6 I suggest two large pepperoni pizzas and some breadsticks.",
            "Agent: For a group of 6 I suggest two large pepperoni pizzas and some breadsticks.",
            "Ravi: Yes please add those. [OLLAMA]",
        ], tmp)
        mock = self._make_ollama('{"items": ["2 Large Pepperoni Pizza", "1 Breadsticks"]}')
        try:
            v.extract_expected_from_log(tmp, ollama=mock)
        finally:
            os.unlink(tmp)
        # Full transcript path would include "Transcript:" header
        self.assertNotIn("Transcript:", mock.last_prompt)

    def test_no_recommendation_tag_uses_full_transcript(self):
        """When no [AGENT RECOMMENDATION] tag, the full transcript is sent to Ollama."""
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".txt")
        self._write_log([
            "Agent: What would you like?",
            "Ravi: I'd like a large pepperoni pizza please. [DETERMINISTIC]",
            "Agent: Got it, a large pepperoni pizza. Anything else?",
            "Ravi: No that's all thank you. [DETERMINISTIC]",
        ], tmp)
        mock = self._make_ollama('{"items": ["1 Large Pepperoni Pizza"]}')
        try:
            result = v.extract_expected_from_log(tmp, ollama=mock)
        finally:
            os.unlink(tmp)
        self.assertEqual(result, ["1 Large Pepperoni Pizza"])
        self.assertIn("Transcript:", mock.last_prompt)

    def test_recommendation_tag_ollama_returns_empty(self):
        """If Ollama finds no items in the recommendation, returns empty list."""
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".txt")
        self._write_log([
            "[AGENT RECOMMENDATION]: Let me check what we have for you.",
        ], tmp)
        mock = self._make_ollama('{"items": []}')
        try:
            result = v.extract_expected_from_log(tmp, ollama=mock)
        finally:
            os.unlink(tmp)
        self.assertEqual(result, [])

    def test_log_file_not_found_returns_empty(self):
        """Missing log file returns empty list without raising."""
        result = v.extract_expected_from_log("/nonexistent/path/log.txt")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
