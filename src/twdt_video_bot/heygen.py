"""HeyGen avatar video generation — talking-head narrator for TWDT recaps.

Sends the trimmed recap text to HeyGen's v2 video API, which generates
a talking avatar with lip-synced audio via ElevenLabs (Crazy Eddie voice).
The returned MP4 is overlaid onto the bottom-left corner of the recap video.

Pipeline:
  1. POST /v2/video/generate with avatar_id + voice config + script text
  2. Poll /v1/video_status.get?video_id=X until status="completed"
  3. Download the finished MP4 from the returned video_url
"""

import os
import re
import time
from pathlib import Path

import requests

API_GENERATE = "https://api.heygen.com/v2/video/generate"
API_STATUS = "https://api.heygen.com/v1/video_status.get"

# Crazy Eddie — HeyGen's internal voice ID (different from the ElevenLabs ID).
# HeyGen maintains its own voice library; even if the voice originally came
# from ElevenLabs, HeyGen assigns its own ID.
HEYGEN_VOICE_ID = "32f7653b4e8f4e33b9369263e9f9a434"


def _load_env():
    """Read env vars, checking both twdt-video-bot and maigent .env files."""
    for env_path in [
        Path(__file__).parent.parent.parent / ".env",
        Path(__file__).parent.parent.parent.parent / "maigent" / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"([A-Z_]+)\s*=\s*(.+)", line)
                if m:
                    key, val = m.group(1), m.group(2).strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = val


def _get(var: str) -> str:
    _load_env()
    val = os.getenv(var)
    if not val:
        raise RuntimeError(f"{var} not set in .env")
    return val


def generate_avatar_video(
    script_text: str,
    avatar_id: str = "",
    voice_id: str = HEYGEN_VOICE_ID,
    background_color: str = "#000000",  # black background — blends with game footage
    poll_interval_s: float = 5.0,
    poll_timeout_s: float = 600.0,
) -> bytes:
    """Generate a talking-head avatar video via HeyGen.

    Args:
        script_text: the narration text (already trimmed to <5000 chars)
        avatar_id: HeyGen avatar ID (reads AVATAR_ID from env if empty)
        voice_id: ElevenLabs voice ID
        background_color: hex color for avatar background. #00FF00 (green)
            lets us chroma-key it out if needed, or use as-is for PiP.
        poll_interval_s: seconds between status polls
        poll_timeout_s: max seconds to wait for video completion

    Returns: MP4 video bytes of the talking avatar
    """
    api_key = _get("HEYGEN_API_KEY")
    if not avatar_id:
        avatar_id = _get("AVATAR_ID")

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "video_inputs": [
            {
                "character": {
                    "type": "talking_photo",
                    "talking_photo_id": avatar_id,
                    "scale": 1,
                    "use_avatar_iv_model": True,
                },
                "voice": {
                    "type": "text",
                    "voice_id": voice_id,
                    "input_text": script_text,
                    "speed": 1.5,
                    "pitch": 0,
                },
                "background": {
                    "type": "color",
                    "value": background_color,
                },
            }
        ],
        "dimension": {
            "width": 512,
            "height": 512,
        },
    }

    # Step 1: submit the job
    print(f"  [heygen] submitting avatar video job...", flush=True)
    r = requests.post(API_GENERATE, json=payload, headers=headers, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HeyGen generate error {r.status_code}: {r.text[:300]}")

    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"HeyGen generate error: {data['error']}")
    video_id = data.get("data", {}).get("video_id")
    if not video_id:
        raise RuntimeError(f"HeyGen response missing video_id: {str(data)[:300]}")
    print(f"  [heygen] job submitted: {video_id}", flush=True)

    # Step 2: poll for completion
    deadline = time.time() + poll_timeout_s
    video_url = None
    while time.time() < deadline:
        time.sleep(poll_interval_s)
        sr = requests.get(
            API_STATUS,
            params={"video_id": video_id},
            headers=headers,
            timeout=30,
        )
        if sr.status_code != 200:
            print(f"  [heygen] status poll error {sr.status_code}", flush=True)
            continue
        sdata = sr.json().get("data", {})
        status = sdata.get("status", "")
        print(f"  [heygen] status: {status}", flush=True)
        if status == "completed":
            video_url = sdata.get("video_url")
            break
        if status == "failed":
            error = sdata.get("error", "unknown")
            raise RuntimeError(f"HeyGen video generation failed: {error}")

    if not video_url:
        raise RuntimeError(f"HeyGen video timed out after {poll_timeout_s}s")

    # Step 3: download the finished video
    print(f"  [heygen] downloading avatar video...", flush=True)
    dr = requests.get(video_url, timeout=120)
    if dr.status_code != 200:
        raise RuntimeError(f"HeyGen video download failed: HTTP {dr.status_code}")

    print(f"  [heygen] avatar video: {len(dr.content)} bytes", flush=True)
    return dr.content
