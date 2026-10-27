"""Render the After-hours contribution snake as one animated SVG.

Usage: GITHUB_TOKEN=... python3 scripts/afterhours_snake.py <login> <out.svg>

The frame, sky gradient and Silkscreen caption are baked into the SVG because
GitHub strips style and clip-path from README HTML.
"""

import json
import math
import os
import sys
import urllib.request

CELL, GAP = 9, 3
STEP = CELL + GAP
ROWS = 7
BODY = 26
# The decision_grid preview moves the head 0.55 cells per requestAnimationFrame
# tick, so at 60 Hz the snake eats 33 cells a second.
FPS, CELLS_PER_FRAME = 60, 0.55
CELL_S = 1 / (FPS * CELLS_PER_FRAME)
RAMP = ["#10152e", "#2a4a3a", "#3f6e5a", "#569a6f", "#6fae7f"]
SNAKE, HEAD = "#ff9a3c", "#ffe0a8"
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

# Silkscreen at 12px, converted to outlines with fontTools so the SVG needs no
# webfont. Each entry is (advance width, path data at a baseline of 0).
GLYPHS = {
    'A': (9, 'M1.5 0V-6H3V-7.5H6V-6H7.5V0H6V-3H3V0ZM3 -4.5H6V-5.94H3Z'),
    'B': (9, 'M1.5 0V-7.5H6V-6H7.5V-1.5H6V0ZM3 -4.5H5.94V-6H3ZM3 -1.5H5.94V-3H3Z'),
    'C': (9, 'M6 -4.5V-6H3V-7.5H6V-6H7.5V-4.5ZM3 0V-1.5H1.5V-6H3V-1.5H6V0ZM6 -1.5V-3H7.5V-1.5Z'),
    'D': (9, 'M1.5 0V-7.5H6V-6H7.5V-1.5H6V0ZM3 -1.5H5.94V-6H3Z'),
    'E': (7.5, 'M1.5 0V-7.5H6V-6H3V-4.5H6V-3H3V-1.5H6V0Z'),
    'F': (7.5, 'M1.5 0V-7.5H6V-6H3V-4.5H6V-3H3V0Z'),
    'G': (9, 'M3 -6V-7.5H7.5V-6ZM1.5 -1.5V-6H3V-1.5ZM6 -1.5V-3H4.5V-4.5H7.5V-1.5ZM3 0V-1.5H6V0Z'),
    'H': (9, 'M1.5 0V-7.5H3V-4.5H6V-7.5H7.5V0H6V-3H3V0Z'),
    'I': (4.5, 'M1.5 0V-7.5H3V0Z'),
    'J': (9, 'M6 -1.5V-7.5H7.5V-1.5ZM3 0V-1.5H1.5V-3H3V-1.5H6V0Z'),
    'K': (9, 'M1.5 0V-7.5H3V-4.5H4.5V-3H6V-1.5H7.5V0H6V-1.5H4.5V-3H3V0ZM6 -6V-7.5H7.5V-6ZM4.5 -4.5V-6H6V-4.5Z'),
    'L': (7.5, 'M1.5 0V-7.5H3V-1.5H6V0Z'),
    'M': (10.5, 'M1.5 0V-7.5H3V-6H4.5V-4.5H6V-3H4.5V-4.5H3V0ZM7.5 0V-4.5H6V-6H7.5V-7.5H9V0Z'),
    'N': (10.5, 'M1.5 0V-7.5H3V-6H4.5V-4.5H6V-3H7.5V-7.5H9V0H7.5V-1.5H6V-3H4.5V-4.5H3V0Z'),
    'O': (9, 'M3 0V-1.5H1.5V-6H3V-7.5H6V-6H7.5V-1.5H6V0ZM3 -1.56H6V-5.94H3Z'),
    'P': (9, 'M1.5 0V-7.5H6V-6H7.5V-4.5H6V-3H3V0ZM3 -4.5H5.94V-6H3Z'),
    'Q': (9, 'M6 1.5V0H3V-1.5H1.5V-6H3V-7.5H6V-6H7.5V-1.5H6V0H7.5V1.5ZM3 -1.56H6V-5.94H3Z'),
    'R': (9, 'M1.5 0V-7.5H6V-6H7.5V-4.5H6V-1.5H7.5V0H6V-1.5H4.5V-3H3V0ZM3 -4.5H5.94V-6H3Z'),
    'S': (9, 'M3 -6V-7.5H7.5V-6ZM6 -1.5V-3H3V-4.5H1.5V-6H3V-4.5H6V-3H7.5V-1.5ZM1.5 0V-1.5H6V0Z'),
    'T': (7.5, 'M3 0V-6H1.5V-7.5H6V-6H4.5V0Z'),
    'U': (9, 'M3 0V-1.5H1.5V-7.5H3V-1.5H6V0ZM6 -1.5V-7.5H7.5V-1.5Z'),
    'V': (10.5, 'M4.5 0V-1.5H3V-4.5H1.5V-7.5H3V-4.5H4.5V-1.5H6V0ZM7.5 -4.5V-7.5H9V-4.5ZM6 -1.5V-4.5H7.5V-1.5Z'),
    'W': (10.5, 'M3 0V-1.5H1.5V-7.5H3V-1.5H4.5V0ZM7.5 -1.5V-7.5H9V-1.5ZM6 0V-1.5H4.5V-6H6V-1.5H7.5V0Z'),
    'X': (10.5, 'M7.5 0V-1.5H6V-3H4.5V-4.5H3V-6H1.5V-7.5H3V-6H4.5V-4.5H6V-3H7.5V-1.5H9V0ZM6 -4.5V-6H7.5V-7.5H9V-6H7.5V-4.5ZM3 -1.5V-3H4.5V-1.5ZM1.5 0V-1.5H3V0Z'),
    'Y': (10.5, 'M4.5 0V-4.5H3V-6H1.5V-7.5H3V-6H4.5V-4.5H6V0ZM7.5 -6V-7.5H9V-6ZM6 -4.5V-6H7.5V-4.5Z'),
    'Z': (7.5, 'M4.5 -4.5V-6H1.5V-7.5H6V-4.5ZM3 -3V-4.5H4.5V-3ZM1.5 0V-3H3V-1.5H6V0Z'),
    '0': (9, 'M3 0V-1.5H1.5V-6H3V-7.5H6V-6H7.5V-1.5H6V0ZM3 -1.56H6V-5.94H3Z'),
    '1': (7.5, 'M1.5 0V-1.5H3V-6H1.5V-7.5H4.5V-1.5H6V0Z'),
    '2': (9, 'M6 -4.5V-6H1.5V-7.5H6V-6H7.5V-4.5ZM3 -3V-4.5H6V-3ZM1.5 0V-3H3V-1.5H7.5V0Z'),
    '3': (9, 'M6 -4.5V-6H1.5V-7.5H6V-6H7.5V-4.5ZM6 -1.5V-3H3V-4.5H6V-3H7.5V-1.5ZM1.5 0V-1.5H6V0Z'),
    '4': (9, 'M4.5 0V-3H1.5V-7.5H3V-4.5H4.5V-7.5H6V-4.5H7.5V-3H6V0Z'),
    '5': (9, 'M6 -1.5V-3H1.5V-7.5H7.5V-6H3V-4.5H6V-3H7.5V-1.5ZM1.5 0V-1.5H6V0Z'),
    '6': (9, 'M3 0V-1.5H1.5V-6H3V-7.5H6V-6H3V-4.5H6V-3H7.5V-1.5H6V0ZM3 -1.56H6V-2.94H3Z'),
    '7': (9, 'M3 0V-3H4.5V-4.5H6V-6H1.5V-7.5H7.5V-4.5H6V-3H4.5V0Z'),
    '8': (9, 'M3 0V-1.5H1.5V-3H3V-4.5H1.5V-6H3V-7.5H6V-6H7.5V-4.5H6V-3H7.5V-1.5H6V0ZM3 -4.56H6V-5.94H3ZM3 -1.56H6V-2.94H3Z'),
    '9': (9, 'M3 0V-1.5H6V-3H3V-4.5H1.5V-6H3V-7.5H6V-6H7.5V-1.5H6V0ZM3 -4.56H6V-5.94H3Z'),
    ' ': (6, ''),
    '·': (4.5, 'M1.5 -3V-4.5H3V-3Z'),
    ',': (6, 'M3 0V-1.5H4.5V0ZM1.5 1.5V0H3V1.5Z'),
    '-': (7.5, 'M1.5 -3V-4.5H6V-3Z'),
}
TRACKING = 0.48  # The artifact's caption uses 0.04em letter-spacing.

