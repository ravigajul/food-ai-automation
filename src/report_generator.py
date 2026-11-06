"""
HTML Test Report Generator for Voice Ordering Tests.

Single entry point: generate_report()
  - 1 scenario  → self-contained single-scenario HTML report
  - N scenarios → summary table + per-scenario sections, all in one HTML file

Screenshots are embedded as base64 data URIs when show_images=True.
"""

import base64
import os
import re
from datetime import datetime
from pathlib import Path

# Screenshot filename stem → human-readable caption (in display order)
SCREENSHOT_CAPTIONS = [
    # Step 1 — App launched (always first)
    ("step1_app_launched",                   "Step 1: App Launched"),
    # Order Ahead pre-steps — delivery (happen before voice-agent navigation)
    ("order_ahead_00_before_tap",            "Order Ahead: Before Tap"),
    ("order_ahead_tap_failed",               "Order Ahead: Tap Failed"),
    ("order_ahead_01_delivery_options_panel","Order Ahead: Delivery Options Panel"),
    ("order_ahead_02_delivery_time_screen",  "Order Ahead: Delivery Time Screen"),
    ("order_ahead_02_day_time_selected",     "Order Ahead: Day/Time Selected"),
    ("order_ahead_03_calendar",              "Order Ahead: Calendar"),
    ("order_ahead_03b_day_selected",         "Order Ahead: Day Selected"),
    ("order_ahead_04_time_slots",            "Order Ahead: Time Slots"),
    ("order_ahead_05_slot_selected",         "Order Ahead: Slot Selected"),
    ("order_ahead_07_complete",              "Order Ahead: Schedule Confirmed"),
    # Order Ahead pre-steps — carryout
    ("oa_carryout_02_after_chevron",         "OA Carryout: After Chevron"),
    ("oa_carryout_03_panel_open",            "OA Carryout: Panel Open"),
    ("oa_carryout_04_carryout_tab",          "OA Carryout: Carryout Tab"),
    ("oa_carryout_05a_focus",                "OA Carryout: ZIP Field Focused"),
    ("oa_carryout_05b_typed",                "OA Carryout: ZIP Typed"),
    ("oa_carryout_05_zip_done",              "OA Carryout: ZIP Submitted"),
    ("oa_carryout_06_search_results",        "OA Carryout: Store Search Results"),
    ("oa_carryout_07_store_selected",        "OA Carryout: Store Selected"),
    ("oa_carryout_08_future_order_screen",   "OA Carryout: Future Order Screen"),
    ("oa_carryout_09_calendar",              "OA Carryout: Calendar"),
    ("oa_carryout_09b_day_selected",         "OA Carryout: Day Selected"),
    ("oa_carryout_10_time_slots",            "OA Carryout: Time Slots"),
    ("oa_carryout_11_slot_selected",         "OA Carryout: Slot Selected"),
    ("oa_carryout_12_complete",              "OA Carryout: Schedule Confirmed"),
    # Phase 1 — Navigation to voice agent
    ("step2_start_voice_order_visible",      "Step 2: Voice Order Button Visible"),
    ("step3_voice_agent_launched",           "Step 3: Voice Agent Screen"),
    ("nav_retry_1",                          "Navigation Retry 1"),
    ("nav_retry_2",                          "Navigation Retry 2"),
    ("nav_retry_3",                          "Navigation Retry 3"),
    ("step6_agent_verified",                 "Voice Agent Verified"),
    ("step6_agent_not_verified",             "Voice Agent NOT Verified"),
    # Phase 2 — Disclaimer
    ("ai_disclaimer_check",                  "AI Disclaimer Verification"),
    # Phase 4 — Waiting for Order Complete screen
    ("verification_waiting",                 "Verification: Last Screen Seen While Waiting"),
    ("verification_timeout",                 "Verification: Timeout (Order Complete never appeared)"),
    ("payment_failed_screen",                "Verification: Payment Failed"),
    ("pipa_track_detected",                  "Verification: Pipa Track Screen Detected"),
    ("pipa_track_direct",                    "Verification: Pipa Track (Direct)"),
    ("order_complete_after_back",            "Verification: Order Complete (after back from Pipa Track)"),
    ("scenario_exception",                   "Scenario Exception — current screen at crash"),
    # Phase 4 — Order Complete screen checks
    ("order_complete_screen",                "Order Complete Screen"),
    ("order_complete_overview",              "Order Overview Tab"),
    ("order_complete_details",               "Order Details Tab"),
    ("cart_verification",                    "Cart Verification"),
    ("verification_quantity_mismatch",       "Verification: Quantity Mismatch"),
    ("verification_delivery_mismatch",       "Verification: Delivery Type Mismatch"),
    ("verification_schedule_mismatch",       "Verification: Schedule Mismatch"),
    ("verification_complete",                "Verification: Passed — Final Screen"),
    ("verification_failed",                  "Verification: Failed — Final Screen"),
]

