"""ffmpeg video compositor — stitches clips + narration into the final MP4.

Takes a list of pre-clipped video files and an MP3 narration, produces:
  - Concatenated video track from all clips (preserving original aspect)
  - Scaled/cropped to 1920x1080 letterboxed or cover
  - Audio track = narration at 100% mixed with the clips' audio at 20%
  - Output length = narration length (video is looped or truncated to match)
  - Encoded at CRF 23, h264 yuv420p for Discord compatibility
  - Gold border frame + vignette for polished Discord embed look
"""

import subprocess
from pathlib import Path


TARGET_W = 1920
TARGET_H = 1080
CRF = 23

# Avatar crop target — center-crop the 16:9 HeyGen output to portrait
AVATAR_CROP_W = 800
AVATAR_CROP_H = 900


def crop_avatar(input_path: Path, output_path: Path, speed: float = 1.3) -> Path:
    """Prepare a HeyGen avatar video for overlay.

    - 16:9 input: center-crop to 800x900 portrait (API output)
    - 9:16 input: crop center square, scale down (web UI phone format)
    - Speeds up video/audio by `speed` factor (default 1.3x)
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Probe input dimensions to pick the right filter
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(input_path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    try:
        w, h = [int(x) for x in probe.stdout.strip().split(",")]
    except ValueError:
        w, h = 0, 0

    if h > w:
        # Portrait (9:16 from web UI) — crop center square, then scale down
        vf = f"crop={w}:{w}:0:({h}-{w})/2,scale={AVATAR_CROP_W}:-2"
    else:
        # Landscape (16:9 from API) — center-crop to portrait
        vf = f"crop={AVATAR_CROP_W}:{AVATAR_CROP_H}"

    # Speed up video
    if speed != 1.0:
        vf += f",setpts=PTS/{speed}"

    af = f"atempo={speed}" if speed != 1.0 else "acopy"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(CRF),
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg crop failed: {result.stderr[-600:]}")
    return output_path


def apply_frame(input_path: Path, output_path: Path) -> Path:
    """Apply a cinematic frame to the final video for Discord presentation.

    Adds: 4px gold outer border, 1px dark inner line, subtle vignette,
    thin dark gradient bars at top/bottom for depth.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Frame filter chain:
    #   1. Outer gold border (4px) via drawbox
    #   2. Inner dark border (1px) for depth
    #   3. Vignette for cinematic edge darkening
    #   4. Thin dark gradient bars top+bottom (letterbox feel)
    border = 4
    inner = border + 1
    frame_filter = (
        # Gold outer border
        f"drawbox=x=0:y=0:w=iw:h=ih:t={border}:color=#B8962E@0.85,"
        # Dark inner line
        f"drawbox=x={border}:y={border}:w=iw-{border*2}:h=ih-{border*2}:t=1:color=#000000@0.5,"
        # Subtle vignette — darkens edges naturally
        "vignette=PI/5:1.2,"
        # Top gradient bar (semi-transparent black, 30px)
        f"drawbox=x={inner}:y={inner}:w=iw-{inner*2}:h=30:t=fill:color=#000000@0.3,"
        # Bottom gradient bar
        f"drawbox=x={inner}:y=ih-{inner}-30:w=iw-{inner*2}:h=30:t=fill:color=#000000@0.3"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", frame_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(CRF),
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame failed: {result.stderr[-600:]}")
    return output_path


def overlay_credits(
    video_path: Path,
    output_path: Path,
    show_s: float = 6.0,
    fade_s: float = 1.0,
) -> Path:
    """Overlay credits text in the top-right corner for the first few seconds.

    Text fades in at the start and fades out after show_s seconds.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    font_file = r"C\:/Windows/Fonts/arial.ttf"
    # Each line: (text, fontsize, y_offset from top-right anchor)
    lines = [
        ("TWDT Season 32 - Week 7 Recap", 24, 20),
        (r"Writing\: Lee", 18, 52),
        (r"Recording\: Dameon Angell", 18, 74),
        (r"Production\: Dare", 18, 96),
    ]

    # Fade: alpha goes 0→1 over fade_s, holds, then 1→0
    fade_in = f"if(lt(t,{fade_s}),t/{fade_s},if(lt(t,{show_s - fade_s}),1,({show_s}-t)/{fade_s}))"

    drawtext_parts = []
    for text, size, y_off in lines:
        drawtext_parts.append(
            f"drawtext=text='{text}':fontsize={size}"
            f":fontcolor=white:fontfile='{font_file}'"
            f":x=w-text_w-20:y={y_off}"
            f":alpha='{fade_in}'"
        )

    vf = ",".join(drawtext_parts)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(CRF),
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg credits overlay failed: {result.stderr[-600:]}")
    return output_path


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

    # Per-clip filter: crop center 50% (zoom in) → scale to target → pad
    # The crop removes the outer 25% on each side, making the action fill
    # the frame. Then scale to target dims with letterbox padding.
    scale_pad = (
        f"crop=iw/2:ih/2:iw/4:ih/4,"
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


def overlay_avatar(
    video_path: Path,
    avatar_path: Path,
    output_path: Path,
    avatar_fraction: float = 0.20,
    background_db: float = -14.0,
) -> Path:
    """Overlay a talking-head avatar video onto the bottom-left corner of
    the main video. The avatar's audio replaces the narration track (since
    HeyGen already generates lip-synced narration). The main video's audio
    is mixed in at background_db (~20%).

    Args:
        video_path: the concatenated game clips (720p, with game audio)
        avatar_path: HeyGen's avatar MP4 (512x512 or similar, with narration audio)
        output_path: final output MP4
        avatar_fraction: how much of the main video's width the avatar takes
                         up. 0.20 = 20% = bottom-left corner.
        background_db: volume of the game audio behind the narration (-14 ≈ 20%)

    Duration is clamped to the avatar video's length (= narration length).
    """
    video_path = Path(video_path)
    avatar_path = Path(avatar_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get avatar duration for the -t clamp
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(avatar_path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    try:
        avatar_duration = float(probe.stdout.strip())
    except ValueError:
        avatar_duration = 0.0

    # Get main video dimensions for the overlay math
    probe2 = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(video_path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    try:
        main_w, main_h = [int(x) for x in probe2.stdout.strip().split(",")]
    except ValueError:
        main_w, main_h = TARGET_W, TARGET_H

    # Avatar target width = fraction of main video width
    avatar_w = int(main_w * avatar_fraction)

    # Check if main video is shorter than avatar — need to loop if so
    probe3 = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    try:
        video_duration = float(probe3.stdout.strip())
    except ValueError:
        video_duration = 0.0

    need_loop = video_duration > 0 and video_duration < avatar_duration - 0.5

    # Filter graph:
    # [1:v] scale avatar to target width, maintain aspect → [avatar]
    # [0:v][avatar] overlay at bottom-left → [vout]
    # [0:a] game audio at background volume → [bg]
    # [1:a] avatar narration at full volume → [narr]
    # [bg][narr] amix → [aout]
    filter_graph = (
        f"[1:v]scale={avatar_w}:-1[avatar];"
        f"[0:v][avatar]overlay=0:H-h[vout];"
        f"[0:a]volume={background_db}dB[bg];"
        f"[1:a]volume=0dB[narr];"
        f"[bg][narr]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]"
    )

    cmd = ["ffmpeg", "-y"]
    if need_loop:
        cmd += ["-stream_loop", "-1"]
    cmd += [
        "-i", str(video_path),
        "-i", str(avatar_path),
        "-filter_complex", filter_graph,
        "-map", "[vout]",
        "-map", "[aout]",
        "-t", f"{avatar_duration:.3f}",
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
            f"ffmpeg overlay failed: {result.stderr[-600:]}"
        )
    return output_path
