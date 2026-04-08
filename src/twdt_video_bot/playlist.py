"""YouTube playlist handling via yt-dlp.

Two operations:
  1. list_playlist(url) — fetch metadata (id, title, duration) for every
     video in the playlist without downloading anything
  2. download_clip(video_id, start_s, length_s, output_path) — download
     only the byte range needed for a `length_s` second clip starting at
     `start_s`, then cut it to exactly `length_s` via ffmpeg
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _find_cookies_txt() -> Optional[Path]:
    """Look for a Netscape cookies.txt in standard locations.

    YouTube throttles unauthenticated downloads to ~1 KB/s. Using real
    browser cookies bypasses the throttle. Export cookies with the
    'Get cookies.txt LOCALLY' Chrome extension in Netscape format.
    """
    repo_root = Path(__file__).parent.parent.parent
    for c in [
        repo_root / "cookies.txt",
        Path.home() / ".twdt-video-bot" / "cookies.txt",
    ]:
        if c.exists() and c.stat().st_size > 200:  # skip empty/header-only files
            return c
    return None


def _cookie_args() -> list[str]:
    """Return yt-dlp --cookies args if a cookies.txt is available."""
    path = _find_cookies_txt()
    if path is not None:
        return ["--cookies", str(path)]
    return []


# YouTube's web/tv clients require a JavaScript runtime to solve the n-sig
# challenge. node.js is the most common runtime; explicitly pass it so
# yt-dlp doesn't skip detection when the shell's PATH resolution lags.
_JS_RUNTIME_ARGS = ["--js-runtimes", "node"]


@dataclass
class PlaylistEntry:
    video_id: str
    title: str
    duration: int  # seconds, may be 0 if unavailable

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def list_playlist(playlist_url: str, max_entries: int = 0) -> list[PlaylistEntry]:
    """List videos in a YouTube playlist without downloading.

    Args:
        playlist_url: the full playlist URL
        max_entries: if > 0, cap the returned list to this many entries

    Returns: ordered list of PlaylistEntry
    """
    cmd = [
        sys.executable, "-m", "yt_dlp",
        *_cookie_args(),
        *_JS_RUNTIME_ARGS,
        "--flat-playlist",
        "--print", "%(id)s|%(title)s|%(duration)s",
        playlist_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp playlist fetch failed: {result.stderr[:300]}")

    entries = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        video_id, title, duration_str = parts
        try:
            duration = int(float(duration_str)) if duration_str and duration_str != "NA" else 0
        except ValueError:
            duration = 0
        entries.append(PlaylistEntry(
            video_id=video_id.strip(),
            title=title.strip(),
            duration=duration,
        ))

    if max_entries > 0:
        entries = entries[:max_entries]
    return entries


def download_clip(
    video_id: str,
    start_s: float,
    length_s: float,
    output_path: Path,
) -> Path:
    """Download a clip from a YouTube video.

    Strategy: use yt-dlp's --download-sections to pull only the needed
    time range, which is far less data than the full video. yt-dlp
    will invoke ffmpeg under the hood to cut to exact boundaries.

    Output is always 720p MP4 re-encoded to h264 for consistent concat.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Section download syntax: "*start-end" for a time range in seconds
    end_s = start_s + length_s
    section = f"*{start_s:.2f}-{end_s:.2f}"

    cmd = [
        sys.executable, "-m", "yt_dlp",
        *_cookie_args(),
        *_JS_RUNTIME_ARGS,
        "--download-sections", section,
        "--force-keyframes-at-cuts",  # cleaner cuts at requested boundaries
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "--merge-output-format", "mp4",
        "-o", str(output_path),
        "--no-warnings",
        "--quiet",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(
            f"yt-dlp clip download failed for {video_id}: "
            f"{result.stderr[:300] or result.stdout[:300]}"
        )
    return output_path
