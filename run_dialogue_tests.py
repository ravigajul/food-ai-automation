#!/usr/bin/env python3
"""
Live Dialogue Behavior Tests
=============================
Launches the Acme Pizza app, navigates to Ava, speaks each question variant,
and uses an Ollama LLM judge to evaluate whether Ava's response satisfies the
behavioral intent — WITHOUT completing an order.

Each question variant gets its own fresh voice session:
    navigate_to_home → Start Voice Order → speak question → capture → judge → close

Usage:
    python run_dialogue_tests.py
    python run_dialogue_tests.py --test "Allergen"      # substring match on name
    python run_dialogue_tests.py --mic "External Microphone"
"""
import argparse
import html as html_lib
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import speech_recognition as sr
import yaml

from src.voice_ai import speak_sync
from src.ollama_client import OllamaClient
from end_to_end_voice_test import find_microphone_index, _load_ollama_model
from launch_and_invoke_voice import (
    launch_app,
    navigate_to_home,
    scroll_to_start_voice_order,
    click_start_voice_order,
    click_arrow_on_ready_screen,
    verify_voice_agent_active,
)

_CONTRACT = os.path.join(os.path.dirname(__file__), "dialogue_tests", "agent_behavior.yaml")


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------
def _listen_once(recognizer, mic_index: int, label: str,
                 pause_threshold: float = 1.8,
                 calibrate: bool = False,
                 timeout: int = 45) -> str | None:
    try:
        with sr.Microphone(device_index=mic_index) as source:
            recognizer.dynamic_energy_threshold = True
            recognizer.pause_threshold = pause_threshold
            if calibrate:
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
            print(f"   🔴 Listening for {label}...")
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=30)

        print("   🔄 Transcribing...")
        text = recognizer.recognize_whisper(audio, model="base.en")
        print(f'   👨‍💼 Ava: "{text}"')
        return text

    except sr.WaitTimeoutError:
        print(f"   ⏱  Timeout waiting for {label}")
        return None
    except sr.UnknownValueError:
        print(f"   ⚠️  Could not recognise speech for {label}")
        return None
    except Exception as e:
        print(f"   ❌ STT error: {e}")
        return None


def _speak(text: str):
    print(f'   🗣  Ravi: "{text}"')
    speak_sync(text)


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------
def _start_voice_session(driver) -> bool:
    """navigate_to_home → Start Voice Order → arrow. Returns True if active."""
    print("   ↩️  Navigating to home...")
    navigate_to_home(driver)
    time.sleep(3)

    element = None
    for attempt in range(3):
        element = scroll_to_start_voice_order(driver)
        if element:
            break
        if attempt < 2:
            print(f"   ⚠️  Start Voice Order not found (attempt {attempt + 1}/3), retrying...")
            time.sleep(4)

    if not element:
        print("   ❌ Could not find 'Start Voice Order' button")
        return False

    click_start_voice_order(driver, element)
    click_arrow_on_ready_screen(driver)
    active = verify_voice_agent_active(driver)
    if not active:
        print("   ❌ Voice agent did not become active")
    return active


def _close_voice_session(driver):
    navigate_to_home(driver)
    time.sleep(2)


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------
def _judge(ravi: str, ava: str, intent: str, anti_intent: str,
           ollama: OllamaClient) -> dict:
    """Call Ollama to evaluate Ava's response against intent / anti_intent."""
    print("   🤖 Evaluating with Ollama judge...")
    result = ollama.evaluate_dialogue_intent(ravi, ava, intent, anti_intent)
    icon = "✅" if result["passed"] else "❌"
    print(f"   {icon} passed={result['passed']}  reasoning: {result.get('reasoning', '')}")
    return result


