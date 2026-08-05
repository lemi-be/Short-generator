"""Try to extract browser cookies for yt-dlp authentication."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def find_manual_cookies() -> str | None:
    """Return a 'cookies.txt' in the project root if present.

    The user may export cookies manually (yt-dlp --cookies cookies.txt
    --skip-download <url>) and drop the file in the project root. This is
    preferred over interrupting/potentially closing the user's browser.
    """
    candidates = (
        Path.cwd() / "cookies.txt",
        Path(__file__).resolve().parent.parent.parent / "cookies.txt",
    )
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def _ytdlp_cmd(extra: list[str]) -> list[str]:
    """Build a working yt-dlp invocation.

    The bundled venv ships a uv-generated yt-dlp.exe that fails with "uv
    trampoline failed to canonicalize script path", so prefer invoking
    yt-dlp through the Python module (python -m yt_dlp), which is known to
    work. Falls back to a PATH yt-dlp if the module isn't importable from
    the running interpreter.
    """
    python = sys.executable
    try:
        import yt_dlp  # noqa: F401  (works when run through our venv)
        return [python, "-m", "yt_dlp", *extra]
    except ImportError:
        return ["yt-dlp", *extra]


def try_browser_cookies(url: str) -> str | None:
    """Try to extract cookies from installed browsers to a temp file."""
    browsers = ["chrome", "edge", "firefox", "brave", "opera"]
    warned = False

    for browser in browsers:
        fd, cookies_path = tempfile.mkstemp(suffix=".txt", prefix=f"cookies_{browser}_")
        os.close(fd)
        success = False
        try:
            cmd = _ytdlp_cmd([
                "--cookies-from-browser", browser,
                "--cookies", cookies_path,
                "--skip-download", "--print", "skip", url,
            ])
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                if os.path.getsize(cookies_path) > 0:
                    print(f"  [cookies] extracted from {browser}")
                    success = True
                    return cookies_path
            err = (result.stderr or "") + (result.stdout or "")
            if ("Could not copy" in err or "not likely to work" in err
                    or "App-Bound" in err or "Enter key" in err) \
               and browser in ("chrome", "edge") and not warned:
                print("  [cookies] Your browser's cookie DB is locked or encrypted.", flush=True)
                print("  [cookies] Close the browser and retry, or use a cookies.txt file.", flush=True)
                warned = True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        finally:
            if not success:
                try:
                    if os.path.exists(cookies_path):
                        os.remove(cookies_path)
                except OSError:
                    pass

    return None
