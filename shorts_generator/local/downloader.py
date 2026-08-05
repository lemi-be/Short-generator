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
    """Map our '720' / '1080' shorthand to a yt-dlp format selector."""
    try:
        height = int(fmt)
    except ValueError:
        height = 720
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"best[height<={height}][ext=mp4]/best"
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


def _existing_download(out_dir: str, video_id: str) -> Optional[str]:
    """Return a cached download path if we already have this YouTube id."""
    for ext in (".mp4", ".mkv", ".webm"):
        candidate = os.path.join(out_dir, f"source_{video_id}{ext}")
        if os.path.exists(candidate):
            return candidate
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
        return p


def download_youtube_local(video_url: str, fmt: str = "720", out_dir: Optional[str] = None) -> str:
    """Download a remote URL or return a local file path unchanged."""
    local_path = _resolve_local_path(video_url)
    if local_path:
        print(f"[download/local] using local file: {local_path}", flush=True)
        return local_path

    yt_dlp = _import_ytdlp()
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    video_id = _extract_youtube_video_id(video_url)
    if video_id:
        cached = _existing_download(out_dir, video_id)
        if cached:
            print(f"[download/local] reusing cached download: {cached}", flush=True)
            return cached

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

    ydl_opts = {
        "format": _format_for(fmt),
        "outtmpl": os.path.join(out_dir, "source_%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [_hook],
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 10,
        "noplaylist": True,
    }

    AUTH_HINTS = (
        "sign in to confirm",
        "sign in",
        "requires authentication",
        "login",
        "to confirm you're not a bot",
        "bot",
        "HTTP Error 403",
        "this video is only available",
        "isn't available",
        "restricted",
    )

    def _is_auth_error(exc: BaseException) -> bool:
        msg = str(exc).lower()
        return any(hint in msg for hint in AUTH_HINTS)

    def _download():
        return _download_with_cookies(ydl_opts, video_url)

    from .cookies import find_manual_cookies

    try:
        path = _download()
    except Exception as exc:
        if not _is_auth_error(exc):
            # Not an auth problem — surface the real cause instead of
            # masking it behind a misleading "authentication" message.
            raise RuntimeError(
                f"Download failed: {exc}\n"
                "This looks like a network or format issue, not an auth "
                "problem. Check your connection and try again."
            ) from exc

        print(f"  [download] auth/bot detection: {exc}", flush=True)
        # 1) A manually exported cookies.txt in the project root is the
        #    friendliest option — it never touches the user's browser.
        manual = find_manual_cookies()
        if manual:
            print(f"  [download] using manual cookies: {manual}", flush=True)
            cookies_ydl = dict(ydl_opts, cookiefile=manual)
            try:
                path = _download_with_cookies(cookies_ydl, video_url)
            except Exception:
                print("  [download] manual cookies.txt failed.", flush=True)
                raise
        else:
            print("  [download] YouTube bot detection triggered, trying browser cookies...", flush=True)
            from .cookies import try_browser_cookies
            cookies_path = try_browser_cookies(video_url)
            if cookies_path:
                ydl_opts["cookiefile"] = cookies_path
                path = _download()
            else:
                raise RuntimeError(
                    "YouTube requires authentication. Either:\n"
                    "  1. Export your cookies and drop 'cookies.txt' in the project root:\n"
                    "       yt-dlp --cookies cookies.txt --skip-download <video-url>\n"
                    "     (log into YouTube in a browser first, then re-run the command)\n"
                    "  2. Or close Chrome and retry (we'll pull cookies from it)."
                )
    finally:
        if not progress._done:
            progress.finish("download complete")

    print(f"[download/local] ready: {path}", flush=True)
    return path