# Phase key → ordered list of screenshot stems to show inline in the phase section

# ─────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _duration_str(start: datetime, end: datetime) -> str:
    delta = end - start
    total = int(delta.total_seconds())
    m, s = divmod(total, 60)
    return f"{m}m {s}s" if m else f"{s}s"


def _phase_icon(status: str) -> str:
    return {"passed": "✅", "failed": "❌", "skipped": "⏭"}.get(status, "❓")


def _phase_color(status: str) -> str:
    return {"passed": "#22c55e", "failed": "#ef4444", "skipped": "#94a3b8"}.get(status, "#94a3b8")


def _esc(text) -> str:
    text = text if isinstance(text, str) else str(text)
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Conversation log parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_conversation(log_file: str) -> list[dict]:
    turns = []
    if not log_file or not os.path.isfile(log_file):
        return turns
    with open(log_file, "r") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("Agent:"):
                text = line[len("Agent:"):].strip()
                if text:
                    turns.append({"speaker": "Agent", "text": text})
            elif line.startswith("Ravi:"):
                text = line[len("Ravi:"):].strip()
                # Extract and strip the [DETERMINISTIC] / [OLLAMA] routing tag
                method = None
                if text.endswith("[DETERMINISTIC]"):
                    method = "deterministic"
                    text = text[: -len("[DETERMINISTIC]")].strip()
                elif text.endswith("[OLLAMA]"):
                    method = "ollama"
                    text = text[: -len("[OLLAMA]")].strip()
                if text:
                    turns.append({"speaker": "Ravi", "text": text, "method": method})
            elif line.startswith("[") and line.endswith("]"):
                turns.append({"speaker": "system", "text": line})
    return turns


# ─────────────────────────────────────────────────────────────────────────────
# Shared CSS
# ─────────────────────────────────────────────────────────────────────────────

