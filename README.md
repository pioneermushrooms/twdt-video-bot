# twdt-video-bot

Automated TWDT weekly recap videos — gorilla avatar narrates over game clips.

## Requirements

- Python 3.11+
- `ffmpeg` + `ffprobe` on PATH
- `yt-dlp` on PATH (with `node` for JS runtime)
- `.env` with `OPENAI_API_KEY` (for script trimming via gpt-4o-mini)
- `cookies.txt` in repo root (Netscape format YouTube cookies — needed to avoid throttling)

## Quick Start

```bash
pip install -e .

# Full pipeline with pre-rendered HeyGen avatar
python -m twdt_video_bot recap \
    --post https://forums.trenchwars.com/twdt/1368041-twdt-playoff-view \
    --playlist https://www.youtube.com/playlist?list=PLD3tebosagHmBt3-Gg7Tu0jgrr3RlShML \
    --avatar-file heygen.mp4 \
    --output recap.mp4

# Audio-only mode (no avatar, ElevenLabs narration)
# Requires ELEVEN_LABS_API_KEY in .env
python -m twdt_video_bot recap \
    --post https://forums.trenchwars.com/twdt/1368041-twdt-playoff-view \
    --playlist https://www.youtube.com/playlist?list=PLD3tebosagHmBt3-Gg7Tu0jgrr3RlShML \
    --no-avatar \
    --output recap.mp4
```

## Workflow (what you actually do each week)

1. **Get the forum post URL** from forums.trenchwars.com
2. **Get the YouTube playlist URL** for this week's match videos
3. **Generate the script** — the bot fetches the post and trims it to ~3k chars automatically
4. **Paste the trimmed script into HeyGen web UI** — use plan minutes (free), not API credits
5. **Generate in HeyGen** — pick the gorilla avatar, Crazy Eddie voice
6. **Download the HeyGen MP4** and save it to this folder (e.g. `heygen.mp4`)
7. **Run the bot:**
   ```bash
   python -m twdt_video_bot recap \
       --post <forum-url> \
       --playlist <playlist-url> \
       --avatar-file heygen.mp4 \
       --output recap_week5.mp4
   ```

The bot handles: clip downloading, length calculation, 50% zoom crop, 720p stitching,
avatar auto-crop (16:9 → 800x900 portrait), bottom-left overlay, audio mixing.

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--post` | — | Forum thread URL (scrapes the OP) |
| `--post-text` | — | Raw post text (skips scraping) |
| `--playlist` | — | YouTube playlist URL |
| `--output` | `recap.mp4` | Output MP4 path |
| `--cache` | `.cache` | Cache dir for intermediate files |
| `--avatar-file` | — | Path to pre-rendered HeyGen MP4 (auto-cropped to 800x900) |
| `--no-avatar` | false | Audio-only mode (ElevenLabs, no avatar) |
| `--voice` | Crazy Eddie | ElevenLabs voice ID (audio-only mode) |
| `--max-videos` | 12 | Max playlist videos to use |

## Pipeline Steps

1. **Fetch post** — scrape OP from forum URL, or take `--post-text` directly
2. **Trim script** — gpt-4o-mini condenses to ≤4500 chars, preserves teams/scores/matchups
3. **Avatar** — if `--avatar-file`, auto-crop 16:9 → 800x900 center portrait via ffmpeg
4. **List playlist** — yt-dlp flat-list metadata (no downloads yet)
5. **Clip length** — `avatar_duration / video_count`, clamped to 8-45s per clip
6. **Download clips** — yt-dlp with cookies + node JS runtime, cut to length
7. **Concat** — stitch all clips, 50% center crop zoom, scale to 1280x720, letterbox
8. **Overlay** — avatar bottom-left (20% width), avatar audio as narration, game audio at -14dB
9. **Output** — h264 CRF 26, yuv420p, Discord-friendly

## File Layout

```
twdt-video-bot/
├── src/twdt_video_bot/
│   ├── __main__.py    # CLI entrypoint
│   ├── pipeline.py    # Orchestrator
│   ├── forum.py       # Forum post scraper
│   ├── trim.py        # Script trimmer (gpt-4o-mini)
│   ├── narration.py   # ElevenLabs TTS (audio-only mode)
│   ├── heygen.py      # HeyGen API (avatar mode, costs credits)
│   ├── playlist.py    # yt-dlp playlist + clip downloader
│   └── compose.py     # ffmpeg: concat, mix, overlay, crop
├── cookies.txt        # YouTube auth cookies (gitignored)
├── .env               # API keys (gitignored)
└── pyproject.toml
```

## Integration with MAIGENT

The `/recap` slash command on MAIGENT's `research-agent` branch shells out to this
package and posts the resulting MP4 to Discord. See `maigent/flows/listeners.py`.
