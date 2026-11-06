#!/usr/bin/env python3
"""
Unit tests for the AI disclaimer keyword-matching logic in
launch_and_invoke_voice._check_ai_disclaimer_text().

No Appium, no device required — runs in < 0.1 second.

Usage:
    python -m pytest unit_tests/test_ai_disclaimer.py -v
"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from launch_and_invoke_voice import _check_ai_disclaimer_text, _check_ai_disclaimer_source

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _check(texts):
    passed, _, _ = _check_ai_disclaimer_text(texts)
    return passed


# ── Passing cases — real or plausible on-screen text ──────────────────────────

def test_exact_screen_text():
    """Current production text from the VOICE ORDERING screen."""
    texts = [
        "Hi, I'm Ava AI. I'll help you create your order, and we'll apply "
        "any available discounts before you check out to make sure you're getting a great deal.",
        "*This feature uses AI and can occasionally give responses that are incorrect or misleading.",
    ]
    assert _check(texts) is True


def test_uses_ai_with_occasionally():
    assert _check(["This feature uses AI", "responses may occasionally be wrong"]) is True


def test_uses_ai_with_incorrect():
    assert _check(["This feature uses AI and can give incorrect answers."]) is True


def test_uses_ai_with_misleading():
    assert _check(["This feature uses AI and may be misleading at times."]) is True


def test_uses_ai_with_mistakes():
    assert _check(["Feature uses AI. It may make mistakes."]) is True


def test_lou_ai_with_occasionally():
    assert _check(["I'm Ava AI.", "I can occasionally be wrong."]) is True


def test_feature_uses_with_incorrect():
    assert _check(["feature uses artificial intelligence", "may give incorrect results"]) is True


def test_case_insensitive():
    assert _check(["THIS FEATURE USES AI AND CAN OCCASIONALLY GIVE INCORRECT RESPONSES."]) is True


def test_disclaimer_split_across_elements():
    """Disclaimer text may span multiple text elements on screen."""
    assert _check([
        "Hi, I'm Ava AI.",
        "This feature uses AI.",
        "Responses can occasionally be incorrect or misleading.",
    ]) is True


# ── Failing cases ──────────────────────────────────────────────────────────────

def test_empty_screen():
    assert _check([]) is False


def test_no_ai_mention():
    """Error caveat present but no AI identification."""
    assert _check(["Responses can occasionally be incorrect."]) is False


def test_no_error_caveat():
    """AI identified but no error caveat."""
    assert _check(["This feature uses AI to take your order."]) is False


def test_neither_concept():
    assert _check(["Voice ordering", "VOICE ORDERING", "Menu"]) is False


def test_ai_word_alone_not_sufficient():
    """'AI' appears in a non-identification context — should still fail without caveat."""
    assert _check(["AI pizza assistant"]) is False


def test_caveat_word_alone_not_sufficient():
    """Error caveat present but no AI identification at all."""
    assert _check(["Occasionally our app may have issues."]) is False


def test_misleading_without_ai_mention():
    assert _check(["This could be misleading."]) is False


def test_mistakes_without_ai_mention():
    assert _check(["Everyone makes mistakes."]) is False


# ── Regression: real on-screen text from order_ahead run ─────────────────────
# Root cause: the disclaimer "*This feature uses AI and can occasionally give
# responses that are incorrect or misleading." was visible on the Voice Ordering
# screen but _check_ai_disclaimer_text received only the greeting text
# ("Hi, I'm Ava AI. ...") because React Native Text components can expose text
# in page_source XML without surfacing via @text/@content-desc attribute reads.
# verify_ai_disclaimer now falls back to page_source when element scan misses it.
# These tests confirm the helper correctly passes when the full disclaimer text
# is present (as it would appear in the page_source fallback scan).

def test_real_disclaimer_text_order_ahead():
    """Exact on-screen text captured from the Voice Ordering screen."""
    assert _check([
        "*This feature uses AI and can occasionally give responses that are incorrect or misleading."
    ]) is True


def test_only_greeting_captured_fails():
    """
    Reproduces the regression: only the greeting ('Hi, I'm Ava AI...') was
    captured by the element scan — no error caveat present → should fail.
    The live fix adds a page_source fallback which is not testable here.
    """
    assert _check([
        "Hi, I'm Ava AI. I'll help you create your order, and we'll apply "
        "any available discounts before you check out to make sure you're "
        "getting a great deal. Would you like to reorder your last order?"
    ]) is False  # passes AI mention but fails error caveat — triggers fallback


# ── _check_ai_disclaimer_source (page_source XML fallback) ────────────────────

def _src_check(source: str) -> bool:
    passed, _, _ = _check_ai_disclaimer_source(source)
    return passed


# Synthetic page_source fixtures — minimal XML that mirrors how React Native
# exposes text in the hierarchy dump.  Update these from real captures saved by
# verify_ai_disclaimer() to logs/disclaimer_source_<ts>.xml when they fail.

_DISCLAIMER_IN_ATTR = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <android.view.ViewGroup>
    <android.widget.TextView text="*This feature uses AI and can occasionally give responses that are incorrect or misleading." />
    <android.widget.TextView text="Hi, I'm Ava AI." />
  </android.view.ViewGroup>
</hierarchy>"""

_DISCLAIMER_IN_CONTENT_DESC = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <android.view.View content-desc="This feature uses AI and may occasionally be misleading." />
</hierarchy>"""

_GREETING_ONLY_SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <android.widget.TextView text="Hi, I'm Ava AI. How can I help?" />
  <android.widget.TextView text="VOICE ORDERING" />
</hierarchy>"""


def test_source_disclaimer_in_text_attr():
    assert _src_check(_DISCLAIMER_IN_ATTR) is True


def test_source_disclaimer_in_content_desc():
    assert _src_check(_DISCLAIMER_IN_CONTENT_DESC) is True


def test_source_greeting_only_fails():
    assert _src_check(_GREETING_ONLY_SOURCE) is False


def test_source_empty_fails():
    assert _src_check("") is False


def test_source_case_insensitive():
    assert _src_check('<t text="THIS FEATURE USES AI AND CAN OCCASIONALLY GIVE INCORRECT RESULTS." />') is True


# ── Fixture-based tests — load real captures saved by _save_disclaimer_evidence ──
# When a disclaimer check fails in a live run, two files are saved:
#   logs/disclaimer_texts_<ts>.json
#   logs/disclaimer_source_<ts>.xml
# Copy them to unit_tests/fixtures/ (renaming to disclaimer_texts.json /
# disclaimer_source.xml) and the tests below will run automatically.

def test_fixture_texts_pass_if_present():
    """Run _check_ai_disclaimer_text against a real captured texts fixture."""
    path = os.path.join(FIXTURES_DIR, "disclaimer_texts.json")
    if not os.path.exists(path):
        return  # no fixture yet — skip silently
    with open(path, encoding="utf-8") as f:
        texts = json.load(f)
    passed, has_ai, has_caveat = _check_ai_disclaimer_text(texts)
    assert passed, (
        f"Fixture texts failed disclaimer check — has_ai={has_ai}, has_caveat={has_caveat}.\n"
        f"Texts: {texts}"
    )


def test_fixture_source_passes_if_present():
    """Run _check_ai_disclaimer_source against a real captured page_source fixture."""
    path = os.path.join(FIXTURES_DIR, "disclaimer_source.xml")
    if not os.path.exists(path):
        return  # no fixture yet — skip silently
    with open(path, encoding="utf-8") as f:
        source = f.read()
    passed, has_ai, has_caveat = _check_ai_disclaimer_source(source)
    assert passed, (
        f"Fixture source failed disclaimer check — has_ai={has_ai}, has_caveat={has_caveat}.\n"
        f"First 500 chars: {source[:500]}"
    )