def _build_styles() -> str:
    return """
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             background: #f1f5f9; color: #1e293b; line-height: 1.5; }

      .header { background: linear-gradient(135deg, #1e3a5f 0%, #c8102e 100%);
                color: white; padding: 28px 40px; display: flex;
                align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
      .header h1 { font-size: 1.6rem; font-weight: 700; }
      .header .meta { font-size: 0.85rem; opacity: 0.85; margin-top: 4px; }

      .badge { display: inline-flex; align-items: center; gap: 8px;
               padding: 10px 22px; border-radius: 999px; font-weight: 700;
               font-size: 1.05rem; letter-spacing: 0.04em; }
      .badge.passed { background: #22c55e; color: white; }
      .badge.failed { background: #ef4444; color: white; }

      .section { background: white; border-radius: 12px; padding: 28px 32px;
                 margin: 24px 40px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
      .section h2 { font-size: 1.1rem; font-weight: 700; color: #1e3a5f;
                    border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;
                    margin-bottom: 20px; }

      /* Scenario divider (suite mode) */
      .scenario-block { border: 2px solid #e2e8f0; border-radius: 14px;
                        margin: 32px 40px; overflow: hidden; }
      .scenario-header { padding: 18px 32px; display: flex; align-items: center;
                         justify-content: space-between; flex-wrap: wrap; gap: 8px; }
      .scenario-header h2 { font-size: 1.15rem; font-weight: 700; margin: 0; }
      .scenario-header .dur { font-size: 0.82rem; opacity: 0.75; }
      .scenario-block .section { margin: 16px 20px; }

      .config-table { width: 100%; border-collapse: collapse; }
      .config-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; font-size: 0.92rem; }
      .config-table td:first-child { color: #64748b; width: 180px; font-weight: 600; }

      .phases { display: flex; gap: 16px; flex-wrap: wrap; }
      .phase-card { flex: 1; min-width: 200px; border-radius: 10px; padding: 18px 20px;
                    display: flex; align-items: center; gap: 14px; }
      .phase-card .icon { font-size: 1.8rem; line-height: 1; }
      .phase-card .info .label { font-weight: 700; font-size: 0.95rem; }
      .phase-card .info .status { font-size: 0.82rem; text-transform: uppercase;
                                   letter-spacing: 0.06em; font-weight: 600; margin-top: 2px; }

      .items-table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
      .items-table th { background: #f8fafc; padding: 10px 14px; text-align: left;
                         color: #64748b; font-weight: 600; font-size: 0.8rem;
                         text-transform: uppercase; letter-spacing: 0.05em; }
      .items-table td { padding: 10px 14px; border-bottom: 1px solid #f1f5f9; }
      .items-table tr.matched td { background: #f0fdf4; }
      .items-table tr.missing td { background: #fef2f2; }
      .items-table tr.extra td { background: #fff7ed; }
      .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
                     margin-right: 8px; }
      .dot-green { background: #22c55e; }
      .dot-red   { background: #ef4444; }
      .dot-orange{ background: #f97316; }

      .overview-table { width: 100%; border-collapse: collapse; margin-top: 16px;
                         font-size: 0.9rem; }
      .overview-table td { padding: 7px 12px; border-bottom: 1px solid #f1f5f9; }
      .overview-table td:first-child { color: #64748b; font-weight: 600; width: 160px; }

      .score-row { display: flex; align-items: center; gap: 24px; margin-bottom: 20px; }
      .score-circle { width: 80px; height: 80px; border-radius: 50%;
                       display: flex; align-items: center; justify-content: center;
                       font-size: 1.4rem; font-weight: 800; color: white; flex-shrink: 0; }
      .score-desc { font-size: 0.9rem; color: #64748b; }
      .score-desc strong { color: #1e293b; font-size: 1rem; }

      .chat { display: flex; flex-direction: column; gap: 10px; }
      .bubble-wrap { display: flex; flex-direction: column; }
      .bubble-wrap.agent { align-items: flex-start; }
      .bubble-wrap.ravi  { align-items: flex-end; }
      .speaker-label { font-size: 0.72rem; font-weight: 700; color: #94a3b8;
                        text-transform: uppercase; letter-spacing: 0.06em;
                        margin-bottom: 3px; padding: 0 4px; }
      .bubble { max-width: 70%; padding: 10px 14px; border-radius: 16px;
                 font-size: 0.9rem; line-height: 1.5; }
      .bubble.agent { background: #f1f5f9; color: #1e293b; border-bottom-left-radius: 4px; }
      .bubble.ravi  { background: #1e3a5f; color: white; border-bottom-right-radius: 4px; }
      .bubble.system { background: #fef9c3; color: #92400e; font-style: italic;
                        border-radius: 8px; font-size: 0.82rem; max-width: 100%; }

      .screenshot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
                           gap: 24px; }
      .screenshot-card { border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;
                           box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
      .screenshot-card img { width: 100%; display: block; object-fit: contain;
                               background: #0f172a; max-height: 680px; }
      .screenshot-caption { padding: 8px 12px; font-size: 0.8rem; color: #64748b;
                              font-weight: 600; background: #f8fafc; }

      .reasoning { background: #f8fafc; border-left: 4px solid #94a3b8; border-radius: 6px;
                    padding: 12px 16px; font-size: 0.88rem; color: #475569; margin-top: 16px; }

      /* Suite summary table */
      .summary-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
      .summary-table th { background: #f8fafc; padding: 10px 14px; text-align: left;
                           color: #64748b; font-weight: 600; font-size: 0.8rem;
                           text-transform: uppercase; letter-spacing: 0.05em; }
      .summary-table td { padding: 11px 14px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
    </style>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Section builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_header(title: str, passed: bool, score: int,
                  start: datetime, end: datetime, subtitle: str = "") -> str:
    dur = _duration_str(start, end)
    ts  = start.strftime("%Y-%m-%d %H:%M:%S")
    badge_class = "passed" if passed else "failed"
    badge_text  = "PASSED" if passed else "FAILED"
    sub_html = f'<div class="meta">{_esc(subtitle)}</div>' if subtitle else ""
    return f"""
    <div class="header">
      <div>
        <h1>{_esc(title)}</h1>
        <div class="meta">{_esc(ts)} &nbsp;|&nbsp; Duration: {_esc(dur)}</div>
        {sub_html}
      </div>
      <div style="display:flex;align-items:center;gap:16px;">
        <div class="badge {badge_class}">{badge_text}</div>
        <div class="badge" style="background:#1e3a5f;">Score: {score}/100</div>
      </div>
    </div>