# The 648x133 box reproduces the artifact's .snakebox.afterhours: 14/12/10 padding
# around the 624x84 grid, an 8px caption gap and a 16.8px caption line.
W, H = 648, 133
PX = f"0,8 8,8 8,0 {W - 8},0 {W - 8},8 {W},8 {W},{H - 8} {W - 8},{H - 8} {W - 8},{H} 8,{H} 8,{H - 8} 0,{H - 8}"

QUERY = """query($login: String!) { user(login: $login) { contributionsCollection {
  contributionCalendar { weeks { contributionDays { weekday contributionLevel contributionCount } } } } } }"""


def fetch_weeks(login, token):
    """Return the last 52 weeks twice, as levels and as counts, with None for future days."""
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    if "errors" in body:
        sys.exit(f"GraphQL error: {body['errors']}")
    weeks, counts = [], []
    for week in body["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"][-52:]:
        days: list[int | None] = [None] * ROWS
        tally: list[int | None] = [None] * ROWS
        for day in week["contributionDays"]:
            days[day["weekday"]] = LEVELS[day["contributionLevel"]]
            tally[day["weekday"]] = day["contributionCount"]
        weeks.append(days)
        counts.append(tally)
    return weeks, counts


def caption(counts):
    """Summarize the days the grid shows: total, longest streak and best day."""
    days = [n for week in counts for n in week if n is not None]
    longest = run = 0
    for n in days:
        run = run + 1 if n else 0
        longest = max(longest, run)
    total = sum(days)
    return (f"{total:,} CONTRIBUTION{'' if total == 1 else 'S'} · LONGEST STREAK {longest} "
            f"DAY{'' if longest == 1 else 'S'} · BEST DAY {max(days):,}")