# ---------------------------------------------------------------------------
# Run one rule — all variants in a single session
# ---------------------------------------------------------------------------
def run_one_rule(rule: dict, driver, mic_index: int, ollama: OllamaClient) -> dict:
    """
    Run the primary ravi_says + all ravi_variants in ONE voice session:
        navigate → greeting exchange → ask Q1 → capture → ask Q2 → capture → ... → close

    Avoids the per-variant nav overhead that was causing long delays.
    """
    name = rule["name"]
    severity = rule.get("severity", "error")
    intent = rule.get("intent", "").strip()
    anti_intent = rule.get("anti_intent", "").strip()

    primary = rule.get("ravi_says", "").strip()
    variants = rule.get("ravi_variants", [])
    all_questions = ([primary] if primary else []) + list(variants)

    print(f"\n{'═' * 60}")
    print(f"🧪  {name}  ({len(all_questions)} variant(s))")
    print(f"{'═' * 60}")

    if not all_questions:
        return {"name": name, "severity": severity, "skipped": True,
                "reason": "no ravi_says or ravi_variants defined"}

    if not intent:
        return {"name": name, "severity": severity, "skipped": True,
                "reason": "no intent defined — add intent/anti_intent to YAML"}

    recognizer = sr.Recognizer()

    # ── Single navigation + greeting ────────────────────────────────────────
    if not _start_voice_session(driver):
        return {"name": name, "severity": severity, "skipped": False,
                "passed": False,
                "variants": [{"question": q, "label": "primary" if i == 0 else f"variant {i}",
                               "passed": False, "agent": "", "reasoning": "Navigation failed"}
                              for i, q in enumerate(all_questions)]}

    print("\n   [Turn 1] Waiting for Ava's greeting...")
    greeting = _listen_once(recognizer, mic_index, "Ava's greeting",
                            pause_threshold=2.0, calibrate=False)
    if not greeting:
        _close_voice_session(driver)
        return {"name": name, "severity": severity, "skipped": False, "passed": False,
                "variants": [{"question": q,
                               "label": "primary" if i == 0 else f"variant {i}",
                               "passed": False, "agent": "",
                               "reasoning": "No greeting received"}
                              for i, q in enumerate(all_questions)]}

    # Opener: tell Ava we have questions (plural if more than one variant)
    opener = ("Hi, I have a few questions." if len(all_questions) > 1
              else "Hi, I have a quick question.")
    time.sleep(0.5)
    _speak(opener)
    time.sleep(0.3)

    # Drain Ava's acknowledgement — we only care that he finished speaking,
    # not what he said. None = real timeout (agent inactive); empty string = heard
    # something but Whisper couldn't transcribe it (treat as fine and continue).
    print("\n   [Turn 2] Waiting for Ava's acknowledgement...")
    ack = _listen_once(recognizer, mic_index, "Ava's acknowledgement",
                       pause_threshold=1.8, calibrate=True)
    if ack is None:
        _close_voice_session(driver)
        return {"name": name, "severity": severity, "skipped": False, "passed": False,
                "variants": [{"question": q,
                               "label": "primary" if i == 0 else f"variant {i}",
                               "passed": False, "agent": "",
                               "reasoning": "Ava did not acknowledge opening line"}
                              for i, q in enumerate(all_questions)]}

    # ── Ask each variant back-to-back ───────────────────────────────────────
    variant_results = []

    for i, question in enumerate(all_questions):
        label = "primary" if i == 0 else f"variant {i}"
        print(f"\n  ── [{label}] ──────────────────────────────────")

        time.sleep(0.5)
        _speak(question)
        time.sleep(0.3)

        print(f"\n   Waiting for Ava's answer...")
        answer = _listen_once(recognizer, mic_index, "Ava's answer",
                              pause_threshold=2.0, calibrate=True)

        if not answer:
            variant_results.append({
                "question": question, "label": label,
                "passed": False, "agent": "",
                "reasoning": "Ava did not respond to the question",
            })
            # Session may be stale — stop trying further variants
            break

        judgment = _judge(question, answer, intent, anti_intent, ollama)
        variant_results.append({
            "question": question, "label": label,
            "passed": judgment["passed"],
            "agent": answer,
            "reasoning": judgment.get("reasoning", ""),
            "met_required": judgment.get("met_required"),
            "violated_forbidden": judgment.get("violated_forbidden"),
        })

    _close_voice_session(driver)

    overall_passed = bool(variant_results) and all(r["passed"] for r in variant_results)
    return {
        "name": name,
        "severity": severity,
        "skipped": False,
        "passed": overall_passed,
        "variants": variant_results,
    }


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
def _e(text: str) -> str:
    """HTML-escape a string."""
    return html_lib.escape(str(text))