"""


def _build_suite_header(suite_results: list, suite_start: datetime, suite_end: datetime) -> str:
    total   = len(suite_results)
    passed  = sum(1 for r in suite_results if r["results"].get("passed"))
    overall = passed == total
    score   = int(sum(r["results"].get("score", 0) for r in suite_results) / total) if total else 0
    subtitle = f"{passed}/{total} scenarios passed"
    return _build_header(
        "Voice Ordering — Test Suite",
        overall, score, suite_start, suite_end, subtitle,
    )


def _build_config(metadata: dict) -> str:
    persona    = _esc(metadata.get("persona") or "default")
    scenario   = _esc(metadata.get("scenario") or "—")
    mic        = _esc(metadata.get("mic") or "—")
    session_id = metadata.get("session_id") or ""

    rows_html = []
    for k, v in [("Persona", persona), ("Scenario", scenario), ("Microphone", mic)]:
        rows_html.append(f'<tr><td>{k}</td><td>{v}</td></tr>')

    if session_id and session_id != "—":
        cell = (
            f'<code style="font-family:monospace;background:#f1f5f9;'
            f'padding:2px 6px;border-radius:4px;user-select:all;">{_esc(session_id)}</code>'
            f' <span style="font-size:0.75rem;color:#94a3b8;">(click to select)</span>'
        )
    else:
        cell = "—"
    rows_html.append(f'<tr><td>Session ID</td><td>{cell}</td></tr>')

    return f"""
    <div class="section">
      <h2>Test Configuration</h2>
      <table class="config-table">{''.join(rows_html)}</table>
    </div>
"""


def _build_monitor(findings: dict) -> str:
    """Render Health Monitor section — only shown when there is something to report."""
    if not findings:
        return ""

    timeline     = findings.get("timeline", [])
    errors       = findings.get("errors", [])
    activity_log = findings.get("activity_log", [])

    # Skip rendering if nothing notable happened
    if not errors and not activity_log:
        return ""

    rows_errors = ""
    if errors:
        rows_errors = "".join(
            f'<tr style="background:#fef2f2;">'
            f'<td style="color:#94a3b8;font-family:monospace;font-size:0.8rem;">{_esc(e["ts"])}</td>'
            f'<td><span style="background:#ef4444;color:white;padding:1px 6px;border-radius:3px;'
            f'font-size:0.75rem;font-weight:700;">{_esc(e["phase"])}</span></td>'
            f'<td style="font-family:monospace;font-size:0.78rem;word-break:break-all;">'
            f'{_esc(e["line"][:200])}</td></tr>'
            for e in errors
        )
        errors_html = f"""
        <h3 style="margin:0 0 10px;font-size:0.95rem;color:#ef4444;">
          Logcat Errors ({len(errors)})
        </h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
          <thead>
            <tr style="background:#f8fafc;">
              <th style="padding:8px 10px;text-align:left;color:#64748b;font-size:0.78rem;
                         font-weight:600;white-space:nowrap;width:100px;">Time</th>
              <th style="padding:8px 10px;text-align:left;color:#64748b;font-size:0.78rem;
                         font-weight:600;width:120px;">Phase</th>
              <th style="padding:8px 10px;text-align:left;color:#64748b;font-size:0.78rem;
                         font-weight:600;">Log Line</th>
            </tr>
          </thead>
          <tbody>{rows_errors}</tbody>
        </table>"""
    else:
        errors_html = '<p style="color:#22c55e;font-size:0.88rem;">No logcat errors detected.</p>'

    rows_activity = ""
    if activity_log:
        rows_activity = "".join(
            f'<tr><td style="color:#94a3b8;font-family:monospace;font-size:0.8rem;'
            f'white-space:nowrap;padding:6px 10px;">{_esc(a["ts"])}</td>'
            f'<td style="padding:6px 10px;"><span style="background:#1e3a5f;color:white;'
            f'padding:1px 6px;border-radius:3px;font-size:0.75rem;font-weight:700;">'
            f'{_esc(a["phase"])}</span></td>'
            f'<td style="font-family:monospace;font-size:0.82rem;padding:6px 10px;">'
            f'{_esc(a["activity"])}</td></tr>'
            for a in activity_log
        )
        activity_html = f"""
        <h3 style="margin:16px 0 10px;font-size:0.95rem;color:#1e3a5f;">
          Activity Changes ({len(activity_log)})
        </h3>
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#f8fafc;">
              <th style="padding:6px 10px;text-align:left;color:#64748b;font-size:0.78rem;
                         font-weight:600;width:100px;">Time</th>
              <th style="padding:6px 10px;text-align:left;color:#64748b;font-size:0.78rem;
                         font-weight:600;width:120px;">Phase</th>
              <th style="padding:6px 10px;text-align:left;color:#64748b;font-size:0.78rem;
                         font-weight:600;">Activity</th>
            </tr>
          </thead>
          <tbody>{rows_activity}</tbody>
        </table>"""
    else:
        activity_html = ""

    return f"""
    <div class="section">
      <h2>Health Monitor</h2>
      {errors_html}
      {activity_html}
    </div>
