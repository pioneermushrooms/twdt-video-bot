"""End-to-end recap pipeline — ties every module together."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from twdt_video_bot.compose import concat_clips_to_target, mix_narration
from twdt_video_bot.forum import load_post
from twdt_video_bot.narration import DEFAULT_VOICE_ID, generate_narration
from twdt_video_bot.playlist import download_clip, list_playlist
from twdt_video_bot.trim import trim_for_tts

# Clip length sanity bounds. Too short (<8s) = whiplash; too long (>45s) = boring
MIN_CLIP_S = 8.0
MAX_CLIP_S = 45.0
# Cap playlist size so each clip gets enough screen time with typical narrations
MAX_PLAYLIST_ENTRIES = 12
# Each clip starts at this offset (skip intros / loading / warmup)
CLIP_START_OFFSET_S = 15.0


@dataclass
class RecapResult:
    output_path: Path
    narration_chars: int
    narration_duration_s: float
    clip_count: int
    clip_length_s: float
    total_seconds: float


def build_recap(
    post_source: str,
    playlist_url: str,
    output_path: Path,
    cache_dir: Path,
    voice_id: str = DEFAULT_VOICE_ID,
    max_playlist: int = MAX_PLAYLIST_ENTRIES,
    clip_start_offset: float = CLIP_START_OFFSET_S,
    on_progress=None,
) -> RecapResult:
    """Run the full pipeline.

    post_source: URL of a forum thread OR raw text of the post
    playlist_url: YouTube playlist URL
    output_path: final MP4 path
    cache_dir: directory for temporary clips + intermediate video
    """
    started = time.time()
    output_path = Path(output_path)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    def step(msg: str):
        print(f"  [{time.time() - started:6.1f}s] {msg}", flush=True)
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    # Step 1: fetch & trim the post
    step("Fetching forum post")
    raw_text = load_post(post_source)
    step(f"  raw post: {len(raw_text)} chars")

    step("Trimming for TTS (5000 char limit)")
    trimmed = trim_for_tts(raw_text)
    step(f"  trimmed: {len(trimmed)} chars")

    # Step 2: narration
    step("Generating ElevenLabs narration")
    mp3_bytes, narration_duration = generate_narration(trimmed, voice_id=voice_id)
    narration_path = cache_dir / "narration.mp3"
    narration_path.write_bytes(mp3_bytes)
    step(f"  narration: {len(mp3_bytes)} bytes, {narration_duration:.1f}s")

    # Step 3: playlist
    step(f"Listing playlist (capped at {max_playlist})")
    entries = list_playlist(playlist_url, max_entries=max_playlist)
    if not entries:
        raise RuntimeError("Playlist returned no videos.")
    step(f"  {len(entries)} videos in playlist")

    # Step 4: compute per-clip length
    raw_clip_s = narration_duration / len(entries)
    clip_length_s = max(MIN_CLIP_S, min(MAX_CLIP_S, raw_clip_s))
    step(f"  per-clip length: {clip_length_s:.1f}s  (raw {raw_clip_s:.1f}s)")

    # Step 5: download clips
    clip_paths = []
    for i, entry in enumerate(entries, 1):
        step(f"  [{i}/{len(entries)}] downloading clip from {entry.title[:60]}")
        # Don't start past the end of short videos
        start = clip_start_offset
        if entry.duration and start + clip_length_s > entry.duration - 2:
            start = max(0.0, entry.duration - clip_length_s - 2)
        try:
            clip_path = download_clip(
                entry.video_id,
                start_s=start,
                length_s=clip_length_s,
                output_path=cache_dir / f"clip_{i:02d}.mp4",
            )
            clip_paths.append(clip_path)
        except Exception as e:
            step(f"    FAILED: {e}")

    if not clip_paths:
        raise RuntimeError("No clips downloaded successfully.")
    step(f"  got {len(clip_paths)}/{len(entries)} clips")

    # Step 6: concat to single video track
    step("Concatenating clips to 720p")
    intermediate = cache_dir / "concat.mp4"
    concat_clips_to_target(clip_paths, intermediate)

    # Step 7: overlay narration + final encode
    step("Mixing narration onto clips (final encode)")
    mix_narration(intermediate, narration_path, output_path)

    total = time.time() - started
    step(f"Done: {output_path} ({total:.0f}s total)")

    return RecapResult(
        output_path=output_path,
        narration_chars=len(trimmed),
        narration_duration_s=narration_duration,
        clip_count=len(clip_paths),
        clip_length_s=clip_length_s,
        total_seconds=total,
    )
