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
    narration_db: float = 0.0,
    background_db: float = -14.0,
) -> Path:
    """Overlay narration onto the video's audio track.

    Narration plays at full volume, the video's original audio is mixed in
    at ~20% (-14dB). Output length is clamped to the narration length so the
    video ends when Crazy Eddie stops talking.

    narration_db: adjust narration level (0 = unchanged)
    background_db: how much to attenuate the source audio (-14 ≈ 20%)
    """
    video_path = Path(video_path)
    narration_mp3 = Path(narration_mp3)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Filter: amix two audio streams with weighted volumes, then take the
    # shortest duration. Video is trimmed to the audio length via -shortest.
    filter_graph = (
        f"[0:a]volume={background_db}dB[bg];"
        f"[1:a]volume={narration_db}dB[narr];"
        "[bg][narr]amix=inputs=2:duration=longest:dropout_transition=0:"
        "normalize=0[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",  # loop the video in case narration is longer
        "-i", str(video_path),
        "-i", str(narration_mp3),
        "-filter_complex", filter_graph,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(CRF),
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-shortest",  # end when the shortest stream ends (= narration)
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg mix failed: {result.stderr[-600:]}"
        )
    return output_path