"""


def _build_phases(phase_statuses: dict) -> str:
    phases = [
        ("navigation",   "Phase 1", "Navigation to Voice Agent"),
        ("disclaimer",   "Phase 2", "AI Disclaimer Verification"),
        ("conversation", "Phase 3", "AI Customer Conversation"),
        ("verification", "Phase 4", "Order Verification"),
    ]
    cards = []
    for key, num, label in phases:
        status = phase_statuses.get(key, "skipped")
        icon   = _phase_icon(status)
        color  = _phase_color(status)
        cards.append(f"""
        <div class="phase-card" style="background:{color}18;border:1px solid {color}40;">
          <div class="icon">{icon}</div>
          <div class="info">
            <div class="label">{_esc(num)}: {_esc(label)}</div>
            <div class="status" style="color:{color};">{_esc(status)}</div>
          </div>
        </div>""")
    return f"""
    <div class="section">
      <h2>Test Phases</h2>
      <div class="phases">{''.join(cards)}</div>
    </div>
"""


def _build_verification(results: dict) -> str:
    matched   = results.get("matched_items", [])
    missing   = results.get("missing_items", [])
    extra     = results.get("extra_items", [])
    score     = results.get("score", 0)
    passed    = results.get("passed", False)
    reasoning = results.get("reasoning", "")
    overview  = results.get("overview") or {}

    score_color = "#22c55e" if score >= 80 else "#f97316" if score >= 50 else "#ef4444"

    item_rows = []
    for item in matched:
        item_rows.append(
            f'<tr class="matched"><td><span class="status-dot dot-green"></span>Matched</td>'
            f'<td>{_esc(item)}</td></tr>'
        )
    for item in missing:
        item_rows.append(
            f'<tr class="missing"><td><span class="status-dot dot-red"></span>Missing</td>'
            f'<td>{_esc(item)}</td></tr>'
        )
    for item in extra:
        item_rows.append(
            f'<tr class="extra"><td><span class="status-dot dot-orange"></span>Extra</td>'
            f'<td>{_esc(item)}</td></tr>'
        )

    items_table = (
        f'<table class="items-table"><thead><tr><th>Status</th><th>Item</th></tr></thead>'
        f'<tbody>{"".join(item_rows)}</tbody></table>'
        if item_rows else
        '<p style="color:#94a3b8;font-size:0.9rem;">No items to display.</p>'
    )

    ov_fields = [
        ("Order #",      overview.get("order_number")),
        ("Item count",   overview.get("item_count")),
        ("Payment",      overview.get("payment")),
        ("Order total",  overview.get("order_total")),
        ("Total amount", overview.get("order_total_amount")),
    ]
    ov_rows = "".join(
        f'<tr><td>{k}</td><td>{_esc(v)}</td></tr>' for k, v in ov_fields if v
    )
    overview_html = (
        f'<h3 style="margin:20px 0 8px;font-size:0.95rem;color:#1e3a5f;">Order Overview</h3>'
        f'<table class="overview-table"><tbody>{ov_rows}</tbody></table>'
        if ov_rows else ""
    )

    # ── Delivery & Schedule verification rows ──────────────────────────────
    expected_delivery_type = results.get("expected_delivery_type")
    expected_schedule      = results.get("expected_schedule")
    delivery_type          = overview.get("delivery_type", "")
    scheduled_time         = overview.get("scheduled_time", "")
    schedule_ok            = results.get("schedule_ok")

    delivery_rows = []
    if expected_delivery_type or delivery_type:
        if expected_delivery_type:
            dt_match = delivery_type.lower() == expected_delivery_type.lower() if delivery_type else False
            color    = "#22c55e" if dt_match else "#ef4444"
            label    = (
                f'<span style="color:{color};font-weight:700;">'
                f'{_esc(delivery_type or "(not found)")}</span>'
                f' <span style="color:#94a3b8;font-size:0.85em;">'
                f'(expected: {_esc(expected_delivery_type)})</span>'
            )
        else:
            label = _esc(delivery_type)
        delivery_rows.append(f'<tr><td>Delivery Type</td><td>{label}</td></tr>')

    if expected_schedule or scheduled_time:
        if expected_schedule:
            s_color = "#22c55e" if schedule_ok else "#ef4444"
            label   = (
                f'<span style="color:{s_color};font-weight:700;">'
                f'{_esc(scheduled_time or "(not found)")}</span>'
                f' <span style="color:#94a3b8;font-size:0.85em;">'
                f'(expected: {_esc(expected_schedule)})</span>'
            )
        else:
            label = _esc(scheduled_time)
        delivery_rows.append(f'<tr><td>Scheduled Time</td><td>{label}</td></tr>')

    delivery_html = (
        f'<h3 style="margin:20px 0 8px;font-size:0.95rem;color:#1e3a5f;">Delivery &amp; Schedule</h3>'
        f'<table class="overview-table"><tbody>{"".join(delivery_rows)}</tbody></table>'
        if delivery_rows else ""
    )

    reasoning_html = (
        f'<div class="reasoning"><strong>Reasoning:</strong> {_esc(reasoning)}</div>'
        if reasoning else ""
    )

    return f"""
    <div class="section">
      <h2>Order Verification</h2>
      <div class="score-row">
        <div class="score-circle" style="background:{score_color};">{score}</div>
        <div class="score-desc">
          <strong>{'Order verified successfully' if passed else 'Order verification failed'}</strong><br>
          Matched: {len(matched)} &nbsp;|&nbsp; Missing: {len(missing)} &nbsp;|&nbsp; Extra: {len(extra)}
        </div>
      </div>
      {items_table}
      {overview_html}
      {delivery_html}
      {reasoning_html}
    </div>
