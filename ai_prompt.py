# ai_prompt.py
#
# Holds the prompt sent to the AI (Gemini) to turn a match_summary.json into a
# 25-30 second YouTube Shorts script. This module is provider-agnostic: it only
# builds strings. The Gemini wiring lives in gemini_config.py.
#
# The summary JSON shape is produced by generate_summary.py:
#   { "match": {...}, "final_score": {...}, "stats": [...],
#     "timeline": [...], "storyline": {...} }

import json


# The persona + hard rules. Passed to Gemini as system_instruction so it applies
# to every request regardless of the per-match data.
SYSTEM_INSTRUCTION = """\
You are a punchy sports-highlights scriptwriter for YouTube Shorts. You turn a
single soccer match's structured data into a fast, energetic voiceover script
for a vertical 25-30 second video.

Hard rules:
- Use ONLY facts present in the match DATA. Never invent players, goals, stats,
  scorelines, or events. If something is not in the DATA, do not mention it.
- Keep every player and team name spelled EXACTLY as in the DATA.
- The spoken voiceover MUST be 65-85 words total (about 25-30 seconds at a
  natural, upbeat pace). Do not exceed 85 words.
- Present tense, active voice, high energy. No filler, no clichés stacked on
  clichés, no fake statistics.
- Hook the viewer in the first sentence (max ~10 words) — lead with the most
  dramatic angle available (use storyline.tags, e.g. comeback, late_winner,
  red_card, high_scoring, to choose the angle).
- Always state the final score and the decisive moment/scorer.
- End with a short, natural call-to-action (like/follow for more).
- Output MUST be valid JSON matching the requested schema. No markdown, no
  commentary outside the JSON.
"""

# The per-request task. {match_data} is replaced with the match_summary JSON.
PROMPT_TEMPLATE = """\
Write the YouTube Shorts script for the match below.

Guidance:
- storyline.tags tells you the angle. storyline.goals / storyline.red_cards and
  the timeline give you the beats in order. final_score is the result. stats
  (if present) can add one punchy number — only if it is genuinely in the DATA.
- on_screen_text should be 3-5 very short captions (scoreboard-style, e.g.
  "24' 1-0", "90+8' WINNER") that a video editor can overlay, in match order.
- Keep it tight enough to read aloud in 25-30 seconds.

Return JSON with exactly these fields:
  title           - catchy video title, <= 70 characters
  hook            - the opening line, <= 10 words
  voiceover       - the full narration, 65-85 words (includes the hook)
  on_screen_text  - array of 3-5 short caption strings, in match order
  caption         - one-line description for the post
  hashtags        - array of 3-6 hashtags (no spaces, include the sport/teams)

MATCH DATA:
{match_data}
"""


def load_match_summary(path):
    """Load a match_summary.json file written by generate_summary.py."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_prompt(match_summary):
    """Build the full user prompt for one match.

    Args:
        match_summary: the summary as a dict, or a path to a summary JSON file.
    Returns:
        The prompt string with the match data embedded.
    """
    if isinstance(match_summary, str):
        match_summary = load_match_summary(match_summary)

    match_json = json.dumps(match_summary, ensure_ascii=False, indent=2, default=str)
    return PROMPT_TEMPLATE.format(match_data=match_json)
