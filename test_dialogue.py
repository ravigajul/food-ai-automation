#!/usr/bin/env python3
"""
Dialogue Behavior Tests — validate what Ava (the voice agent) says in response
to specific things Ravi says, using a recorded conversation log as input.

This tests the *agent's* behavior (do's and don'ts), which cannot be covered
by test_state_machine.py (which only tests Ravi's deterministic responses).

Contract rules live in: dialogue_tests/agent_behavior.yaml
Add new do's/don'ts there — no code changes needed.

Usage:
    # Standalone validator against a log file:
    python test_dialogue.py --log logs/test_run_<timestamp>.txt

    # With pytest (pass log via --log flag or DIALOGUE_LOG env var):
    python -m pytest test_dialogue.py --log logs/test_run_<timestamp>.txt -v
    DIALOGUE_LOG=logs/test_run_<timestamp>.txt python -m pytest test_dialogue.py -v

Exit codes:
    0 — all triggered rules passed (untriggered rules are skipped, not failures)
    1 — one or more error-severity rules failed
"""
import argparse
import os
import re
import sys
import unittest
import yaml


# ---------------------------------------------------------------------------
# Log parser
# ---------------------------------------------------------------------------
def parse_log(log_path: str) -> list[tuple[str, str]]:
    """
    Parse a conversation log into a list of (ravi_speech, next_agent_speech) pairs.

    Each pair represents: Ravi said something → Ava replied with something.
    The [DETERMINISTIC] / [OLLAMA] tags on Ravi's lines are stripped.
    Blank lines and non-speech lines are ignored.

    Returns:
        List of (ravi, agent) tuples in conversation order.
    """
    pairs = []
    lines = []
    with open(log_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            lines.append(line)

    # Walk lines collecting Agent / Ravi alternations
    pending_ravi = None
    for line in lines:
        if line.startswith("Agent:"):
            agent_text = line[len("Agent:"):].strip().strip('"')
            if pending_ravi is not None:
                # Complete the pair: ravi said → agent replied
                pairs.append((pending_ravi, agent_text))
                pending_ravi = None
        elif line.startswith("Ravi:"):
            ravi_text = line[len("Ravi:"):].strip().strip('"')
            # Strip [DETERMINISTIC] / [OLLAMA] tags
            ravi_text = re.sub(r'\s*\[(DETERMINISTIC|OLLAMA)\]\s*$', '', ravi_text).strip()
            pending_ravi = ravi_text

    return pairs


# ---------------------------------------------------------------------------
# Contract loader
# ---------------------------------------------------------------------------
def load_contract(yaml_path: str) -> list[dict]:
    """Load the agent behavior contract from YAML."""
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("tests", [])


# ---------------------------------------------------------------------------
# Assertion engine
# ---------------------------------------------------------------------------
def _contains_any(text: str, phrases: list[str]) -> bool:
    """Case-insensitive check: does text contain at least one of phrases?"""
    lower = text.lower()
    return any(p.lower() in lower for p in phrases)


def _contains_none(text: str, phrases: list[str]) -> bool:
    """Case-insensitive check: does text contain none of phrases?"""
    lower = text.lower()
    return not any(p.lower() in lower for p in phrases)


class DialogueRuleResult:
    """Outcome of evaluating one rule against one matching turn."""
    def __init__(self, rule_name, ravi, agent, passed, reason):
        self.rule_name = rule_name
        self.ravi = ravi
        self.agent = agent
        self.passed = passed
        self.reason = reason


def evaluate_rule(rule: dict, pairs: list[tuple[str, str]]) -> list[DialogueRuleResult]:
    """
    Find all conversation turns where Ravi's speech matches the rule trigger,
    then validate Ava's response against must_contain_any / must_not_contain.

    Returns one result per matching turn (empty list = rule was never triggered).
    """
    triggers = rule.get("ravi_trigger_contains_any", [])
    must_contain = rule.get("next_agent_must_contain_any", [])
    must_not_contain = rule.get("next_agent_must_not_contain", [])
    name = rule["name"]

    results = []
    for ravi, agent in pairs:
        if not _contains_any(ravi, triggers):
            continue  # this turn doesn't trigger the rule

        passed = True
        reason_parts = []

        if must_contain and not _contains_any(agent, must_contain):
            passed = False
            reason_parts.append(
                f"agent response missing required phrase(s): {must_contain}"
            )
        if must_not_contain and not _contains_none(agent, must_not_contain):
            matched = [p for p in must_not_contain if p.lower() in agent.lower()]
            passed = False
            reason_parts.append(
                f"agent response contained forbidden phrase(s): {matched}"
            )

        reason = "; ".join(reason_parts) if reason_parts else "OK"
        results.append(DialogueRuleResult(name, ravi, agent, passed, reason))

    return results


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------
def run_contract(log_path: str, contract_path: str) -> bool:
    """
    Run all rules against the log and print a report.
    Returns True if all triggered error-severity rules passed.
    """
    print(f"\n{'=' * 60}")
    print("DIALOGUE BEHAVIOR VALIDATION")
    print(f"{'=' * 60}")
    print(f"Log    : {log_path}")
    print(f"Contract: {contract_path}")

    pairs = parse_log(log_path)
    print(f"Parsed : {len(pairs)} ravi→agent turn pair(s)\n")

    rules = load_contract(contract_path)
    overall_passed = True

    for rule in rules:
        name = rule["name"]
        severity = rule.get("severity", "error")
        results = evaluate_rule(rule, pairs)

        if not results:
            print(f"  ⏭   SKIPPED  [{severity}] {name}")
            print(f"       (trigger not found in log — run a session where Ravi asks this)\n")
            continue

        for r in results:
            if r.passed:
                print(f"  ✅  PASSED   [{severity}] {name}")
                print(f"       Ravi : {r.ravi}")
                print(f"       Ava  : {r.agent}\n")
            else:
                icon = "❌" if severity == "error" else "⚠️ "
                print(f"  {icon}  FAILED   [{severity}] {name}")
                print(f"       Ravi  : {r.ravi}")
                print(f"       Ava   : {r.agent}")
                print(f"       Reason: {r.reason}\n")
                if severity == "error":
                    overall_passed = False

    status = "PASSED" if overall_passed else "FAILED"
    print(f"{'=' * 60}")
    print(f"Result: {status}")
    print(f"{'=' * 60}\n")
    return overall_passed


# ---------------------------------------------------------------------------
# pytest integration
# ---------------------------------------------------------------------------
def pytest_addoption(parser):
    parser.addoption(
        "--log", action="store", default=None,
        help="Path to conversation log file for dialogue tests"
    )


_CONTRACT = os.path.join(os.path.dirname(__file__), "dialogue_tests", "agent_behavior.yaml")


def _resolve_log() -> str | None:
    """Find a log path from --log CLI arg, DIALOGUE_LOG env var, or latest log."""
    # 1. pytest CLI arg
    for i, arg in enumerate(sys.argv):
        if arg == "--log" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith("--log="):
            return arg.split("=", 1)[1]
    # 2. Environment variable
    if os.environ.get("DIALOGUE_LOG"):
        return os.environ["DIALOGUE_LOG"]
    # 3. Most recent log file (auto-discover)
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    if os.path.isdir(log_dir):
        logs = sorted(
            (f for f in os.listdir(log_dir) if f.startswith("test_run_") and f.endswith(".txt")),
            reverse=True,
        )
        if logs:
            return os.path.join(log_dir, logs[0])
    return None


class TestAgentBehavior(unittest.TestCase):
    """
    One pytest test per rule in agent_behavior.yaml.
    Skipped when the rule's trigger phrase never appears in the log.
    """

    @classmethod
    def setUpClass(cls):
        cls.log_path = _resolve_log()
        cls.rules = load_contract(_CONTRACT)
        if cls.log_path and os.path.isfile(cls.log_path):
            cls.pairs = parse_log(cls.log_path)
        else:
            cls.pairs = []

    def _run_rule(self, rule):
        if not self.log_path or not os.path.isfile(self.log_path):
            self.skipTest("No log file available — pass --log or set DIALOGUE_LOG")

        results = evaluate_rule(rule, self.pairs)
        if not results:
            self.skipTest(
                f"Trigger not found in log — run a session where Ravi says "
                f"something containing: {rule.get('ravi_trigger_contains_any', [])}"
            )

        severity = rule.get("severity", "error")
        failures = [r for r in results if not r.passed]
        if failures and severity == "error":
            msgs = [
                f"\n  Ravi : {f.ravi}\n  Ava  : {f.agent}\n  Reason: {f.reason}"
                for f in failures
            ]
            self.fail(f"Agent behavior violation in '{rule['name']}':" + "".join(msgs))


def _make_test(rule):
    """Dynamically create a test method for a single rule."""
    def test_method(self):
        self._run_rule(rule)
    # Sanitise rule name → valid Python identifier for pytest display
    safe = re.sub(r'[^a-z0-9]+', '_', rule["name"].lower()).strip('_')
    test_method.__name__ = f"test_{safe}"
    test_method.__doc__ = rule.get("description", rule["name"]).strip()
    return test_method


# Attach one test method per rule to TestAgentBehavior at import time
_rules_for_tests = load_contract(_CONTRACT)
for _rule in _rules_for_tests:
    _method = _make_test(_rule)
    setattr(TestAgentBehavior, _method.__name__, _method)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate agent dialogue behavior against a log.")
    parser.add_argument("--log", required=False, help="Path to conversation log file")
    parser.add_argument("--contract", default=_CONTRACT,
                        help="Path to agent_behavior.yaml (default: dialogue_tests/agent_behavior.yaml)")
    args = parser.parse_args()

    log = args.log or _resolve_log()
    if not log or not os.path.isfile(log):
        print("❌ No log file found. Pass --log <path> or set DIALOGUE_LOG=<path>.")
        sys.exit(1)

    passed = run_contract(log, args.contract)
    sys.exit(0 if passed else 1)