"""


def _build_conversation(log_file: str) -> str:
    turns = _parse_conversation(log_file)
    if not turns:
        return ""
    bubbles = []
    for turn in turns:
        speaker = turn["speaker"]
        text    = _esc(turn["text"])
        if speaker == "system":
            bubbles.append(
                f'<div class="bubble-wrap agent">'
                f'<div class="bubble system">{text}</div></div>'
            )
        elif speaker == "Agent":
            bubbles.append(
                f'<div class="bubble-wrap agent">'
                f'<div class="speaker-label">Voice Agent</div>'
                f'<div class="bubble agent">{text}</div></div>'
            )
        else:
            method = turn.get("method")
            if method == "deterministic":
                badge = (
                    '<span style="font-size:0.6rem;background:#22c55e;color:white;'
                    'padding:1px 5px;border-radius:3px;margin-left:6px;'
                    'vertical-align:middle;font-weight:700;letter-spacing:0.04em;">DET</span>'
                )
            elif method == "ollama":
                badge = (
                    '<span style="font-size:0.6rem;background:#7c3aed;color:white;'
                    'padding:1px 5px;border-radius:3px;margin-left:6px;'
                    'vertical-align:middle;font-weight:700;letter-spacing:0.04em;">AI</span>'
                )
            else:
                badge = ""
            bubbles.append(
                f'<div class="bubble-wrap ravi">'
                f'<div class="speaker-label">Ravi (AI Customer)</div>'
                f'<div class="bubble ravi">{text}{badge}</div></div>'
            )
    legend = (
        '<div style="display:flex;gap:12px;margin-bottom:16px;font-size:0.78rem;color:#64748b;">'
        '<span><span style="background:#22c55e;color:white;padding:1px 6px;border-radius:3px;'
        'font-weight:700;">DET</span> Deterministic (state machine)</span>'
        '<span><span style="background:#7c3aed;color:white;padding:1px 6px;border-radius:3px;'
        'font-weight:700;">AI</span> Ollama fallback</span>'
        '</div>'
    )
    return f"""
    <div class="section">
      <h2>Conversation Transcript ({len(turns)} turns)</h2>
      {legend}
      <div class="chat">{''.join(bubbles)}</div>
    </div>
