"""
ScenarioMonitor — parallel health monitoring during scenario execution.

Runs two background threads for the lifetime of a scenario:
  - Logcat thread   : captures ADB logcat, flags crash/error lines tagged to the
                      active phase at the time they appeared.
  - Health thread   : polls current Android activity every 5 s; records changes
                      and warns if the app leaves the foreground.

Usage (from run_suite.py):
    monitor = ScenarioMonitor(app_package, driver)
    monitor.start()
    monitor.mark_phase("navigation")
    ...
    monitor.mark_phase("conversation")
    ...
    monitor.stop()
    findings = monitor.get_findings()   # attach to result dict for the report
"""

import subprocess
import threading
import time
from datetime import datetime
from typing import Optional


# Logcat lines containing any of these strings are flagged as errors
_ERROR_PATTERNS = [
    "FATAL EXCEPTION",
    "ANR in",
    "Force finishing activity",
    "java.lang.RuntimeException",
    "java.lang.NullPointerException",
    "java.lang.IllegalStateException",
    "android.os.NetworkOnMainThreadException",
    "E/AndroidRuntime",
    "W/ActivityManager: Force",
]

# Logcat lines to skip even if they match app package (noisy non-issues)
_SKIP_PATTERNS = [
    "GC_",
    "dalvikvm",
    "art     :",
    "Choreographer",
]

_HEALTH_INTERVAL = 5   # seconds between activity polls


def _now_str() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class ScenarioMonitor:
    """Monitors app health in parallel during a test scenario."""

    def __init__(self, app_package: str, driver=None):
        """
        Args:
            app_package: Android package name (e.g. 'com.acmepizza.android.debug.qa')
            driver:      AppiumDriver instance for activity polling (optional).
                         If None the health thread is skipped.
        """
        self.app_package = app_package
        self._driver = driver

        # Shared state — all writes protected by _lock
        self._lock = threading.Lock()
        self._current_phase: str = "pre-start"
        self._timeline: list[dict] = []      # {ts, event, phase}
        self._errors: list[dict] = []        # {ts, phase, line}
        self._activity_log: list[dict] = []  # {ts, activity, phase}

        self._stop_event = threading.Event()
        self._logcat_thread: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def start(self):
        """Start background monitoring threads."""
        # Clear stale logcat buffer so we only see lines from this scenario
        try:
            subprocess.run(["adb", "logcat", "-c"], capture_output=True, timeout=5)
        except Exception:
            pass

        self._stop_event.clear()

        self._logcat_thread = threading.Thread(
            target=self._logcat_reader, daemon=True, name="ScenMonitor-logcat"
        )
        self._logcat_thread.start()

        if self._driver is not None:
            self._health_thread = threading.Thread(
                target=self._health_checker, daemon=True, name="ScenMonitor-health"
            )
            self._health_thread.start()

        self._record_event("Monitor started")

    def mark_phase(self, phase: str):
        """Record a phase boundary. Call before each major block."""
        with self._lock:
            self._current_phase = phase
        self._record_event(f"Phase: {phase}")

    def stop(self):
        """Stop background threads and finalise findings."""
        self._record_event("Monitor stopped")
        self._stop_event.set()
        if self._logcat_thread:
            self._logcat_thread.join(timeout=4)
        if self._health_thread:
            self._health_thread.join(timeout=4)

    def get_findings(self) -> dict:
        """Return a snapshot of everything captured so far."""
        with self._lock:
            return {
                "timeline":       list(self._timeline),
                "errors":         list(self._errors),
                "activity_log":   list(self._activity_log),
                "total_errors":   len(self._errors),
            }

    # ─────────────────────────────────────────────────────────────────────
    # Background threads
    # ─────────────────────────────────────────────────────────────────────

    def _logcat_reader(self):
        try:
            proc = subprocess.Popen(
                ["adb", "logcat", "-v", "time"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            for raw_line in proc.stdout:
                if self._stop_event.is_set():
                    proc.terminate()
                    break

                line = raw_line.rstrip()

                # Skip noisy lines
                if any(skip in line for skip in _SKIP_PATTERNS):
                    continue

                # Only keep lines relevant to our app or known error patterns
                is_app_line = self.app_package in line
                is_error = any(p.lower() in line.lower() for p in _ERROR_PATTERNS)

                if not (is_app_line or is_error):
                    continue

                with self._lock:
                    phase = self._current_phase

                if is_error:
                    with self._lock:
                        self._errors.append({
                            "ts":    _now_str(),
                            "phase": phase,
                            "line":  line,
                        })

        except Exception:
            pass  # monitoring must never crash the test

    def _health_checker(self):
        prev_activity: Optional[str] = None
        while not self._stop_event.wait(timeout=_HEALTH_INTERVAL):
            try:
                activity = self._driver.driver.current_activity
                package  = self._driver.driver.current_package

                with self._lock:
                    phase = self._current_phase

                full = f"{package}/{activity}"

                if full != prev_activity:
                    with self._lock:
                        self._activity_log.append({
                            "ts":       _now_str(),
                            "activity": full,
                            "phase":    phase,
                        })
                    prev_activity = full

                # Warn if app has left the foreground
                if package and self.app_package not in package:
                    self._record_event(
                        f"WARNING: App not in foreground — current package: {package}",
                        is_warning=True,
                    )

            except Exception:
                pass  # driver may be closing — ignore

    # ─────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────

    def _record_event(self, event: str, is_warning: bool = False):
        with self._lock:
            phase = self._current_phase
            self._timeline.append({
                "ts":      _now_str(),
                "event":   event,
                "phase":   phase,
                "warning": is_warning,
            })
