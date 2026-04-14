"""Source loader — fetches recap text from a URL, local file, or raw string.

Supports:
  - Local .txt files (preferred — just plain text, no parsing needed)
  - Forum thread URLs (vBulletin 5 — legacy, scrapes js-post__content-text div)
  - Raw pasted text
"""

import re
from html import unescape
from pathlib import Path

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 twdt-video-bot/0.1"


def fetch_op_text(url: str, timeout: int = 20) -> str:
    """Fetch a forum thread URL and return the OP's text content.

    Strips all HTML tags, collapses whitespace, unescapes entities.
    Raises RuntimeError if the post body can't be located.
    """
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Forum fetch failed: HTTP {resp.status_code} for {url}")

    html = resp.text
    # The first post body in document order is the OP
    match = re.search(
        r'<div[^>]*class="[^"]*js-post__content-text[^"]*"[^>]*>(.*?)</div>',
        html,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError(
            "Could not locate the OP body on this page. "
            "The forum HTML structure may have changed — check the "
            "js-post__content-text selector in twdt_video_bot/forum.py."
        )

    body_html = match.group(1)
    # Strip all tags
    text = re.sub(r"<[^>]+>", " ", body_html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Unescape &amp; &quot; etc.
    text = unescape(text)
    return text


def load_post(source: str) -> str:
    """Resolve a 'post source' into text.

    Accepts a local file path (.txt), a URL (forum scrape), or raw text.
    """
    # Local file
    p = Path(source)
    if p.suffix in (".txt",) and p.exists():
        return p.read_text(encoding="utf-8").strip()

    # URL
    if source.startswith(("http://", "https://")):
        return fetch_op_text(source)

    return source.strip()
