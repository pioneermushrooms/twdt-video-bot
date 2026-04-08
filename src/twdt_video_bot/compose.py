"""ffmpeg video compositor — stitches clips + narration into the final MP4.

Takes a list of pre-clipped video files and an MP3 narration, produces:
  - Concatenated video track from all clips (preserving original aspect)
  - Scaled/cropped to 1280x720 letterboxed or cover
  - Audio track = narration at 100% mixed with the clips' audio at 20%
  - Output length = narration length (video is looped or truncated to match)
  - Encoded at CRF 26, h264 yuv420p for Discord compatibility
"""

import subprocess
from pathlib import Path


TARGET_W = 1280
TARGET_H = 720
CRF = 26


def concat_clips_to_target(clip_paths: list[Path], intermediate_path: Path) -> Path:
    """Concatenate all clips into a single video track, normalized to the
    target resolution with letterboxing. Audio is preserved from the sources.
    """
    if not clip_paths:
        raise RuntimeError("No clips to concat.")

    # Build a filter graph that scales each clip to fit the target box while
    # preserving aspect (letterboxes if needed), then concats them together.
    n = len(clip_paths)
    inputs = []
    for clip in clip_paths:
        inputs += ["-i", str(clip)]

    # Per-clip filter: scale to fit target box, pad to exact target dims
    scale_pad = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    # Build the full filter: each input gets scaled+padded, then concat v+a
    filter_parts = []
    for i in range(n):
        filter_parts.append(f"[{i}:v]{scale_pad}[v{i}]")
        # Make sure there IS an audio stream — if not, insert silence via anullsrc
        # (but yt-dlp always outputs audio for these sources, so skip the check)
        filter_parts.append(f"[{i}:a]aresample=44100[a{i}]")

    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]")
    filter_graph = ";".join(filter_parts)

    intermediate_path = Path(intermediate_path)
    intermediate_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_graph,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(CRF),
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(intermediate_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg concat failed: {result.stderr[-600:]}"
        )
    return intermediate_path


def mix_narration(
    video_path: Path,
    narration_mp3: Path,
    output_path: Path,
    narration_duration_s: float,
    narration_db: float = 0.0,
    background_db: float = -14.0,
) -> Path:
    """Overlay narration onto the video's audio track.

    Narration plays at full volume, the video's original audio is mixed in
    at ~20% (-14dB). Output length is **hard-clamped** to
    `narration_duration_s` via ffmpeg's -t flag — we used to rely on
    `-stream_loop -1 ... -shortest` but that interacted badly with the
    amix filter and produced hour-long 450MB files.

    If the concatenated video is shorter than the narration, the video
    is looped via stream_loop and then truncated at narration length.
    If it's longer, it's truncated directly.
    """
    video_path = Path(video_path)
    narration_mp3 = Path(narration_mp3)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Figure out if we need to loop the video. Probe its duration.
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        video_duration = float(probe.stdout.strip())
    except ValueError:
        video_duration = 0.0

    need_loop = video_duration > 0 and video_duration < narration_duration_s - 0.5

    # Filter: amix two audio streams with weighted volumes. duration=first
    # anchors the mix to the looped-or-trimmed background track; -t later
    # hard-caps everything to narration length.
    filter_graph = (
        f"[0:a]volume={background_db}dB[bg];"
        f"[1:a]volume={narration_db}dB[narr];"
        "[bg][narr]amix=inputs=2:duration=longest:dropout_transition=0:"
        "normalize=0[aout]"
    )

    cmd = ["ffmpeg", "-y"]
    if need_loop:
        cmd += ["-stream_loop", "-1"]
    cmd += [
        "-i", str(video_path),
        "-i", str(narration_mp3),
        "-filter_complex", filter_graph,
        "-map", "0:v",
        "-map", "[aout]",
        "-t", f"{narration_duration_s:.3f}",  # HARD cap — this is the fix
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(CRF),
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg mix failed: {result.stderr[-600:]}"
        )
    return output_path
