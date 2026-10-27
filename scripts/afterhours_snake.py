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

# "GRID · AFTER HOURS · LV.52" in Silkscreen 12px with 0.04em tracking, converted
# to outlines with fontTools so the SVG needs no webfont.
CAPTION = (
    "M3 -6V-7.5H7.5V-6ZM1.5 -1.5V-6H3V-1.5ZM6 -1.5V-3H4.5V-4.5H7.5V-1.5ZM3 0V-1.5H6V0ZM10.98 0V-7.5H15.48V-6H16.98V-4.5H15.48V-1.5H16.98V0H15.48V-1.5H13.98V-3H12.48V0ZM12.48 -4.5H15.42V-6H12.48ZM20.46 0V-7.5H21.96V0ZM25.44 0V-7.5H29.94V-6H31.44V-1.5H29.94V0ZM26.94 -1.5H29.88V-6H26.94ZM41.4 -3V-4.5H42.9V-3ZM51.36 0V-6H52.86V-7.5H55.86V-6H57.36V0H55.86V-3H52.86V0ZM52.86 -4.5H55.86V-6H52.86ZM60.84 0V-7.5H66.84V-6H62.34V-4.5H65.34V-3H62.34V0ZM71.82 0V-6H69.57V-7.5H75.57V-6H73.32V0ZM79.05 0V-7.5H85.05V-6H80.55V-4.5H83.55V-3H80.55V-1.5H85.05V0ZM88.53 0V-7.5H93.03V-6H94.53V-4.5H93.03V-1.5H94.53V0H93.03V-1.5H91.53V-3H90.03V0ZM90.03 -4.5H92.97V-6H90.03ZM103.5 0V-7.5H105V-4.5H108V-7.5H109.5V0H108V-3H105V0ZM114.48 -1.5V-6H115.98V-1.5ZM115.98 0V-1.5H118.98V0ZM115.98 -6V-7.5H118.98V-6ZM118.98 -1.5V-6H120.48V-1.5ZM123.96 -1.5V-7.5H125.46V-1.5ZM125.46 0V-1.5H128.46V0ZM128.46 -1.5V-7.5H129.96V-1.5ZM133.44 0V-7.5H137.94V-6H139.44V-4.5H137.94V-1.5H139.44V0H137.94V-1.5H136.44V-3H134.94V0ZM134.94 -4.5H137.88V-6H134.94ZM142.92 -1.5V-3H147.42V-1.5ZM144.42 -4.5V-6H148.92V-4.5ZM142.92 -4.5V-6H144.42V-4.5ZM142.92 0V-1.5H147.42V0ZM147.42 -1.5V-4.5H148.92V-1.5ZM144.42 -6V-7.5H148.92V-6ZM158.88 -3V-4.5H160.38V-3ZM168.84 0V-7.5H170.34V-1.5H174.84V0ZM179.82 -1.5V-3H181.32V-1.5ZM176.82 -3V-7.5H178.32V-3ZM181.32 -3V-7.5H182.82V-3ZM178.32 0V-1.5H179.82V0ZM178.32 -1.5V-3H179.82V-1.5ZM186.3 0V-1.5H187.8V0ZM191.28 0V-1.5H195.78V0ZM190.78 -4.5V-6H195.28V-4.5ZM189.78 -1.5V-3H191.28V-1.5ZM194.28 -3V-4.5H195.78V-3ZM189.28 -6V-7.5H195.78V-6ZM189.28 -4.5V-6H190.78V-4.5ZM198.76 0V-1.5H205.26V0ZM205.26 -3V-1.5H203.76V-3ZM203.76 -4.5V-3H202.26V-4.5ZM202.26 -6V-4.5H200.26V-6ZM200.76 -6V-7.5H205.26V-6ZM199.26 -4.5V-6H200.76V-4.5ZM205.26 -4.5V-6H206.76V-4.5Z"
)

# The 648x133 box reproduces the artifact's .snakebox.afterhours: 14/12/10 padding
# around the 624x84 grid, an 8px caption gap and a 16.8px caption line.
W, H = 648, 133
PX = f"0,8 8,8 8,0 {W - 8},0 {W - 8},8 {W},8 {W},{H - 8} {W - 8},{H - 8} {W - 8},{H} 8,{H} 8,{H - 8} 0,{H - 8}"

QUERY = """query($login: String!) { user(login: $login) { contributionsCollection {
  contributionCalendar { weeks { contributionDays { weekday contributionLevel } } } } } }"""


def fetch_weeks(login, token):
    """Return the last 52 weeks as 7-slot lists of levels, with None for future days."""
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    if "errors" in body:
        sys.exit(f"GraphQL error: {body['errors']}")
    weeks = []
    for week in body["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"][-52:]:
        days: list[int | None] = [None] * ROWS
        for day in week["contributionDays"]:
            days[day["weekday"]] = LEVELS[day["contributionLevel"]]
        weeks.append(days)
    return weeks


def period_s(n):
    """Return the loop length in seconds for a path of n cells.

    The preview draws the frame where the tail clears the last cell, then resets
    the head to zero on the next frame.
    """
    return (math.ceil((n + BODY) / CELLS_PER_FRAME) + 1) / FPS


def pct(seconds, period):
    return f"{seconds / period * 100:.3f}%"


def render(weeks):
    """Build the SVG for a list of weeks, each a 7-slot list of levels or None."""
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
        f'<path transform="translate(12 119.08)" fill="#ffbe73" d="{CAPTION}"/>',
        "</svg>",
    ])


if __name__ == "__main__":
    login, out = sys.argv[1], sys.argv[2]
    with open(out, "w") as f:
        f.write(render(fetch_weeks(login, os.environ["GITHUB_TOKEN"])))
