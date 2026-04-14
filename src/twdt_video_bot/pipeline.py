"""End-to-end recap pipeline — ties every module together.

Two modes:
  - Avatar mode (default): HeyGen generates a talking-head avatar video with
    lip-synced ElevenLabs narration. The avatar is overlaid on the bottom-left
    20% of the game clips, and HeyGen's audio is the primary narration track.
  - Audio-only mode (--no-avatar): standalone ElevenLabs narration mixed over
    game clips, no avatar. Faster, cheaper, still sounds good.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from twdt_video_bot.compose import apply_frame, concat_clips_to_target, crop_avatar, mix_narration, overlay_avatar, overlay_credits
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
    avatar: bool


def _probe_duration(path: Path) -> float:
    """Use ffprobe to measure a media file's duration in seconds."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def build_recap(
    post_source: str,
    playlist_url: str,
    output_path: Path,
    cache_dir: Path,
    voice_id: str = DEFAULT_VOICE_ID,
    max_playlist: int = MAX_PLAYLIST_ENTRIES,
    clip_start_offset: float = CLIP_START_OFFSET_S,
    use_avatar: bool = True,
    avatar_file: str = "",
    use_frame: bool = True,
    on_progress=None,
) -> RecapResult:
    """Run the full pipeline.

    post_source: URL of a forum thread OR raw text of the post
    playlist_url: YouTube playlist URL
    output_path: final MP4 path
    cache_dir: directory for temporary clips + intermediate video
    use_avatar: if True, use an avatar overlay (HeyGen API or local file).
                if False, use standalone ElevenLabs narration only.
    avatar_file: path to a pre-rendered avatar MP4 (e.g. downloaded from
                 HeyGen's web UI). Skips the HeyGen API call entirely.
                 Use this to avoid API credit costs — render in the web UI
                 with plan minutes ($0), download, pass the file here.
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

    # ── Step 1: fetch & trim the post ──
    step("Fetching forum post")
    raw_text = load_post(post_source)
    step(f"  raw post: {len(raw_text)} chars")

    step("Trimming for TTS (5000 char limit)")
    trimmed = trim_for_tts(raw_text)
    step(f"  trimmed: {len(trimmed)} chars")

    # ── Step 2: generate narration ──
    # Avatar mode: HeyGen produces a video with lip-synced audio
    # Audio-only mode: standalone ElevenLabs MP3
    avatar_path = None
    narration_path = None
    narration_duration = 0.0

    if use_avatar and avatar_file:
        # Pre-rendered avatar file (from HeyGen web UI — $0, plan minutes)
        raw_avatar = Path(avatar_file)
        if not raw_avatar.exists():
            raise RuntimeError(f"Avatar file not found: {raw_avatar}")
        step(f"Cropping avatar to 800x900 portrait: {raw_avatar.name}")
        avatar_path = cache_dir / "avatar_cropped.mp4"
        crop_avatar(raw_avatar, avatar_path)
        narration_duration = _probe_duration(avatar_path)
        step(f"Using pre-rendered avatar: {avatar_path.name} ({narration_duration:.1f}s)")
    elif use_avatar:
        step("Generating HeyGen avatar video (this takes 2-5 minutes)")
        from twdt_video_bot.heygen import generate_avatar_video
        avatar_bytes = generate_avatar_video(trimmed)
        avatar_path = cache_dir / "avatar.mp4"
        avatar_path.write_bytes(avatar_bytes)
        narration_duration = _probe_duration(avatar_path)
        step(f"  avatar video: {len(avatar_bytes)} bytes, {narration_duration:.1f}s")
    else:
        step("Generating ElevenLabs narration (audio only)")
        mp3_bytes, narration_duration = generate_narration(trimmed, voice_id=voice_id)
        narration_path = cache_dir / "narration.mp3"
        narration_path.write_bytes(mp3_bytes)
        step(f"  narration: {len(mp3_bytes)} bytes, {narration_duration:.1f}s")

    # ── Step 3: playlist ──
    step(f"Listing playlist (capped at {max_playlist})")
    entries = list_playlist(playlist_url, max_entries=max_playlist)
    if not entries:
        raise RuntimeError("Playlist returned no videos.")
    step(f"  {len(entries)} videos in playlist")

    # ── Step 4: compute per-clip length ──
    raw_clip_s = narration_duration / len(entries) if len(entries) > 0 else 30.0
    clip_length_s = max(MIN_CLIP_S, min(MAX_CLIP_S, raw_clip_s))
    step(f"  per-clip length: {clip_length_s:.1f}s  (raw {raw_clip_s:.1f}s)")

    # ── Step 5: download clips ──
    clip_paths = []
    for i, entry in enumerate(entries, 1):
        step(f"  [{i}/{len(entries)}] downloading clip from {entry.title[:60]}")
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

    # ── Step 6: concat to single video track ──
    step("Concatenating clips to 1080p")
    intermediate = cache_dir / "concat.mp4"
    concat_clips_to_target(clip_paths, intermediate)

    # ── Step 7: compose (avatar overlay or narration mix) ──
    pre_frame = cache_dir / "pre_frame.mp4"
    if use_avatar and avatar_path:
        step("Overlaying avatar onto clips (bottom-left 20%) + mixing audio")
        overlay_avatar(intermediate, avatar_path, pre_frame)
    else:
        step("Mixing narration onto clips (final encode)")
        mix_narration(
            intermediate, narration_path, pre_frame,
            narration_duration_s=narration_duration,
        )

    # ── Step 8: overlay credits ──
    step("Overlaying credits (top-right, first 6s)")
    credited = cache_dir / "credited.mp4"
    overlay_credits(pre_frame, credited)

    # ── Step 9: apply decorative frame ──
    if use_frame:
        step("Applying frame (gold border + vignette)")
        apply_frame(credited, output_path)
    else:
        step("Skipping frame (--no-frame)")
        import shutil
        shutil.copy2(credited, output_path)

    total = time.time() - started
    step(f"Done: {output_path} ({total:.0f}s total)")

    return RecapResult(
        output_path=output_path,
        narration_chars=len(trimmed),
        narration_duration_s=narration_duration,
        clip_count=len(clip_paths),
        clip_length_s=clip_length_s,
        total_seconds=total,
        avatar=use_avatar,
    )
