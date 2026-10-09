"""Local YouTube download via yt-dlp.

Returns a local mp4 path so the rest of the local pipeline can read it
directly off disk.
"""
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from typing import Optional

from ..config import LOCAL_OUTPUT_DIR
from ..progress import Progress


def _import_ytdlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e
    return yt_dlp


def _format_for(fmt: str) -> str:
    """Map our '720' / '1080' / 'best' shorthand to a yt-dlp format selector."""
    if fmt == "best":
        return "bestvideo+bestaudio/best"
    try:
        height = int(fmt)
    except ValueError:
        height = 1080
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}][ext=mp4]/"
        f"best[height<={height}]/"
        f"best"
    )


def _extract_youtube_video_id(source: str) -> Optional[str]:
    """Best-effort extraction of a YouTube video id from a URL."""
    parsed = urlparse(source)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    if host in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.lstrip("/").split("/", 1)[0]
        return video_id or None

    if "youtube.com" in host:
        if parsed.path.startswith("/watch"):
            qs = parse_qs(parsed.query)
            video_id = qs.get("v", [""])[0]
            return video_id or None
        match = re.search(r"/(?:shorts|embed|live)/([^/?#&]+)", parsed.path)
        if match:
            return match.group(1)

    return None


def _resolve_local_path(source: str) -> Optional[str]:
    """Return a local filesystem path if the input already points at one."""
    parsed = urlparse(source)
    if parsed.scheme == "file":
        raw_path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            raw_path = f"//{parsed.netloc}{raw_path}"
        candidate = Path(raw_path).expanduser()
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
        raise RuntimeError(f"Local file URL does not exist: {source}")

    if parsed.scheme in ("http", "https"):
        return None

    candidate = Path(source).expanduser()
    if candidate.exists() and candidate.is_file():
        return str(candidate.resolve())

    if any(sep in source for sep in (os.sep, "/")) or source.startswith("~") or source.startswith("."):
        raise RuntimeError(f"Local file path does not exist: {source}")

    return None


def _existing_download(out_dir: str, video_id: str, min_height: Optional[int] = None) -> Optional[str]:
    """Return a cached download path if we already have this YouTube id and it satisfies resolution."""
    import cv2
    for ext in (".mp4", ".mkv", ".webm"):
        candidate = os.path.join(out_dir, f"source_{video_id}{ext}")
        if os.path.exists(candidate):
            if min_height is not None and min_height > 720:
                try:
                    cap = cv2.VideoCapture(candidate)
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
                    if h > 0 and h < min_height:
                        print(f"[download/local] cached source is {h}p, but {min_height}p was requested. Upgrading download...", flush=True)
                        continue
                except Exception:
                    pass
            return candidate
    return None


def _write_title_sidecar(p: str, info: dict) -> None:
    """Persist the YouTube title next to the download so later stages can name
    the episode after the video without another network call."""
    title = info.get("title")
    if not title:
        return
    try:
        sidecar = os.path.splitext(p)[0] + ".title"
        with open(sidecar, "w", encoding="utf-8") as f:
            f.write(title)
    except OSError:
        pass


def _parse_cookie_file(cookies_path: str) -> Optional[str]:
    """Read a cookies.txt file and return its resolved path if valid."""
    try:
        p = Path(cookies_path)
        if p.is_file() and p.suffix == ".txt" and p.read_text(encoding="utf-8").strip():
            return str(p.resolve())
    except (OSError, ValueError):
        pass
    return None


def _download_with_cookies(ydl_opts: dict, video_url: str) -> str:
    ytdlp = _import_ytdlp()
    with ytdlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        p = ydl.prepare_filename(info)
        if not os.path.exists(p):
            stem, _ = os.path.splitext(p)
            for ext in (".mp4", ".mkv", ".webm"):
                if os.path.exists(stem + ext):
                    p = stem + ext
                    break
        _write_title_sidecar(p, info)
        return p


# Substrings that indicate YouTube sign-in / bot-detection / restriction.
# Kept lowercase because we compare against a lowercased exception message.
_AUTH_HINTS = (
    "sign in to confirm",
    "sign in",
    "requires authentication",
    "login",
    "to confirm you're not a bot",
    "bot",
    "http error 403",
    "403 forbidden",
    "this video is only available",
    "isn't available",
    "restricted",
    "unable to download video data",
)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences yt-dlp embeds in error output."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _is_auth_error(exc: BaseException) -> bool:
    """True when the exception is a YouTube auth/bot-detection issue.

    yt-dlp wraps errors as `DownloadError` whose message includes ANSI
    colour codes and the "ERROR:" prefix, so we strip ANSI and lowercase
    BOTH sides before substring matching.
    """
    msg = _strip_ansi(str(exc)).lower()
    return any(hint in msg for hint in _AUTH_HINTS)


import shutil


def _find_node_path() -> Optional[str]:
    """Locate the Node.js executable on the system."""
    p = shutil.which("node")
    if p and os.path.exists(p):
        return str(Path(p).resolve())
    for candidate in [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\node\node.exe"),
        os.path.expandvars(r"%APPDATA%\npm\node.cmd"),
    ]:
        if os.path.exists(candidate):
            return str(Path(candidate).resolve())
    return None


def find_manual_cookies() -> Optional[str]:
    """Look for a manually exported cookies.txt in the project root or output dir."""
    candidates = [
        Path("cookies.txt"),
        Path(".cookies"),
        Path(__file__).resolve().parent.parent.parent / "cookies.txt",
        Path(LOCAL_OUTPUT_DIR) / "cookies.txt",
    ]
    for c in candidates:
        if c.is_file():
            try:
                return str(c.resolve())
            except OSError:
                pass
    return None