def _build_html_report(all_results: list[dict], start: datetime, end: datetime) -> str:
    total    = len([r for r in all_results if not r.get("skipped")])
    n_passed = sum(1 for r in all_results if not r.get("skipped") and r.get("passed"))
    duration = (end - start).total_seconds()

    rows = []
    for r in all_results:
        name = _e(r["name"])
        if r.get("skipped"):
            rows.append(f"""
            <div class="rule skipped">
              <div class="rule-header">⏭ SKIPPED — {name}</div>
              <div class="reason">{_e(r.get("reason",""))}</div>
            </div>""")
            continue

        status_cls = "passed" if r["passed"] else "failed"
        icon = "✅" if r["passed"] else "❌"
        status_label = "PASSED" if r["passed"] else f"FAILED [{r.get('severity','error')}]"

        variant_rows = []
        for v in r.get("variants", []):
            v_icon = "✅" if v["passed"] else "❌"
            v_cls  = "v-passed" if v["passed"] else "v-failed"
            met    = v.get("met_required")
            viol   = v.get("violated_forbidden")
            sub = ""
            if met is not None:
                sub = (f'<span class="sub-badge">met_required={met}</span>'
                       f'<span class="sub-badge">violated_forbidden={viol}</span>')
            variant_rows.append(f"""
              <tr class="{v_cls}">
                <td>{v_icon} {_e(v["label"])}</td>
                <td class="speech">"{_e(v["question"])}"</td>
                <td class="speech">"{_e(v.get("agent",""))}"</td>
                <td>{_e(v.get("reasoning",""))} {sub}</td>
              </tr>""")

        rows.append(f"""
        <div class="rule {status_cls}">
          <div class="rule-header">{icon} {status_label} — {name}</div>
          <table class="variant-table">
            <thead><tr><th>Variant</th><th>Ravi</th><th>Ava</th><th>Verdict</th></tr></thead>
            <tbody>{"".join(variant_rows)}</tbody>
          </table>
        </div>""")

    summary_cls = "sum-pass" if n_passed == total else "sum-fail"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dialogue Behavior Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f8f9fa; color: #1a1a2e; }}
  h1   {{ font-size: 1.5rem; }}
  .summary {{ display:flex; gap:1.5rem; margin-bottom:1.5rem; flex-wrap:wrap; }}
  .stat {{ background:#fff; border-radius:8px; padding:1rem 1.5rem; box-shadow:0 1px 4px rgba(0,0,0,.1); }}
  .stat span {{ display:block; font-size:2rem; font-weight:700; }}
  .sum-pass span {{ color:#16a34a; }}
  .sum-fail span {{ color:#dc2626; }}
  .rule {{ background:#fff; border-radius:8px; margin-bottom:1rem;
           box-shadow:0 1px 4px rgba(0,0,0,.1); overflow:hidden; }}
  .rule-header {{ padding:.75rem 1rem; font-weight:600; font-size:.95rem; }}
  .rule.passed .rule-header {{ background:#dcfce7; color:#166534; }}
  .rule.failed .rule-header {{ background:#fee2e2; color:#991b1b; }}
  .rule.skipped .rule-header {{ background:#fef9c3; color:#854d0e; }}
  .reason {{ padding:.5rem 1rem; font-size:.85rem; color:#6b7280; }}
  .variant-table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
  .variant-table th {{ background:#f3f4f6; padding:.5rem .75rem; text-align:left; }}
  .variant-table td {{ padding:.5rem .75rem; border-top:1px solid #e5e7eb; vertical-align:top; }}
  .v-passed {{ background:#f0fdf4; }}
  .v-failed {{ background:#fff1f2; }}
  .speech {{ font-style:italic; color:#374151; }}
  .sub-badge {{ display:inline-block; background:#e5e7eb; border-radius:4px;
                padding:1px 6px; font-size:.75rem; margin-left:4px; }}
</style>
</head>
<body>
<h1>Dialogue Behavior Report</h1>
<div class="summary">
  <div class="stat {summary_cls}"><span>{n_passed}/{total}</span>Tests passed</div>
  <div class="stat"><span>{duration:.0f}s</span>Duration</div>
  <div class="stat"><span>{_e(start.strftime("%H:%M:%S"))}</span>Started</div>
</div>
{"".join(rows)}
</body></html>"""


def _write_html_report(all_results: list[dict], start: datetime, end: datetime) -> str:
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    ts   = start.strftime("%Y%m%d_%H%M%S")
    path = reports_dir / f"dialogue_{ts}.html"
    path.write_text(_build_html_report(all_results, start, end), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Suite runner + report
# ---------------------------------------------------------------------------
def run_suite(rules: list[dict], driver, mic_index: int, ollama: OllamaClient) -> bool:
    start      = datetime.now()
    all_results = []
    for rule in rules:
        result = run_one_rule(rule, driver, mic_index, ollama)
        all_results.append(result)
    end = datetime.now()

    print(f"\n{'=' * 60}")
    print("DIALOGUE TEST RESULTS")
    print(f"{'=' * 60}\n")

    overall = True
    for r in all_results:
        if r.get("skipped"):
            print(f"  ⏭  SKIPPED   {r['name']}")
            print(f"      {r['reason']}\n")
            continue

        icon = "✅" if r["passed"] else ("❌" if r["severity"] == "error" else "⚠️ ")
        status = "PASSED" if r["passed"] else "FAILED"
        print(f"  {icon}  {status}    {r['name']}")

        for v in r.get("variants", []):
            v_icon = "✅" if v["passed"] else "❌"
            print(f"      {v_icon} [{v['label']}] \"{v['question']}\"")
            print(f"           Ava     : {v['agent']}")
            print(f"           Verdict : {v['reasoning']}")

        print()
        if not r["passed"] and r["severity"] == "error":
            overall = False

    report_path = _write_html_report(all_results, start, end)
    status = "PASSED" if overall else "FAILED"
    print(f"{'=' * 60}")
    print(f"Overall : {status}")
    print(f"Report  : {report_path}")
    print(f"{'=' * 60}")
    return overall


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Live dialogue intent tests — no order completion needed."
    )
    parser.add_argument("--test", default=None,
                        help="Run only tests whose name contains this substring")
    parser.add_argument("--mic", default=None,
                        help="Microphone name (default: auto-detect from config)")
    parser.add_argument("--contract", default=_CONTRACT,
                        help="Path to agent_behavior.yaml")
    args = parser.parse_args()

    with open(args.contract, encoding="utf-8") as f:
        all_rules = yaml.safe_load(f).get("tests", [])

    rules = all_rules
    if args.test:
        rules = [r for r in all_rules if args.test.lower() in r["name"].lower()]
        if not rules:
            print(f"❌ No test matching '{args.test}' found.")
            sys.exit(1)
        print(f"Running {len(rules)} test(s) matching '{args.test}'")
    else:
        print(f"Running {len(rules)} dialogue test(s)")

    model = _load_ollama_model()
    ollama = OllamaClient(model=model)
    if not ollama.is_available():
        print("❌ Ollama is not running. Start it with: ollama serve")
        sys.exit(1)
    print(f"✅ Ollama judge ready (model: {model})")

    mic_index = find_microphone_index(args.mic)
    driver = launch_app()

    try:
        passed = run_suite(rules, driver, mic_index, ollama)
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        passed = False
    finally:
        try:
            navigate_to_home(driver)
        except Exception:
            pass

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
