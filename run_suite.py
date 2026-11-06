#!/usr/bin/env python3
"""
Test Suite Runner for Voice Ordering Tests.

Loads scenario definitions from scenarios/*.yaml and runs each one
end-to-end, reusing the same Appium session between scenarios.
Between scenarios the app is returned to the home screen and the
voice experience is relaunched.

Usage:
  python run_suite.py                              # run all scenarios/
  python run_suite.py --scenario simple_pepperoni  # run one by file stem or name
  python run_suite.py --tag smoke                  # run tagged subset
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

from src.appium_driver import AppiumDriver
from src.report_generator import generate_report, capture_screenshots
from src.scenario_monitor import ScenarioMonitor
from launch_and_invoke_voice import (
    launch_app,
    scroll_to_start_voice_order,
    click_start_voice_order,
    click_arrow_on_ready_screen,
    get_voice_session_id,
    navigate_to_home,
    PRE_STEP_REGISTRY,
)
from end_to_end_voice_test import run_ai_customer_conversation, prepare_persona
from verify_order import verify_order

SCENARIOS_DIR = Path("scenarios")
APPIUM_URL    = "http://localhost:4723/status"
OLLAMA_URL    = "http://localhost:11434/api/tags"


# ─────────────────────────────────────────────────────────────────────────────
# Appium auto-start
# ─────────────────────────────────────────────────────────────────────────────

def _appium_ready() -> bool:
    """Return True if the Appium server is up and reports ready."""
    try:
        with urllib.request.urlopen(APPIUM_URL, timeout=3) as resp:
            import json
            data = json.loads(resp.read())
            return data.get("value", {}).get("ready", False)
    except Exception:
        return False


def _ensure_appium_running(wait_secs: int = 20) -> None:
    """
    Start Appium in the background if it is not already running.
    Waits up to *wait_secs* seconds for it to become ready.
    Raises RuntimeError if it never becomes ready.
    """
    if _appium_ready():
        print("✅ Appium already running")
        return

    print("⚡ Appium not running — starting in background...")
    log_path = Path("logs/appium.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "w") as log_f:
        subprocess.Popen(
            ["appium"],
            stdout=log_f,
            stderr=log_f,
            start_new_session=True,   # detach from this process group
        )

    deadline = time.time() + wait_secs
    while time.time() < deadline:
        time.sleep(2)
        if _appium_ready():
            print(f"✅ Appium is ready  (log: {log_path})")
            return

    raise RuntimeError(
        f"Appium did not become ready within {wait_secs}s. "
        f"Check {log_path} for details."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Ollama auto-start
# ─────────────────────────────────────────────────────────────────────────────

def _ollama_ready() -> bool:
    """Return True if the Ollama server is up and responding."""
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ensure_ollama_running(wait_secs: int = 30) -> None:
    """Start Ollama in the background if it is not already running."""
    if _ollama_ready():
        print("✅ Ollama already running")
        return

    print("⚡ Ollama not running — starting in background...")
    log_path = Path("logs/ollama.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "w") as log_f:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=log_f,
            stderr=log_f,
            start_new_session=True,
        )

    deadline = time.time() + wait_secs
    while time.time() < deadline:
        time.sleep(2)
        if _ollama_ready():
            print(f"✅ Ollama is ready  (log: {log_path})")
            return

    raise RuntimeError(
        f"Ollama did not become ready within {wait_secs}s. "
        f"Check {log_path} for details."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario loading
# ─────────────────────────────────────────────────────────────────────────────

def _log_has_payment_failure(log_file: str) -> bool:
    """Return True if the conversation log contains a payment failure marker."""
    if not log_file:
        return False
    try:
        with open(log_file) as f:
            return "[PAYMENT FAILED" in f.read()
    except Exception:
        return False


def load_scenarios(scenarios_dir: Path, name_filter: str = None, tag_filter: str = None) -> list:
    """
    Load all *.yaml files from scenarios_dir.

    Args:
        scenarios_dir: directory containing scenario YAML files
        name_filter:   if set, keep only the scenario whose 'name' or file stem matches
        tag_filter:    if set, keep only scenarios whose 'tags' list contains this value

    Returns:
        list of scenario dicts (each has a '_file' key with the source path)
    """
    files = sorted(scenarios_dir.glob("*.yaml"))
    if not files:
        print(f"❌ No scenario YAML files found in {scenarios_dir}/")
        return []

    scenarios = []
    for f in files:
        try:
            with open(f) as fp:
                sc = yaml.safe_load(fp)
            sc["_file"] = str(f)
            scenarios.append(sc)
            print(f"  Loaded: {f.name}  →  {sc.get('name', '(no name)')}")
        except Exception as e:
            print(f"  ⚠️  Failed to load {f.name}: {e}")

    if name_filter:
        scenarios = [
            s for s in scenarios
            if s.get("name") == name_filter or Path(s["_file"]).stem == name_filter
        ]

    if tag_filter:
        scenarios = [s for s in scenarios if tag_filter in (s.get("tags") or [])]

    return scenarios


# ─────────────────────────────────────────────────────────────────────────────
# Single scenario runner
# ─────────────────────────────────────────────────────────────────────────────

def run_scenario(driver: AppiumDriver, scenario: dict, args) -> dict:
    """
    Run one scenario end-to-end.

    Flow:
      1. Clear stale screenshots
      2. Navigate to voice agent (scroll → click → arrow → verify)
      3. Capture session ID (#)
      4. Run AI customer conversation
      5. Verify order against expected_items from YAML
      6. Generate per-scenario HTML report

    Returns:
        dict with keys: name, scenario, results, phase_statuses,
                        start_time, end_time, report_path
    """
    name = scenario.get("name", Path(scenario["_file"]).stem)
    print(f"\n{'#' * 70}")
    print(f"  SCENARIO: {name}")
    print(f"{'#' * 70}")

    start_time = datetime.now()
    phase_statuses = {
        "navigation":   "skipped",
        "disclaimer":   "skipped",
        "conversation": "skipped",
        "verification": "skipped",
    }
    log_file      = None
    session_id    = ""
    selected_slot = None
    results    = {
        "passed": False, "score": 0,
        "matched_items": [], "missing_items": [], "extra_items": [],
        "reasoning": "Scenario did not complete.", "overview": {},
    }
    monitor_findings = {}

    screenshot_dir = driver.config["test"]["screenshot_dir"]
    app_package    = driver.config["capabilities"]["appPackage"]

    monitor = ScenarioMonitor(app_package, driver)

    try:
        # ── Pre-flight: generate persona BEFORE launching the app ─────────
        # Ollama generation can take several seconds. Doing it here avoids a
        # gap between the voice agent going live and Ravi being ready to respond.
        print(f"\n{'=' * 70}")
        print("PRE-FLIGHT: Preparing Ravi's Persona")
        print(f"{'=' * 70}")
        ravi_persona = prepare_persona(
            persona_name=scenario.get("persona"),
            # Do NOT pass scenario description here — named persona file takes priority
            # and the description is just human documentation, not for Ollama generation.
        )

        # Start parallel monitoring now that the scenario is about to run
        monitor.start()

        # ── Clear stale screenshots from the previous scenario ─────────────
        for png in Path(screenshot_dir).glob("*.png"):
            try:
                png.unlink()
            except Exception:
                pass

        # ── PHASE 1: Navigate to voice agent ──────────────────────────────
        print(f"\n{'=' * 70}")
        print("PHASE 1: Navigate to Voice Agent")
        print(f"{'=' * 70}")
        monitor.mark_phase("navigation")

        # Capture app state at the start of each scenario (after stale screenshots cleared).
        driver.take_screenshot("step1_app_launched")

        # Always return to the home screen before navigating to the voice agent.
        # The app uses noReset=true so it may be on any screen (e.g. ORDER COMPLETE
        # from a previous run).  navigate_to_home() is idempotent — it is a no-op
        # when the app is already on the home screen.
        navigate_to_home(driver)
        time.sleep(3)  # Give home screen time to fully load after navigation

        # ── Pre-steps (e.g. order_ahead time selection) ───────────────────────
        pre_steps = scenario.get("pre_steps") or []
        pre_step_results = {}
        for step_name in pre_steps:
            fn = PRE_STEP_REGISTRY.get(step_name)
            if fn is None:
                raise RuntimeError(f"Unknown pre_step '{step_name}' — add it to PRE_STEP_REGISTRY")
            pre_step_results[step_name] = fn(driver)
        selected_slot = (pre_step_results.get("order_ahead")
                        or pre_step_results.get("order_ahead_delivery")
                        or pre_step_results.get("order_ahead_carryout"))

        # After pre-steps the app may be on a store page or loading screen.
        # Navigate back to home so the "Start Voice Order" banner is reachable.
        if pre_steps:
            navigate_to_home(driver)
            time.sleep(4)  # give the home banner extra time to settle

        # Retry up to 3 times — home screen banner may take a moment to appear
        # (e.g. after returning from ORDER COMPLETE screen).
        element = None
        for _retry in range(3):
            element = scroll_to_start_voice_order(driver)
            if element:
                break
            if _retry < 2:
                print(f"  ⏳ 'Start Voice Order' not found — retrying in 4s "
                      f"(attempt {_retry + 2}/3)...")
                driver.take_screenshot(f"nav_retry_{_retry + 1}")
                time.sleep(4)

        if not element:
            print("❌ Could not find 'Start Voice Order' button after 3 attempts")
            phase_statuses["navigation"] = "failed"
            # monitor.stop() is called in the finally block below
            raise RuntimeError("'Start Voice Order' button not found after 3 attempts")

        click_start_voice_order(driver, element)
        voice_screen_texts = click_arrow_on_ready_screen(driver)

        # Disclaimer check: deferred to post-conversation (see below).
        # The disclaimer renders alongside Ava's first greeting — it is NOT present
        # in the pre-scraped texts (which only contain the nav bar elements at
        # loading-cleared time).  After the conversation the voice ordering screen
        # is still visible and the disclaimer is fully rendered, so page_source finds it.
        phase_statuses["navigation"] = "passed"

        session_id = get_voice_session_id(driver)

        # ── PHASE 2: AI customer conversation ─────────────────────────────
        print(f"\n{'=' * 70}")
        print("PHASE 2: AI Customer Conversation")
        print(f"{'=' * 70}")
        monitor.mark_phase("conversation")

        log_file = run_ai_customer_conversation(
            persona_name=scenario.get("persona"),
            mic_name=args.mic,
            termination_trigger=scenario.get("termination_trigger", "cvv"),
            persona_text=ravi_persona,
            cvv=scenario.get("cvv", "382"),
            expected_items=scenario.get("expected_items"),
            expected_schedule=selected_slot,
            driver=driver,
            phase_statuses=phase_statuses,
            pre_order_queries=scenario.get("pre_order_queries"),
            voice_items=scenario.get("voice_items"),
            items_to_remove=scenario.get("items_to_remove"),
            post_order_requests=scenario.get("post_order_requests"),
            mind_change_item=scenario.get("mind_change_item"),
            pipa_dough_action=scenario.get("pipa_dough_action", "apply"),
        )
        phase_statuses["conversation"] = "passed"

        # ── PHASE 3: Order verification ────────────────────────────────────
        print(f"\n{'=' * 70}")
        print("PHASE 3: Verify Order")
        print(f"{'=' * 70}")
        monitor.mark_phase("verification")

        if _log_has_payment_failure(log_file):
            print("❌ Payment failure detected in conversation log — skipping order verification.")
            driver.take_screenshot("payment_failed_screen")
            results = {
                "passed": False, "score": 0,
                "matched_items": [], "missing_items": scenario.get("expected_items") or [],
                "extra_items": [],
                "reasoning": "Payment failed — the app could not process the payment.",
                "overview": {},
            }
            phase_statuses["verification"] = "failed"
        else:
            expected_items = scenario.get("expected_items") or None
            results = verify_order(driver, expected_items=expected_items,
                                   log_file=log_file,
                                   expected_schedule=selected_slot or scenario.get("expected_time"),
                                   expected_delivery_type=scenario.get("expected_delivery_type"))
            phase_statuses["verification"] = "passed" if results["passed"] else "failed"

    except KeyboardInterrupt:
        print("\n🛑 Scenario interrupted by user")
        raise
    except Exception as e:
        print(f"❌ Scenario error: {e}")
        import traceback
        traceback.print_exc()
        try:
            driver.take_screenshot("scenario_exception")
        except Exception:
            pass
    finally:
        monitor.stop()
        monitor_findings = monitor.get_findings()
        if monitor_findings.get("total_errors", 0):
            print(f"  [monitor] {monitor_findings['total_errors']} logcat error(s) detected "
                  f"— see report Health Monitor section.")

    return _finish_scenario(name, scenario, results, phase_statuses,
                            start_time, log_file, session_id, driver,
                            monitor_findings)


def _finish_scenario(name, scenario, results, phase_statuses,
                     start_time, log_file, session_id, driver,
                     monitor_findings=None) -> dict:
    """Package everything the report generator needs into the result dict."""
    end_time       = datetime.now()
    screenshot_dir = driver.config["test"]["screenshot_dir"]
    sc_name        = scenario.get("description") or name

    status = "✅ PASSED" if results.get("passed") else "❌ FAILED"
    print(f"\n  {status}  score={results.get('score')}/100")

    # Capture screenshots now — the directory is cleared for the next scenario
    # immediately after this function returns, so we must embed them here.
    screenshots = capture_screenshots(screenshot_dir)

    return {
        "name":             name,
        "scenario":         scenario,
        "results":          results,
        "phase_statuses":   phase_statuses,
        "monitor_findings": monitor_findings or {},
        "start_time":       start_time,
        "end_time":         end_time,
        "log_file":         log_file,
        "screenshot_dir":   screenshot_dir,
        "screenshots":      screenshots,
        "metadata": {
            "persona":    scenario.get("persona"),
            "scenario":   sc_name,
            "mic":        "—",
            "session_id": session_id,
            "start_time": start_time,
            "end_time":   end_time,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Suite runner
# ─────────────────────────────────────────────────────────────────────────────

def run_suite(args) -> int:
    print(f"\n{'=' * 70}")
    print("Loading scenarios...")
    print(f"{'=' * 70}")

    scenarios = load_scenarios(
        SCENARIOS_DIR,
        name_filter=getattr(args, "scenario", None),
        tag_filter=getattr(args, "tag", None),
    )

    if not scenarios:
        print("❌ No scenarios to run")
        return 1

    print(f"\n{'=' * 70}")
    print(f"SUITE: {len(scenarios)} scenario(s) queued")
    print(f"{'=' * 70}")
    for sc in scenarios:
        print(f"  • {sc.get('name', sc['_file'])}")

    suite_start  = datetime.now()
    all_results  = []
    report_path  = None
    _ensure_ollama_running()
    _ensure_appium_running()
    driver       = launch_app(config_path=getattr(args, "config", "config/appium_config.yaml"))

    try:
        for i, scenario in enumerate(scenarios):
            result = run_scenario(driver, scenario, args)
            all_results.append(result)

            # Between scenarios: go home and let the screen settle
            if i < len(scenarios) - 1:
                print(f"\n↩️  Returning to Home screen for next scenario...")
                navigate_to_home(driver)
                time.sleep(3)

    except KeyboardInterrupt:
        print("\n🛑 Suite interrupted by user")
    finally:
        # Generate the single combined report for all scenarios run so far
        # (even if the suite was interrupted or a scenario crashed).
        suite_end = datetime.now()
        if all_results:
            try:
                report_path = generate_report(all_results, suite_start, suite_end, show_images=True)
                passed = sum(1 for r in all_results if r["results"].get("passed"))
                total  = len(all_results)
                print(f"\n{'=' * 70}")
                print(f"SUITE COMPLETE  {passed}/{total} passed")
                print(f"Report: {report_path}")
                print(f"{'=' * 70}")
            except Exception as report_err:
                print(f"\n⚠️  Report generation failed: {report_err}")

        driver.stop()

    passed = sum(1 for r in all_results if r["results"].get("passed"))
    total  = len(all_results)

    print(f"\n{'=' * 70}")
    print(f"SUITE COMPLETE  {passed}/{total} passed")
    if report_path:
        print(f"Report: {report_path}")
    print(f"{'=' * 70}")

    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Voice Order Test Suite Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_suite.py                              # run every scenario
  python run_suite.py --scenario simple_pepperoni  # one scenario by file stem
  python run_suite.py --tag smoke                  # smoke-tagged scenarios only
  python run_suite.py --mic "External Microphone"  # custom mic
  python run_suite.py --config config/appium_config.testgrid.yaml
        """,
    )
    parser.add_argument(
        "--scenario",
        help="Run a specific scenario by file stem (e.g. simple_pepperoni) or full name",
    )
    parser.add_argument(
        "--tag",
        help="Run only scenarios whose tags list contains this value (e.g. smoke)",
    )
    parser.add_argument(
        "--mic",
        default="MacBook Pro Microphone",
        help="Microphone name for capturing phone audio (default: MacBook Pro Microphone)",
    )
    parser.add_argument(
        "--config",
        default="config/appium_config.yaml",
        help="Path to Appium config YAML (default: config/appium_config.yaml)",
    )
    args = parser.parse_args()
    sys.exit(run_suite(args))


if __name__ == "__main__":
    main()