def caption_path(text):
    """Lay out text in the Silkscreen glyph table as one SVG path at a baseline of 0."""
    x, parts = 0.0, []
    for ch in text:
        width, d = GLYPHS[ch]
        if d:
            parts.append(f'<path transform="translate({x:g} 0)" d="{d}"/>')
        x += width + TRACKING
    return "".join(parts)


def period_s(n):
    """Return the loop length in seconds for a path of n cells.

    The preview draws the frame where the tail clears the last cell, then resets
    the head to zero on the next frame.
    """
    return (math.ceil((n + BODY) / CELLS_PER_FRAME) + 1) / FPS


def pct(seconds, period):
    return f"{seconds / period * 100:.3f}%"


def render(weeks, text=""):
    """Build the SVG for a list of weeks, each a 7-slot list of levels or None, captioned with text."""
    path = []
    for c, week in enumerate(weeks):
        rows = range(ROWS) if c % 2 == 0 else reversed(range(ROWS))
        path += [(c, r) for r in rows if week[r] is not None]
    period = period_s(len(path))
    anim = f"{period:.2f}s step-end infinite"

    # Every cell shares the body keyframes and starts them when the head arrives.
    # The head paints the cell, then each later body segment fades it a step.
    body = [f"0%{{fill:{HEAD};opacity:1}}"]
    for b in range(1, BODY + 1):
        body.append(f"{pct(b * CELL_S, period)}{{fill:{SNAKE};opacity:{1 - b / BODY * 0.55:.3f}}}")
    body.append(f"{pct((BODY + 1) * CELL_S, period)},100%{{opacity:0}}")
    css = [f"@keyframes s{{{''.join(body)}}}", f".s{{opacity:0;animation:s {anim}}}"]

    cells, snake = [], []
    for i, (c, r) in enumerate(path):
        x, y = c * STEP, r * STEP
        level = weeks[c][r]
        eaten_at = i * CELL_S
        if level:
            # An eaten cell drops to the empty color until the loop restarts.
            css.append(f"@keyframes e{i}{{0%{{fill:{RAMP[level]}}}{pct(eaten_at, period)},100%{{fill:{RAMP[0]}}}}}")
            style = f' style="animation:e{i} {anim}"'
        else:
            style = ""
        cells.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" fill="{RAMP[level]}"{style}/>')
        snake.append(f'<rect class="s" x="{x}" y="{y}" width="{CELL}" height="{CELL}" style="animation-delay:{eaten_at:.3f}s"/>')

    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f"<style>{''.join(css)}</style>",
        '<defs><linearGradient id="sky" x2="0" y2="1"><stop offset="0" stop-color="#0b0f24"/>'
        '<stop offset="1" stop-color="#2b1740"/></linearGradient>'
        f'<clipPath id="px"><polygon points="{PX}"/></clipPath></defs>',
        f'<g clip-path="url(#px)"><rect width="{W}" height="{H}" fill="url(#sky)"/>'
        f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" fill="none" stroke="#ffb347" stroke-width="2"/></g>',
        '<g transform="translate(12 14)">', *cells, *snake, "</g>",
        f'<g transform="translate(12 119.08)" fill="#ffbe73">{caption_path(text)}</g>',
        "</svg>",
    ])


if __name__ == "__main__":
    login, out = sys.argv[1], sys.argv[2]
    with open(out, "w") as f:
        weeks, counts = fetch_weeks(login, os.environ["GITHUB_TOKEN"])
        f.write(render(weeks, caption(counts)))
