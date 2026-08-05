"""Lightweight, dependency-free progress indicator.

Used by the local pipeline to show what's happening during a multi-minute
run. Stages:

  1. Downloading    (yt-dlp)         - has a percent
  2. Transcribing   (faster-whisper) - emits one segment at a time, no percent
  3. Ranking highlights (LLM)        - per-chunk progress + per-call retry
  4. Clipping       (ffmpeg + cv2)  - per-frame count

A small `ticker` background thread drives an in-place spinner + elapsed time
for stages that don't emit a percentage. Stops cleanly on exit.

This module is imported by the local downloader, transcriber, llm, and
clipper. It's safe to import but does nothing fancy if `sys.stdout` isn't a
TTY (non-interactive runs get the same `[stage] message` lines they always
did).
"""
import os
import sys
import threading
import time
from typing import Optional


_IS_TTY = sys.stdout.isatty() and os.environ.get("PROGRESS_FORCE") != "0"
_DISABLE = os.environ.get("PROGRESS_OFF") == "1"

# Detect UTF-8 capable stdout (Windows terminals often are not). If not, fall
# back to ASCII so we never crash on encoding.
def _stdout_supports_unicode() -> bool:
    enc = (sys.stdout.encoding or "").lower()
    return "utf" in enc or "utf8" in enc


_USE_ASCII = not _stdout_supports_unicode()

_SPINNER = ["|", "/", "-", "\\"] if _USE_ASCII else ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_BAR = "#" if _USE_ASCII else "█"
_BAR_EMPTY = "-" if _USE_ASCII else "░"
_CHECK = "OK" if _USE_ASCII else "\u2713"


def _format_eta(seconds: float) -> str:
    if seconds < 0 or seconds == float("inf"):
        return "--:--"
    s = int(seconds)
    m, s = divmod(s, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def _format_elapsed(seconds: float) -> str:
    s = int(seconds)
    m, s = divmod(s, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


class Progress:
    """Stage-aware progress line printer.

    Use either as a context manager (for stages with a known total) or by
    calling `update()` repeatedly (for indeterminate stages).

        with Progress("Transcribing", total=duration_seconds) as p:
            for seg in segments:
                p.update(seg.end)
    """

    def __init__(
        self,
        label: str,
        total: Optional[float] = None,
        unit: str = "",
        stage: Optional[str] = None,
    ) -> None:
        self.label = label
        self.total = total
        self.unit = unit
        self.stage = stage  # e.g. "2/4" — printed at the start
        self._start = time.time()
        self._last_print = 0.0
        self._current = 0.0
        self._done = False
        self._spinner_idx = 0
        self._stop_ticker = threading.Event()
        self._ticker: Optional[threading.Thread] = None

    def __enter__(self) -> "Progress":
        if self.stage:
            print(f"\n{self.stage}  {self.label}", flush=True)
        else:
            print(f"\n{self.label}", flush=True)
        if _IS_TTY and not _DISABLE and self.total is None:
            self._ticker = threading.Thread(target=self._ticker_loop, daemon=True)
            self._ticker.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_val is not None:
            self.fail(str(exc_val))
        else:
            self.finish()

    def _ticker_loop(self) -> None:
        while not self._stop_ticker.is_set():
            self._print_line(force=False)
            time.sleep(0.2)

    def _print_line(self, force: bool = False) -> None:
        if not _IS_TTY or _DISABLE:
            return
        now = time.time()
        if not force and now - self._last_print < 0.2:
            return
        self._last_print = now

        elapsed = now - self._start
        spinner = _SPINNER[self._spinner_idx % len(_SPINNER)]
        self._spinner_idx += 1

        if self.total and self.total > 0:
            pct = max(0.0, min(100.0, (self._current / self.total) * 100.0))
            eta = (elapsed / self._current * (self.total - self._current)) if self._current > 0 else 0
            bar_width = 20
            filled = int(bar_width * pct / 100)
            bar = _BAR * filled + _BAR_EMPTY * (bar_width - filled)
            line = (
                f"\r  {spinner} {self.label}  [{bar}] {pct:5.1f}%  "
                f"({_format_elapsed(elapsed)} < {_format_eta(eta)})   "
            )
        else:
            line = (
                f"\r  {spinner} {self.label}  ({_format_elapsed(elapsed)})   "
            )
        sys.stdout.write(line)
        sys.stdout.flush()

    def update(self, current: float) -> None:
        self._current = max(self._current, float(current))
        if self.total and self.total > 0:
            self._print_line(force=True)
        # Else: ticker thread is updating for us.

    def set_total(self, total: float) -> None:
        self.total = float(total)

    def finish(self, message: Optional[str] = None) -> None:
        if self._done:
            return
        self._done = True
        self._stop_ticker.set()
        if self._ticker is not None:
            self._ticker.join(timeout=0.5)

        elapsed = time.time() - self._start
        if _IS_TTY and not _DISABLE:
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()

        if message:
            print(f"  [{_CHECK}] {message} ({_format_elapsed(elapsed)})", flush=True)
        else:
            print(f"  [{_CHECK}] {self.label} done ({_format_elapsed(elapsed)})", flush=True)

    def fail(self, error: str) -> None:
        """Mark as failed. Called from __exit__ when the context raises."""
        if self._done:
            return
        self._done = True
        self._stop_ticker.set()
        if self._ticker is not None:
            self._ticker.join(timeout=0.5)

        elapsed = time.time() - self._start
        if _IS_TTY and not _DISABLE:
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()

        print(f"  [!] {self.label}: {error} ({_format_elapsed(elapsed)})", flush=True)


def stage(stage_num: int, total_stages: int, label: str) -> None:
    """Print a stage header, e.g. `stage(2, 4, "Transcribing")`."""
    print(f"\n[{stage_num}/{total_stages}] {label}", flush=True)
