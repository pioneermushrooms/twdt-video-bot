"""CLI entrypoint: python -m twdt_video_bot recap ..."""

import argparse
import sys
from pathlib import Path

from twdt_video_bot.narration import DEFAULT_VOICE_ID
from twdt_video_bot.pipeline import build_recap


def main():
    parser = argparse.ArgumentParser(
        prog="twdt-video-bot",
        description="Automated TWDT weekly recap videos",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    recap = sub.add_parser("recap", help="Build a recap video from a forum post + playlist")
    src = recap.add_mutually_exclusive_group(required=True)
    src.add_argument("--post", help="Forum thread URL (scrapes the OP)")
    src.add_argument("--post-text", help="Raw post text (skips scraping)")
    recap.add_argument("--playlist", required=True, help="YouTube playlist URL")
    recap.add_argument("--output", default="recap.mp4", help="Output MP4 path")
    recap.add_argument("--cache", default=".cache", help="Cache dir for intermediate files")
    recap.add_argument("--voice", default=DEFAULT_VOICE_ID, help="ElevenLabs voice ID")
    recap.add_argument("--max-videos", type=int, default=12, help="Max playlist videos to use")

    args = parser.parse_args()

    if args.command == "recap":
        post_source = args.post or args.post_text
        print(f"twdt-video-bot recap")
        print(f"  post:     {post_source[:80] if post_source else ''}")
        print(f"  playlist: {args.playlist}")
        print(f"  output:   {args.output}")
        print()
        try:
            result = build_recap(
                post_source=post_source,
                playlist_url=args.playlist,
                output_path=Path(args.output),
                cache_dir=Path(args.cache),
                voice_id=args.voice,
                max_playlist=args.max_videos,
            )
        except Exception as e:
            print(f"FAILED: {e}", file=sys.stderr)
            sys.exit(1)

        print()
        print(f"Output:  {result.output_path}")
        print(f"Runtime: {result.total_seconds:.0f}s")
        print(f"Narration: {result.narration_chars} chars / {result.narration_duration_s:.1f}s")
        print(f"Clips:   {result.clip_count} @ {result.clip_length_s:.1f}s each")
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
