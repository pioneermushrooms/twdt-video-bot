"""Interactive recap wizard — step-by-step CLI with prompts.

Run: python -m twdt_video_bot wizard
"""

import sys
import textwrap
from pathlib import Path

from twdt_video_bot.compose import apply_frame, concat_clips_to_target, crop_avatar, overlay_avatar, mix_narration
from twdt_video_bot.forum import load_post
from twdt_video_bot.narration import generate_narration
from twdt_video_bot.pipeline import _probe_duration, MIN_CLIP_S, MAX_CLIP_S, CLIP_START_OFFSET_S
from twdt_video_bot.playlist import download_clip, list_playlist
from twdt_video_bot.trim import trim_for_tts


DIVIDER = "─" * 60


def _ask(prompt: str, default: str = "") -> str:
    """Prompt the user for input with an optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        sys.exit(1)
    return val or default


def _confirm(prompt: str) -> bool:
    """Ask yes/no."""
    val = _ask(f"{prompt} (y/n)", "y")
    return val.lower() in ("y", "yes")


def _header(step: int, title: str):
    print(f"\n{DIVIDER}")
    print(f"  Step {step}: {title}")
    print(DIVIDER)


def run_wizard():
    cache_dir = Path(".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("  TWDT Recap Video Wizard")
    print("  " + "=" * 40)
    print()

    # ── Step 1: Forum post ──
    _header(1, "Forum Post")
    post_url = _ask("Forum post URL (or paste raw text)")
    print("  Fetching & parsing...")
    raw_text = load_post(post_url)
    print(f"  Got {len(raw_text)} chars")

    # ── Step 2: Trim script ──
    _header(2, "Trim Script for Narration")
    print("  Trimming to ~4500 chars via gpt-4o-mini...")
    trimmed = trim_for_tts(raw_text)
    print(f"  Trimmed: {len(trimmed)} chars")
    print()
    # Show a preview
    preview = trimmed[:300] + ("..." if len(trimmed) > 300 else "")
    print(textwrap.indent(preview, "    "))
    print()

    # ── Step 3: Copy script to HeyGen ──
    _header(3, "HeyGen Avatar Video")
    print("  The trimmed script has been printed above.")
    print("  Next steps:")
    print("    1. Copy the script text")
    print("    2. Paste it into HeyGen web UI")
    print("    3. Select your gorilla avatar + Crazy Eddie voice")
    print("    4. Generate the video (uses plan minutes, free)")
    print("    5. Download the finished MP4 to this folder")
    print()

    # Save script to file for easy copy-paste
    script_path = cache_dir / "script.txt"
    script_path.write_text(trimmed, encoding="utf-8")
    print(f"  Script saved to: {script_path}")
    print("  (Open that file and copy the full text into HeyGen)")
    print()

    input("  Press Enter when the HeyGen video is downloaded...")
    print()
    avatar_file = _ask("HeyGen MP4 filename (in this folder)", "heygen.mp4")
    avatar_path = Path(avatar_file)
    if not avatar_path.exists():
        print(f"  ERROR: {avatar_path} not found. Check the filename and try again.")
        avatar_file = _ask("Try again — filename")
        avatar_path = Path(avatar_file)
        if not avatar_path.exists():
            print(f"  FATAL: {avatar_path} not found. Exiting.")
            sys.exit(1)

    # ── Step 4: Crop avatar ──
    _header(4, "Crop Avatar (16:9 -> 800x900)")
    cropped_path = cache_dir / "avatar_cropped.mp4"
    print(f"  Cropping {avatar_path.name} to 800x900 center portrait...")
    crop_avatar(avatar_path, cropped_path)
    avatar_duration = _probe_duration(cropped_path)
    print(f"  Done: {cropped_path.name} ({avatar_duration:.1f}s)")

    # ── Step 5: Playlist ──
    _header(5, "YouTube Playlist")
    playlist_url = _ask("YouTube playlist URL")
    max_vids = int(_ask("Max videos to use", "12"))
    print(f"  Listing playlist (max {max_vids})...")
    entries = list_playlist(playlist_url, max_entries=max_vids)
    if not entries:
        print("  ERROR: No videos found in playlist.")
        sys.exit(1)
    print(f"  Found {len(entries)} videos:")
    for i, e in enumerate(entries, 1):
        dur = f" ({e.duration:.0f}s)" if e.duration else ""
        print(f"    {i}. {e.title[:70]}{dur}")
    print()

    # ── Step 6: Download clips ──
    raw_clip_s = avatar_duration / len(entries) if entries else 30.0
    clip_length_s = max(MIN_CLIP_S, min(MAX_CLIP_S, raw_clip_s))
    _header(6, f"Download Clips ({clip_length_s:.1f}s each)")

    clip_paths = []
    for i, entry in enumerate(entries, 1):
        print(f"  [{i}/{len(entries)}] {entry.title[:60]}...")
        start = CLIP_START_OFFSET_S
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
            print(f"         OK")
        except Exception as e:
            print(f"         FAILED: {e}")

    if not clip_paths:
        print("  FATAL: No clips downloaded.")
        sys.exit(1)
    print(f"\n  Got {len(clip_paths)}/{len(entries)} clips")

    # ── Step 7: Concat ──
    _header(7, "Stitch Clips (1080p)")
    intermediate = cache_dir / "concat.mp4"
    print("  Concatenating + scaling to 1920x1080...")
    concat_clips_to_target(clip_paths, intermediate)
    print("  Done")

    # ── Step 8: Overlay avatar ──
    _header(8, "Overlay Avatar")
    pre_frame = cache_dir / "pre_frame.mp4"
    print("  Overlaying avatar (bottom-left 20%) + mixing audio...")
    overlay_avatar(intermediate, cropped_path, pre_frame)
    print("  Done")

    # ── Step 9: Apply frame ──
    output_name = _ask("Output filename", "recap.mp4")
    output_path = Path(output_name)
    _header(9, "Apply Frame")
    print("  Adding gold border + vignette...")
    apply_frame(pre_frame, output_path)

    # ── Done ──
    size_mb = output_path.stat().st_size / (1024 * 1024)
    duration = _probe_duration(output_path)
    print(f"\n{DIVIDER}")
    print(f"  DONE!")
    print(f"  Output:   {output_path}")
    print(f"  Duration: {duration:.1f}s")
    print(f"  Size:     {size_mb:.1f} MB")
    print(f"  Clips:    {len(clip_paths)} @ {clip_length_s:.1f}s each")
    print(DIVIDER)


if __name__ == "__main__":
    run_wizard()
