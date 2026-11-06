#!/usr/bin/env python3
"""
Enforce that every take_screenshot("name") call in the codebase has a
matching entry in SCREENSHOT_CAPTIONS (src/report_generator.py).

Without this check, new screenshots are silently dropped from HTML reports.
The test uses static analysis (regex on source files) — no device, no Appium.

Run:
    python -m pytest unit_tests/test_screenshot_registry.py -v
"""
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.report_generator import SCREENSHOT_CAPTIONS

# ── Config ────────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files to scan for take_screenshot calls
SOURCE_FILES = [
    "launch_and_invoke_voice.py",
    "run_suite.py",
    "verify_order.py",
    "end_to_end_voice_test.py",
]

# F-string screenshot names that can't be detected statically.
# Each entry is the stem pattern and the stems it actually produces.
# Update this table whenever a new f-string take_screenshot is added.
FSTRING_STEMS = {
    # run_suite.py: driver.take_screenshot(f"nav_retry_{_retry + 1}")
    "nav_retry_{n}": ["nav_retry_1", "nav_retry_2", "nav_retry_3"],
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect_literal_stems() -> list[tuple[str, str]]:
    """Return [(stem, source_file), ...] for every literal take_screenshot("…") call."""
    pattern = re.compile(r'take_screenshot\(\s*"([^"]+)"\s*\)')
    found = []
    for rel in SOURCE_FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                for m in pattern.finditer(line):
                    found.append((m.group(1), rel))
    return found


def _caption_stems() -> set[str]:
    return {stem for stem, _caption in SCREENSHOT_CAPTIONS}

# ── Tests ─────────────────────────────────────────────────────────────────────

def test_all_literal_screenshots_in_captions():
    """
    Every take_screenshot("literal_name") call must have a matching entry in
    SCREENSHOT_CAPTIONS.  Missing entries are silently dropped from the report.
    """
    captions = _caption_stems()
    literal_stems = _collect_literal_stems()

    missing = [
        (stem, src)
        for stem, src in literal_stems
        if stem not in captions
    ]

    assert not missing, (
        "These take_screenshot() names are missing from SCREENSHOT_CAPTIONS:\n"
        + "\n".join(f"  {src}: '{stem}'" for stem, src in missing)
        + "\n\nAdd them to SCREENSHOT_CAPTIONS in src/report_generator.py."
    )


def test_fstring_stems_in_captions():
    """
    F-string screenshot names are manually declared in FSTRING_STEMS.
    Verify each declared stem is present in SCREENSHOT_CAPTIONS.
    """
    captions = _caption_stems()
    missing = []
    for pattern, stems in FSTRING_STEMS.items():
        for stem in stems:
            if stem not in captions:
                missing.append((pattern, stem))

    assert not missing, (
        "These f-string screenshot stems are missing from SCREENSHOT_CAPTIONS:\n"
        + "\n".join(f"  pattern '{p}' → stem '{s}'" for p, s in missing)
        + "\n\nAdd them to SCREENSHOT_CAPTIONS in src/report_generator.py."
    )


def test_no_unknown_fstring_screenshots():
    """
    Detect f-string take_screenshot calls in source files and confirm each is
    declared in FSTRING_STEMS.  Fails if a new f-string screenshot is added
    without being documented.
    """
    fstring_pattern = re.compile(r'take_screenshot\(\s*f"([^"]+)"\s*\)')
    undeclared = []
    declared_patterns = set(FSTRING_STEMS.keys())

    for rel in SOURCE_FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                for m in fstring_pattern.finditer(line):
                    raw = m.group(1)
                    # Normalise: replace {…} with {n} for lookup
                    normalised = re.sub(r'\{[^}]+\}', '{n}', raw)
                    if normalised not in declared_patterns:
                        undeclared.append((rel, lineno, raw))

    assert not undeclared, (
        "Undeclared f-string take_screenshot() calls found:\n"
        + "\n".join(f"  {src}:{ln}: f\"{raw}\"" for src, ln, raw in undeclared)
        + "\n\nAdd the pattern and its generated stems to FSTRING_STEMS in "
        "unit_tests/test_screenshot_registry.py."
    )
