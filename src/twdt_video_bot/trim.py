"""LLM-powered text trimmer — keeps narration under ElevenLabs' 5000 char cap.

If the forum post is already under the limit, we return it unchanged. If it's
over, we ask gpt-4o-mini to condense it to ~4500 chars (leaving headroom for
TTS formatting quirks) while preserving all team names, scores, matchups, and
the writer's voice.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ELEVEN_LIMIT = 5000
TARGET = 4500  # leave 500-char safety margin


def _api_key() -> str:
    # Look for .env in the repo root (parent of src/)
    load_dotenv(Path(__file__).parent.parent.parent / ".env", override=False)
    # Also try maigent's .env as a convenience — user has keys there
    load_dotenv(Path(__file__).parent.parent.parent.parent / "maigent" / ".env", override=False)
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set in .env")
    return key


def trim_for_tts(text: str, target: int = TARGET) -> str:
    """Return text at or below `target` characters, using gpt-4o-mini if needed."""
    text = text.strip()
    if len(text) <= target:
        return text

    key = _api_key()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    system = (
        "You are a sports editor condensing a weekly TWDT (Trench Wars Draft "
        "Tournament) forum recap into a narration script for a video voiceover. "
        f"Your output MUST be at most {target} characters (hard limit — count "
        "them). Preserve:\n"
        "- All team names exactly as written\n"
        "- All scores and match results\n"
        "- The writer's voice and specific observations\n"
        "- The team-by-team structure\n"
        "Drop:\n"
        "- Redundant phrases and filler\n"
        "- Overly long speculation\n"
        "- Repeated points\n\n"
        "Output ONLY the condensed narration — no preamble, no 'Here is', "
        "no quote marks, nothing but the text the narrator will read."
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
    )
    trimmed = resp.choices[0].message.content.strip()

    # Hard cap as a safety net — if the LLM ignored the limit, clip it
    if len(trimmed) > ELEVEN_LIMIT:
        trimmed = trimmed[:ELEVEN_LIMIT - 3] + "..."

    return trimmed
