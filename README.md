# twdt-video-bot

Automated TWDT weekly recap videos.

## What it does

Given:
- A **forum post URL** (or raw text) containing a weekly recap
- A **YouTube playlist URL** of this week's team game videos

Produces an MP4 where:
- ElevenLabs (Crazy Eddie voice) narrates the forum post
- Each team's game video contributes a first-N-seconds clip
- Clips are sequenced under the narration, time-divided equally across the playlist
- Game audio is mixed at 20% under the narration
- Output is 720p horizontal, Discord-friendly under the Boost L3 100MB cap

## Requirements

- Python ≥ 3.11
- `ffmpeg` on PATH
- `.env` with `ELEVEN_LABS_API_KEY` and `OPENAI_API_KEY`

## Usage

```bash
# From forum URL
python -m twdt_video_bot recap \
    --post https://forums.trenchwars.com/twdt/1368041-twdt-playoff-view \
    --playlist https://www.youtube.com/playlist?list=PLD3tebosagHmBt3-Gg7Tu0jgrr3RlShML \
    --output recap.mp4

# Or from pasted text
python -m twdt_video_bot recap \
    --post-text "$(cat forum_post.txt)" \
    --playlist https://www.youtube.com/playlist?list=PLD3tebosagHmBt3-Gg7Tu0jgrr3RlShML \
    --output recap.mp4
```

## Pipeline

1. **Fetch post** from forum URL (extract OP only, strip chrome) — or take `--post-text` directly
2. **Trim to ≤5000 chars** via gpt-4o-mini if needed (ElevenLabs hard limit)
3. **Generate narration** via ElevenLabs (Crazy Eddie voice) → MP3 + duration
4. **List playlist videos** via yt-dlp
5. **Clip length** = `narration_duration / video_count`, capped to 10-45s
6. **Download & cut** each video's first `clip_length` seconds
7. **Concat clips** + **overlay narration** (narration 100%, game 20%) via ffmpeg
8. **Crop to 1280x720**, encode CRF 26, output MP4

## Integration with MAIGENT

The `/recap` slash command on MAIGENT's `research-agent` branch shells out to this
package and posts the resulting MP4 to Discord. See `maigent/flows/listeners.py`.
