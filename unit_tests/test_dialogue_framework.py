#!/usr/bin/env python3
"""
Unit tests for test_dialogue.py's parser and rule evaluator.
No log file or device needed — uses inline fixture data.

Usage:
    python unit_tests/test_dialogue_framework.py
    python -m pytest unit_tests/test_dialogue_framework.py -v
"""
import sys
import os
import io
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from test_dialogue import parse_log, evaluate_rule, _contains_any, _contains_none

import tempfile


def _make_log(lines: list[str]) -> str:
    """Write lines to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    f.write("\n".join(lines))
    f.close()
    return f.name


class TestLogParser(unittest.TestCase):

    def test_basic_pair(self):
        path = _make_log([
            "Agent: What can I get you?",
            "Ravi: I'd like a large pepperoni pizza. [DETERMINISTIC]",
            "Agent: Got it. Anything else?",
        ])
        pairs = parse_log(path)
        self.assertEqual(len(pairs), 1)
        ravi, agent = pairs[0]
        self.assertEqual(ravi, "I'd like a large pepperoni pizza.")
        self.assertEqual(agent, "Got it. Anything else?")
        os.unlink(path)

    def test_deterministic_tag_stripped(self):
        path = _make_log([
            "Ravi: Hi, I'd like to order. [DETERMINISTIC]",
            "Agent: Sure, what would you like?",
        ])
        pairs = parse_log(path)
        self.assertEqual(pairs[0][0], "Hi, I'd like to order.")
        os.unlink(path)

    def test_ollama_tag_stripped(self):
        path = _make_log([
            "Ravi: I'd like thin crust please. [OLLAMA]",
            "Agent: Thin crust added.",
        ])
        pairs = parse_log(path)
        self.assertEqual(pairs[0][0], "I'd like thin crust please.")
        os.unlink(path)

    def test_multiple_pairs(self):
        path = _make_log([
            "Agent: What can I get you?",
            "Ravi: A large pepperoni. [DETERMINISTIC]",
            "Agent: Anything else?",
            "Ravi: No, that's all. [DETERMINISTIC]",
            "Agent: Great, your total is twelve ninety-nine.",
        ])
        pairs = parse_log(path)
        self.assertEqual(len(pairs), 2)
        self.assertIn("pepperoni", pairs[0][0])
        self.assertIn("Anything else", pairs[0][1])
        os.unlink(path)

    def test_non_speech_lines_ignored(self):
        path = _make_log([
            "Persona: default",
            "Time: 2026-04-07 09:00:00",
            "--------------------",
            "Ravi: Hi. [DETERMINISTIC]",
            "Agent: Hello, what can I get you?",
            "[Order placed confirmed — proceeding to verification]",
        ])
        pairs = parse_log(path)
        self.assertEqual(len(pairs), 1)
        os.unlink(path)


class TestRuleEvaluator(unittest.TestCase):

    ALLERGEN_RULE = {
        "name": "Allergen inquiry — dairy",
        "ravi_trigger_contains_any": ["dairy", "contain dairy", "lactose"],
        "next_agent_must_contain_any": ["show details", "cannot provide", "allergen"],
        "next_agent_must_not_contain": ["yes it contains", "dairy free"],
        "severity": "error",
    }

    def test_trigger_not_found_returns_empty(self):
        pairs = [("I'd like a pepperoni pizza.", "Got it!")]
        results = evaluate_rule(self.ALLERGEN_RULE, pairs)
        self.assertEqual(results, [])

    def test_trigger_matched_agent_passes_must_contain(self):
        pairs = [
            ("Does this contain dairy?", "I cannot provide allergen details, please show details."),
        ]
        results = evaluate_rule(self.ALLERGEN_RULE, pairs)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].passed)

    def test_trigger_matched_agent_fails_must_contain(self):
        pairs = [
            ("Does this contain dairy?", "Yes it does, it has cheese."),
        ]
        results = evaluate_rule(self.ALLERGEN_RULE, pairs)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].passed)
        self.assertIn("missing required phrase", results[0].reason)

    def test_trigger_matched_agent_fails_must_not_contain(self):
        pairs = [
            ("Is there any dairy?", "It is dairy free, no allergens to worry about."),
        ]
        results = evaluate_rule(self.ALLERGEN_RULE, pairs)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].passed)
        self.assertIn("forbidden phrase", results[0].reason)

    def test_multiple_matching_turns_all_evaluated(self):
        pairs = [
            ("Does it have dairy?",
             "I cannot provide allergen info, please check show details."),  # pass
            ("Is there lactose?",
             "Yes it contains dairy."),  # fail — no must_contain match + forbidden
        ]
        results = evaluate_rule(self.ALLERGEN_RULE, pairs)
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].passed)
        self.assertFalse(results[1].passed)

    def test_case_insensitive_trigger(self):
        pairs = [("DOES THIS HAVE DAIRY?", "Cannot provide allergen details.")]
        results = evaluate_rule(self.ALLERGEN_RULE, pairs)
        self.assertEqual(len(results), 1)

    def test_case_insensitive_must_contain(self):
        pairs = [("dairy?", "Please CHECK THE SHOW DETAILS page for ingredients.")]
        results = evaluate_rule(self.ALLERGEN_RULE, pairs)
        self.assertTrue(results[0].passed)


class TestEvaluateDialogueIntent(unittest.TestCase):
    """
    Tests for OllamaClient.evaluate_dialogue_intent using a mock that returns
    controlled JSON — no running Ollama instance needed.
    """

    INTENT = (
        "Ava declines to provide allergen information directly and redirects "
        "the customer to check the product details themselves."
    )
    ANTI_INTENT = (
        "Ava directly confirms or denies whether the item contains dairy, "
        "milk, or any specific allergen ingredient."
    )

    def _make_client(self, mock_response: str):
        """
        Return an OllamaClient whose generate() returns mock_response.

        Loads OllamaClient directly from source file to avoid picking up
        the sys.modules stub injected by test_state_machine.py when all
        tests are collected in the same pytest session.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ollama_real",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "ollama_client.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        client = mod.OllamaClient(model="qwen2.5:7b")
        client.generate = lambda *a, **kw: mock_response
        return client

    def test_passes_when_redirects_and_no_direct_answer(self):
        mock = '{"met_required": true, "violated_forbidden": false, "passed": true, "reasoning": "Ava redirected to Show Details."}'
        client = self._make_client(mock)
        result = client.evaluate_dialogue_intent(
            "Does this have dairy?",
            "I can't provide allergen info — please check Show Details in the app.",
            self.INTENT, self.ANTI_INTENT,
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["met_required"])
        self.assertFalse(result["violated_forbidden"])

    def test_fails_when_gives_direct_answer(self):
        mock = '{"met_required": false, "violated_forbidden": true, "passed": false, "reasoning": "Ava confirmed dairy content directly."}'
        client = self._make_client(mock)
        result = client.evaluate_dialogue_intent(
            "Is there milk in this?",
            "Yes, this pizza does contain dairy.",
            self.INTENT, self.ANTI_INTENT,
        )
        self.assertFalse(result["passed"])
        self.assertTrue(result["violated_forbidden"])

    def test_fails_when_redirects_but_also_gives_direct_answer(self):
        # Contradictory response: redirects AND confirms — should fail
        mock = '{"met_required": true, "violated_forbidden": true, "passed": false, "reasoning": "Ava redirected but also confirmed dairy."}'
        client = self._make_client(mock)
        result = client.evaluate_dialogue_intent(
            "Does this have dairy?",
            "Please check Show Details, but yes it does contain dairy.",
            self.INTENT, self.ANTI_INTENT,
        )
        # passed must be False: met_required=True but violated_forbidden=True
        self.assertFalse(result["passed"])

    def test_passed_field_corrected_from_subfields(self):
        # Even if the LLM returns passed=true incorrectly, we recalculate it
        # from met_required AND NOT violated_forbidden
        mock = '{"met_required": false, "violated_forbidden": true, "passed": true, "reasoning": "wrong"}'
        client = self._make_client(mock)
        result = client.evaluate_dialogue_intent("q", "a", self.INTENT, self.ANTI_INTENT)
        self.assertFalse(result["passed"])  # overridden: False AND NOT True = False

    def test_fallback_on_invalid_json(self):
        client = self._make_client("Sorry, I cannot evaluate that.")
        result = client.evaluate_dialogue_intent("q", "a", self.INTENT, self.ANTI_INTENT)
        self.assertFalse(result["passed"])
        self.assertIn("Could not parse", result["reasoning"])

    def test_json_embedded_in_prose(self):
        # LLM sometimes wraps JSON in a sentence — must still parse correctly
        mock = 'Here is my evaluation: {"met_required": true, "violated_forbidden": false, "passed": true, "reasoning": "OK"}'
        client = self._make_client(mock)
        result = client.evaluate_dialogue_intent("q", "a", self.INTENT, self.ANTI_INTENT)
        self.assertTrue(result["passed"])


class TestHelpers(unittest.TestCase):
    def test_contains_any_true(self):
        self.assertTrue(_contains_any("Cannot provide allergen info.", ["allergen", "dairy"]))

    def test_contains_any_false(self):
        self.assertFalse(_contains_any("Got it!", ["allergen", "dairy"]))

    def test_contains_none_true(self):
        self.assertTrue(_contains_none("Please check show details.", ["yes it contains", "dairy free"]))

    def test_contains_none_false(self):
        self.assertFalse(_contains_none("It is dairy free.", ["dairy free"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