"""


def capture_screenshots(screenshot_dir: str) -> dict:
    """Read screenshot files from disk into {stem: base64_str}.

    Call this at the END of each scenario (before the directory is cleared for
    the next scenario) and store the result in the scenario result dict under
    the key ``"screenshots"``.  ``_build_screenshots`` then works from the
    in-memory dict so that a shared screenshot directory does not cause every
    scenario block to show the same (last-scenario) images.
    """
    captured = {}
    for stem, _caption in SCREENSHOT_CAPTIONS:
        path = os.path.join(screenshot_dir, f"{stem}.png")
        if not os.path.isfile(path):
            continue
        try:
            captured[stem] = _img_to_base64(path)
        except Exception:
            pass
    return captured


def _build_screenshots(screenshots: dict) -> str:
    """Render the Screenshots section from a pre-captured {stem: base64} dict."""
    cards = []
    for stem, caption in SCREENSHOT_CAPTIONS:
        b64 = screenshots.get(stem)
        if not b64:
            continue
        cards.append(f"""
        <div class="screenshot-card">
          <img src="data:image/png;base64,{b64}" alt="{_esc(caption)}">
          <div class="screenshot-caption">{_esc(caption)}</div>
        </div>""")
    if not cards:
        return ""
    return f"""
    <div class="section">
      <h2>Screenshots ({len(cards)})</h2>
      <div class="screenshot-grid">{''.join(cards)}</div>
    </div>
"""


def _build_summary_table(suite_results: list) -> str:
    """Summary table shown at the top of a multi-scenario report."""
    rows = []
    for r in suite_results:
        sc_pass = r["results"].get("passed", False)
        score   = r["results"].get("score", 0)
        matched = r["results"].get("matched_items", [])
        missing = r["results"].get("missing_items", [])
        dur     = _duration_str(r["start_time"], r["end_time"])

        status_cell = (
            '<span style="color:#22c55e;font-weight:700;">PASS</span>'
            if sc_pass else
            '<span style="color:#ef4444;font-weight:700;">FAIL</span>'
        )
        score_color = "#22c55e" if score >= 80 else "#f97316" if score >= 50 else "#ef4444"
        missing_cell = (
            " | ".join(f'<span style="color:#ef4444;">{_esc(i)}</span>' for i in missing)
            if missing else '<span style="color:#94a3b8;">—</span>'
        )
        rows.append(f"""
        <tr style="background:{'#f0fdf4' if sc_pass else '#fef2f2'}">
          <td style="font-weight:600;">{_esc(r.get('name','—'))}</td>
          <td style="text-align:center;">{status_cell}</td>
          <td style="text-align:center;color:{score_color};font-weight:700;">{score}/100</td>
          <td>{', '.join(_esc(i) for i in matched) or '—'}</td>
          <td>{missing_cell}</td>
          <td style="color:#64748b;">{_esc(dur)}</td>
        </tr>""")

    return f"""
    <div class="section">
      <h2>Suite Summary</h2>
      <table class="summary-table">
        <thead>
          <tr>
            <th>Scenario</th>
            <th style="text-align:center;">Status</th>
            <th style="text-align:center;">Score</th>
            <th>Matched Items</th>
            <th>Missing Items</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
