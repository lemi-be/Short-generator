"""Local LLM backend — OpenAI or Gemini, selected by LLM_PROVIDER.

Both backends retry transient errors (429, 503, UNAVAILABLE, RESOURCE_EXHAUSTED,
network/timeout) with exponential backoff. The default cap is 4 attempts over
~30s, which is enough to ride out a typical Gemini "high demand" spike.
"""
import time
from typing import Tuple

from ..config import (
    GEMINI_MODEL,
    LLM_PROVIDER,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    require_gemini_key,
    require_openai_key,
)


# Default retry policy for both backends. Tuned for Gemini's "high demand"
# 503s, which typically clear in 5-15 seconds.
MAX_LLM_ATTEMPTS = 4
BASE_BACKOFF_SECONDS = 2.0  # backoff = BASE * 2^(attempt-1) -> 2s, 4s, 8s, 16s


def _is_transient_error(exc: Exception) -> bool:
    """Return True for HTTP statuses and SDK errors that should be retried."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()

    # Google GenAI / OpenAI SDK error names.
    if any(s in name for s in ("unavailable", "resourcelock", "ratelimit", "deadline", "timeout")):
        return True

    # HTTP status code sniffing — works for both SDKs because they embed the
    # status code in the exception message (e.g. "503 UNAVAILABLE").
    for code in ("503", "429", "500", "502", "504"):
        if code in msg:
            return True
    for phrase in (
        "unavailable",
        "resource exhausted",
        "resource_exhausted",
        "high demand",
        "rate limit",
        "rate_limit",
        "temporarily",
        "try again",
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
    ):
        if phrase in msg:
            return True

    return False


def _call_with_retry(fn, label: str) -> str:
    """Run `fn()` with exponential backoff on transient errors."""
    last_err: Exception = RuntimeError("unknown")
    for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if not _is_transient_error(e) or attempt >= MAX_LLM_ATTEMPTS:
                raise
            sleep_for = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(
                f"[llm] {label} transient error on attempt {attempt}/{MAX_LLM_ATTEMPTS}: {e}. "
                f"Retrying in {sleep_for:.0f}s...",
                flush=True,
            )
            time.sleep(sleep_for)
    raise last_err  # unreachable, satisfies type checkers


def call_openai_llm(prompt: str) -> str:
    """OpenAI Chat Completions backend used by --mode local."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = OpenAI(api_key=require_openai_key(), base_url=OPENAI_BASE_URL)

    def _do() -> str:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

    return _call_with_retry(_do, label="openai")


# Free-tier Gemini: 5 requests per minute -> at least 12s between calls.
_GEMINI_MIN_INTERVAL = 12.0
_last_gemini_call: float = 0.0


def call_gemini_llm(prompt: str) -> str:
    """Gemini backend used by --mode local when LLM_PROVIDER=gemini."""
    global _last_gemini_call

    elapsed = time.time() - _last_gemini_call
    if elapsed < _GEMINI_MIN_INTERVAL:
        time.sleep(_GEMINI_MIN_INTERVAL - elapsed)

    try:
        from google import genai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = genai.Client(api_key=require_gemini_key())

    def _do() -> str:
        global _last_gemini_call
        _last_gemini_call = time.time()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "temperature": 0.2,
                "response_mime_type": "application/json",
                "max_output_tokens": 8192,
            },
        )
        return response.text or ""

    return _call_with_retry(_do, label="gemini")


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = (LLM_PROVIDER or "openai").strip().lower()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'openai' or 'gemini'."
    )