# A realistic Chrome UA — yt-dlp's default sometimes trips YouTube's 403.
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Fallback player clients: the default `android`/`web` clients are the ones
# most often 403'd. `tv` and `web_embedded` frequently still work without
# cookies when YouTube is enforcing bot checks on the standard clients.
# `web_embedded` exposes full DASH formats (incl. 720p mp4) and works with
# PO tokens when Node/Deno is available, without needing cookies.
_YOUTUBE_EXTRACTOR_ARGS = (
    "youtube:player_client=tv,web_embedded"
)


def _make_ydl_opts(out_dir: str, fmt: str, hook=None, cookiefile: Optional[str] = None) -> dict:
    node_path = _find_node_path()
    js_runtimes = {"node": {"path": node_path} if node_path else {}}
    opts = {
        "format": _format_for(fmt),
        "outtmpl": os.path.join(out_dir, "source_%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 10,
        "noplaylist": True,
        "http_headers": {"User-Agent": _CHROME_UA},
        "extractor_args": {"youtube": {"player_client": ["tv", "web_embedded", "web"]}},
        "remote_components": ["ejs:github"],
        "js_runtimes": js_runtimes,
    }
    if hook is not None:
        opts["progress_hooks"] = [hook]
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return opts


def download_youtube_local(
    video_url: str,
    fmt: str = "1080",
    cookies_path: Optional[str] = None,
    force: bool = False,
) -> str:
    """Download a remote URL or return a local file path unchanged.

    Authentication fallback chain (in order):
      1. Explicit `cookies_path` argument (CLI --cookies / web UI).
      2. A `cookies.txt` in the project root.
      3. Browser cookie extraction (Chrome/Edge/Firefox/Brave/Opera).
    """
    local_path = _resolve_local_path(video_url)
    if local_path:
        print(f"[download/local] using local file: {local_path}", flush=True)
        return local_path

    yt_dlp = _import_ytdlp()
    out_dir = LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    video_id = _extract_youtube_video_id(video_url)
    if video_id and not force:
        try:
            req_h = int(fmt)
        except ValueError:
            req_h = 1080 if fmt != "720" else 720
        cached = _existing_download(out_dir, video_id, min_height=req_h)
        if cached:
            print(f"[download/local] reusing cached download: {cached}", flush=True)
            return cached

    # Pre-resolve an explicit cookies file so the first attempt already
    # carries authentication (avoids a wasted 403 round-trip).
    explicit_cookies = None
    if cookies_path:
        explicit_cookies = _parse_cookie_file(cookies_path)
        if explicit_cookies:
            print(f"[download/local] using specified cookiefile: {explicit_cookies}", flush=True)
        else:
            print(f"[download/local] cookiefile not found or invalid: {cookies_path}", flush=True)

    print(f"[download/local] {video_url} @ {fmt}p -> {out_dir}/", flush=True)
    progress = Progress("Downloading video", total=None)
    progress.__enter__()

    def _hook(d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes")
            if total and downloaded is not None:
                if progress.total is None:
                    progress.set_total(total)
                progress.update(downloaded)
        elif status == "finished":
            progress.finish("download complete, finalizing")

    def _attempt(cookiefile: Optional[str]) -> Optional[str]:
        """Try the download once; return the path or None if auth-blocked."""
        opts = _make_ydl_opts(out_dir, fmt, hook=_hook, cookiefile=cookiefile)
        try:
            return _download_with_cookies(opts, video_url)
        except Exception as exc:
            if _is_auth_error(exc):
                print(f"  [download] auth/bot detection (cookiefile={cookiefile!r}): {exc}", flush=True)
                return None
            # Not an auth problem — surface the real cause instead of
            # masking it behind a misleading "authentication" message.
            raise RuntimeError(
                f"Download failed: {_strip_ansi(str(exc))}\n"
                "This looks like a network or format issue, not an auth "
                "problem. Check your connection and try again."
            ) from exc

    try:
        # 1) Explicit cookies file (if provided and valid)
        path = _attempt(explicit_cookies)
        if path:
            progress.finish("download complete")
            print(f"[download/local] ready: {path}", flush=True)
            return path

        # 2) Manual cookies.txt in project root
        manual = find_manual_cookies()
        if manual:
            print(f"  [download] using manual cookies: {manual}", flush=True)
            path = _attempt(manual)
            if path:
                progress.finish("download complete")
                print(f"[download/local] ready: {path}", flush=True)
                return path

        # 3) Browser cookie extraction
        print("  [download] trying browser cookies...", flush=True)
        from .cookies import try_browser_cookies
        browser_cookies = try_browser_cookies(video_url)
        if browser_cookies:
            path = _attempt(browser_cookies)
            if path:
                progress.finish("download complete")
                print(f"[download/local] ready: {path}", flush=True)
                return path

        # 4) All fallbacks exhausted
        raise RuntimeError(
            "YouTube blocked the download (403 Forbidden). Troubleshooting steps:\n"
            "  1. Node.js and EJS challenge solvers are enabled by default to solve player JS challenges.\n"
            "  2. If the video is age-gated, region-locked, or requires sign-in:\n"
            "     - In the WebUI: Click 'YouTube 403 / Age-Gate bypass (Optional cookies.txt)' in the Add Episode form and upload your exported cookies.txt file.\n"
            "     - In the CLI: Pass --cookies cookies.txt or place cookies.txt in the project root.\n"
            "  3. To export cookies: Use the free 'Get cookies.txt LOCALLY' extension in Chrome/Edge/Firefox while logged into YouTube."
        )
    finally:
        if not progress._done:
            progress.finish("download complete")