"""


def _build_scenario_block(result: dict, index: int, total: int, show_images: bool) -> str:
    """Full detail block for one scenario inside a multi-scenario report."""
    name    = result.get("name", f"Scenario {index}")
    passed  = result["results"].get("passed", False)
    dur     = _duration_str(result["start_time"], result["end_time"])
    color   = "#22c55e" if passed else "#ef4444"
    icon    = "✅" if passed else "❌"

    inner = "".join([
        _build_config(result["metadata"]),
        _build_phases(result["phase_statuses"]),
        _build_monitor(result.get("monitor_findings") or {}),
        _build_verification(result["results"]),
        _build_conversation(result.get("log_file") or ""),
        _build_screenshots(
            result.get("screenshots") or capture_screenshots(result.get("screenshot_dir", ""))
        ) if show_images else "",
    ])

    return f"""
    <div class="scenario-block" style="border-color:{color}40;">
      <div class="scenario-header" style="background:{color}10;border-bottom:1px solid {color}30;">
        <h2 style="color:{color};">{icon} Scenario {index}/{total}: {_esc(name)}</h2>
        <span class="dur">{_esc(dur)}</span>
      </div>
      {inner}
    </div>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(
    suite_results: list,
    suite_start: datetime,
    suite_end: datetime,
    show_images: bool = True,
) -> str:
    """
    Generate a single self-contained HTML report for one or more scenarios.

    Each result dict must contain:
        name           str
        results        dict  (passed, score, matched/missing/extra_items, overview)
        phase_statuses dict  (navigation, conversation, verification)
        metadata       dict  (persona, scenario, mic, session_id, start_time, end_time)
        log_file       str | None
        screenshot_dir str
        start_time     datetime
        end_time       datetime

    Args:
        suite_results: list of result dicts (length 1 = single run, >1 = suite)
        suite_start:   datetime the overall run started
        suite_end:     datetime the overall run finished
        show_images:   embed screenshots as base64

    Returns:
        Absolute path to the generated HTML file (inside reports/).
    """
    total  = len(suite_results)
    passed = sum(1 for r in suite_results if r["results"].get("passed"))

    if total == 1:
        # ── Single scenario — compact layout, no summary table ──────────────
        r     = suite_results[0]
        score = r["results"].get("score", 0)
        body  = "\n".join([
            _build_header(
                "Voice Ordering Test Report",
                r["results"].get("passed", False),
                score,
                r["start_time"],
                r["end_time"],
            ),
            _build_config(r["metadata"]),
            _build_phases(r["phase_statuses"]),
            _build_monitor(r.get("monitor_findings") or {}),
            _build_verification(r["results"]),
            _build_conversation(r.get("log_file") or ""),
            _build_screenshots(
                r.get("screenshots") or capture_screenshots(r.get("screenshot_dir", ""))
            ) if show_images else "",
        ])
        title = "Voice Order Test Report"

    else:
        # ── Multi-scenario suite — header + summary table + scenario blocks ─
        overall_score = int(sum(r["results"].get("score", 0) for r in suite_results) / total)
        body = "\n".join([
            _build_suite_header(suite_results, suite_start, suite_end),
            _build_summary_table(suite_results),
            *[
                _build_scenario_block(r, i + 1, total, show_images)
                for i, r in enumerate(suite_results)
            ],
        ])
        title = f"Voice Order Suite — {passed}/{total} passed"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_esc(title)}</title>
  {_build_styles()}
</head>
<body>
  {body}
  <div style="text-align:center;padding:24px 0 32px;color:#94a3b8;font-size:0.8rem;">
    Generated by pizza-voice-test &nbsp;|&nbsp;
    {suite_end.strftime('%Y-%m-%d %H:%M:%S')}
  </div>
</body>
</html>"""

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    ts     = suite_end.strftime("%Y%m%d_%H%M%S")
    if total > 1:
        prefix = "suite"
        slug   = ""
    else:
        scenario_name = suite_results[0].get("name", "")
        slug = "_" + re.sub(r"[^a-z0-9]+", "_", scenario_name.lower()).strip("_") if scenario_name else ""
        prefix = "report"
    path   = reports_dir / f"{prefix}{slug}_{ts}.html"
    path.write_text(html, encoding="utf-8")
    return str(path.resolve())
