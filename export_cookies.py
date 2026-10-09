"""Export browser cookies to cookies.txt so yt-dlp can download YouTube videos.

IMPORTANT: Most downloads no longer need cookies. The pipeline now uses
Node.js to solve YouTube's JS challenges plus a PO-token provider, which
gets past the 403 without any cookies. Only export cookies if the download
still reports a 403.

Usage:
    python export_cookies.py                # try all browsers
    python export_cookies.py chrome         # specific browser: chrome/edge/firefox/brave/opera
    python export_cookies.py chrome --force # auto-close the browser first, then export

Known limitation (Chrome/Edge 127+):
    Google's "App-Bound Encryption" locks the cookie DB key to the running
    Chrome process. yt-dlp cannot decrypt it even when Chrome is closed, and
    the yt-dlp maintainers have stated there is no plan to support it. So
    --force cannot help Chrome/Edge. Use Firefox (no App-Bound encryption),
    or export cookies manually with the "Get cookies.txt LOCALLY" browser
    extension and drop cookies.txt in the project root.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

APP_BOUND_HINTS = (
    "failed to decrypt with dpapi",
    "app-bound",
    "app bound",
    "appbound",
    "unable to decrypt",
    "cryptographic key",
    "enter key",
)


def _ytdlp_cmd(extra: list[str]) -> list[str]:
    python = sys.executable
    try:
        import yt_dlp  # noqa: F401
        return [python, "-m", "yt_dlp", *extra]
    except ImportError:
        return ["yt-dlp", *extra]


def _is_app_bound_error(err: str) -> bool:
    low = err.lower()
    return any(hint in low for hint in APP_BOUND_HINTS)


def _close_browser(name: str) -> None:
    """Terminate a browser process tree on Windows (best-effort)."""
    if sys.platform != "win32":
        print(f"  Closing {name} requires Windows; close it manually and re-run.")
        return
    exe = {"chrome": "chrome.exe", "edge": "msedge.exe",
           "brave": "brave.exe", "opera": "opera.exe", "firefox": "firefox.exe"}.get(name)
    if not exe:
        return
    print(f"  Closing {name} ({exe})...")
    subprocess.run(["taskkill", "/f", "/im", exe, "/t"],
                   capture_output=True, text=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(2)


def _export_from(browser: str, out: Path, force: bool = False) -> bool:
    """Try to export cookies from one browser. Returns True on success."""
    tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()

    cmd = _ytdlp_cmd([
        "--cookies-from-browser", browser,
        "--cookies", str(tmp),
        "--skip-download", "--print", "skip", "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
    ])
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        timeout=90,
    )
    err = (result.stderr or "") + (result.stdout or "")

    if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        tmp.rename(out)
        return True

    if tmp.exists():
        tmp.unlink()

    if _is_app_bound_error(err) and force:
        print(f"  {browser}: App-Bound/DPAPI blocked export, closing browser and retrying...")
        _close_browser(browser)
        return _export_from(browser, out, force=False)

    print(f"  {browser}: failed ({err.strip()[-220:]})")
    if _is_app_bound_error(err):
        print(f"      -> Chrome's cookie DB is encrypted while running.")
        print(f"         Re-run with --force to auto-close the browser first:")
        print(f"         python export_cookies.py {browser} --force")
    return False


def main() -> int:
    force = "--force" in sys.argv
    browsers = [a for a in sys.argv[1:] if not a.startswith("--")] or [
        "chrome", "edge", "firefox", "brave", "opera"]

    out = Path("cookies.txt").resolve()
    if out.exists():
        print(f"  cookies.txt already exists ({out}). Delete it or move it, then re-run.")
        return 1

    print("  Exporting cookies to:", out)
    if not force:
        print("  Tip: close the target browser for the best results.")
        print("      python export_cookies.py chrome --force")
        print("      will close it for you automatically.\n")
    else:
        print("  --force enabled: browsers will be closed before export.\n")

    for browser in browsers:
        print(f"  --- trying {browser} ---")
        if _export_from(browser, out, force=force):
            print(f"  OK: exported {out.stat().st_size} bytes from {browser}")
            print("  You can now run the pipeline:")
            print(f"      python main.py \"<youtube-url>\" --cookies \"{out}\"")
            return 0
        if out.exists():
            return 0

    print("\n  Could not export from any browser.")
    print("  Alternative: install the 'Get cookies.txt LOCALLY' browser")
    print("  extension, log into YouTube, export cookies.txt, then drop it")
    print("  in the project root.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
