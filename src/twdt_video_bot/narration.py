"""ElevenLabs narration — generates TTS audio for the trimmed forum post.

Uses the standard /v1/text-to-speech/{voice_id} endpoint (not Voice Design)
because we have a fixed voice — Crazy Eddie — and want consistent character
across every weekly recap.

Returns the MP3 bytes and the exact audio duration in seconds so the video
compositor can size clips appropriately.
"""

import os
import re
import subprocess
from pathlib import Path

import requests

# Crazy Eddie — fixed voice for TWDT recaps
DEFAULT_VOICE_ID = "OTMqA7lryJHXgAnPIQYt"
DEFAULT_MODEL = "eleven_multilingual_v2"
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

# Voice settings — tweak for recap tone. Higher stability = less emotional
# variation (more consistent), higher similarity_boost = closer to the source
# voice. These are sensible defaults for sports commentary.
VOICE_SETTINGS = {
    "stability": 0.45,
    "similarity_boost": 0.85,
    "style": 0.35,
    "use_speaker_boost": True,
}


def _api_key() -> str:
    # Look for .env in the repo root, then maigent's .env as a fallback
    for env_path in [
        Path(__file__).parent.parent.parent / ".env",
        Path(__file__).parent.parent.parent.parent / "maigent" / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"\s*ELEVEN_LABS_API_KEY\s*=\s*(.+)", line)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
    key = os.getenv("ELEVEN_LABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVEN_LABS_API_KEY not set in .env")
    return key


def generate_narration(text: str, voice_id: str = DEFAULT_VOICE_ID) -> tuple[bytes, float]:
    """Generate narration audio.

    Returns: (mp3_bytes, duration_seconds)
    """
    if not text.strip():
        raise RuntimeError("No text to narrate.")
    key = _api_key()
    url = API_URL.format(voice_id=voice_id)
    payload = {
        "text": text,
        "model_id": DEFAULT_MODEL,
        "voice_settings": VOICE_SETTINGS,
    }
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=180)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs TTS error {resp.status_code}: {resp.text[:300]}")

    mp3 = resp.content
    duration = _probe_duration(mp3)
    return mp3, duration


def _probe_duration(mp3_bytes: bytes) -> float:
    """Use ffprobe to measure an MP3's duration. ffprobe ships with ffmpeg."""
    # Write the bytes to a temp file because ffprobe doesn't read stdin reliably
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3_bytes)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr[:200]}")
        return float(result.stdout.strip())
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
