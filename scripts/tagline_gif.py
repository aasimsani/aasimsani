"""Render the README taglines with the website's block-glyph dissolve, as a looping GIF.

Usage:
  uv run --no-project --with pillow python scripts/tagline_gif.py dist/tagline.gif

The effect copies the hero name's anime.js call in the site's Hero.astro:
scrambleText({ chars: "blocks", from: "center", perturbation: 0.4, revealRate: 9,
settleDuration: 700 }), which refreshes its noise glyphs 30 times a second. The
README version runs about twice as fast (revealRate 20, settleDuration 350), because
a rotating tagline that plays at the site's pace felt slow.
"""

import math
import random
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

LINES = ["2x Founder 🚀", "Building Taxwire 💰", "Foodie 🍜", "Bookworm 📚", "Cyclist 🚴", "Occasionally creating stakeholder value 📈"]
W, H = 648, 60
SIZE, BASELINE = 28, 40
FRAME_MS = 40
HOLD_MS, GAP_MS = 600, 60
CREAM, SKY_TOP, SKY_BOT = (236, 228, 212), (11, 15, 36), (43, 23, 64)
BLOCKS = [chr(c) for c in range(0x2580, 0x25A0)]
GEIST_URL = "https://github.com/google/fonts/raw/main/ofl/geist/Geist%5Bwght%5D.ttf"

# Pixel sprites stand in for the emoji. They use the same format as the site's
# src/scripts/companion/sprites.ts: one character per pixel, "." transparent.
SPRITE_PX = 2
SPRITE_PAL = {
    "o": "#0a0c18", "W": "#ece4d4", "w": "#bdb4cc", "T": "#5fd8c6", "t": "#2f8f84", "A": "#ff9a3c",
    "Y": "#ffe08a", "R": "#d4364f", "G": "#c9a45a", "g": "#e8c98a", "K": "#3f6e5a", "B": "#9a7050",
    "N": "#f2dca0", "L": "#0a66c2", "Q": "#9690b0",
    # The cyclist is the site's wanderer, in its "Normal human" colors.
    "C": "#2e3f74", "c": "#5070b8", "d": "#18203f", "f": "#06070f", "e": "#ffe08a", "s": "#d4364f",
}
SPRITES = {
    "🚀": [
        ".....oo.....",
        "....oWWo....",
        "...oWWWWo...",
        "...oWTTWo...",
        "...oWTtWo...",
        "...oWWWWo...",
        "...owWWWo...",
        "..ooWWWWoo..",
        ".oRowWWWoRo.",
        ".oRRowWoRRo.",
        ".oRo.oo.oRo.",
        ".....AA.....",
        "....AYYA....",
        ".....AA.....",
    ],
    "💰": [
        "....oooo....",
        "...oGggGo...",
        "....oGGo....",
        "...ooGGoo...",
        "..oGggGGGo..",
        ".oGgGGGGGGo.",
        ".oGGGKKGGGo.",
        ".oGGKGGGGGo.",
        ".oGGGKKGGGo.",
        ".oGGGGGKGGo.",
        ".oGGGKKGGGo.",
        ".oGGGGGGGGo.",
        "..oGGGGGGo..",
        "...oooooo...",
    ],
    "🍜": [
        "...w..w..w..",
        "..w..w..w...",
        "...w..w..w..",
        "..w..w..w...",
        "..........BB",
        "........BB..",
        "......BB....",
        "oooooooooooo",
        "oNYYNNNTNNNo",
        "oRRRRRRRRRRo",
        ".oRWRWRWRRo.",
        ".oRRRRRRRRo.",
        "..oRRRRRRo..",
        "...oooooo...",
    ],
    "📚": [
        "............",
        "............",
        "..oooooooo..",
        "..oRRRRRRWo.",
        "..oRAAAARWo.",
        "..oooooooo..",
        ".oooooooooo.",
        ".oWTTTTTTTTo",
        ".oWTttttTTTo",
        ".oooooooooo.",
        "oooooooooo..",
        "oAAAAAAAAWo.",
        "oAYYYAAAAWo.",
        "oooooooooo..",
    ],
    "🚴": [
        ".........oooo.....",
        "........oCCCCo....",
        "........oCffCo....",
        "........ofefeo....",
        "....ssssosssso....",
        "........occcWW....",
        "......ooodd.T.....",
        "..QQQ..T.d..TQQQ..",
        ".Q...Q.T.dTTQT..Q.",
        "Q.....QT.T.Q.T...Q",
        "Q..WTTTTWd.Q..W..Q",
        "Q.....Q....Q.....Q",
        ".Q...Q......Q...Q.",
        "..QQQ........QQQ..",
    ],
    "📈": [
        "............",
        "oooooooooooo",
        "oWWWWWWWWWAo",
        "oWwWwWwWwAWo",
        "oWWWWWWWAAWo",
        "oWwWAwWAwWWo",
        "oWWAWAAWWWWo",
        "oWAWwWwWwWWo",
        "oAWWWWWWWWWo",
        "oWwWwWwWwWWo",
        "oWWWWWWWWWWo",
        "oooooooooooo",
        "............",
        "............",
    ],
}

# Each block element as rectangles in eighths of its cell: (x0, y0, x1, y1).
QUAD = {"ul": (0, 0, 4, 4), "ur": (4, 0, 8, 4), "ll": (0, 4, 4, 8), "lr": (4, 4, 8, 8)}
SHAPES = {
    "▀": [(0, 0, 8, 4)], "▐": [(4, 0, 8, 8)], "▔": [(0, 0, 8, 1)], "▕": [(7, 0, 8, 8)],
    **{chr(0x2581 + i): [(0, 7 - i, 8, 8)] for i in range(8)},  # ▁ to █
    **{chr(0x2589 + i): [(0, 0, 7 - i, 8)] for i in range(7)},  # ▉ to ▏
    "▖": [QUAD["ll"]], "▗": [QUAD["lr"]], "▘": [QUAD["ul"]], "▝": [QUAD["ur"]],
    "▙": [QUAD["ul"], QUAD["ll"], QUAD["lr"]], "▚": [QUAD["ul"], QUAD["lr"]],
    "▛": [QUAD["ul"], QUAD["ur"], QUAD["ll"]], "▜": [QUAD["ul"], QUAD["ur"], QUAD["lr"]],
    "▞": [QUAD["ur"], QUAD["ll"]], "▟": [QUAD["ur"], QUAD["ll"], QUAD["lr"]],
}
SHADES = {"░": 0.25, "▒": 0.5, "▓": 0.75}


def fetch(url, name):
    path = Path(tempfile.gettempdir()) / name
    if not path.exists():
        urllib.request.urlretrieve(url, path)
    return str(path)


def scramble_times(n, rng, rate, settle, perturbation, reverse=False):
    """Return per-character (start, end) fractions, following anime.js scrambleText."""
    duration = (n - 1) * 1000 / rate + settle
    settle_ratio = settle / duration
    spacing = (1 - settle_ratio) / n
    step = 1000 / (30 * duration)
    ref = (n - 1) / 2
    order = [0] * n
    for rank, i in enumerate(sorted(range(n), key=lambda i: abs(i - ref))):
        order[i] = n - 1 - rank if reverse else rank
    scale = perturbation * settle_ratio
    times = []
    for c in range(n):
        start = order[c] * spacing + (rng.uniform(-1, 1) * scale if scale else 0)
        end = math.ceil((start + settle_ratio + (rng.uniform(-1, 1) * scale if scale else 0)) / step) * step
        times.append((start, end))
    return duration, step, times


def main(out):
    geist = ImageFont.truetype(fetch(GEIST_URL, "Geist-wght.ttf"), SIZE)
    geist.set_variation_by_axes([600])
    sky = Image.new("RGB", (W, H))
    for y in range(H):
        t = y / (H - 1)
        sky.paste(tuple(round(a + (b - a) * t) for a, b in zip(SKY_TOP, SKY_BOT)), (0, y, W, y + 1))

    def sprite(ch):
        rows = SPRITES[ch]
        im = Image.new("RGBA", (len(rows[0]), len(rows)))
        for y, row in enumerate(rows):
            for x, k in enumerate(row):
                if k != ".":
                    im.putpixel((x, y), ImageColor.getrgb(SPRITE_PAL[k]))
        return im.resize((im.width * SPRITE_PX, im.height * SPRITE_PX), Image.Resampling.NEAREST)

    def block(draw, ch, x, w):
        top, h = BASELINE - SIZE * 0.82, SIZE
        if ch in SHADES:
            for yy in range(int(top), int(top + h), 2):
                for xx in range(int(x), int(x + w), 2):
                    if ((xx // 2 * 7 + yy // 2 * 3) % 4) < SHADES[ch] * 4:
                        draw.rectangle((xx, yy, xx + 1, yy + 1), fill=CREAM)
            return
        for x0, y0, x1, y1 in SHAPES[ch]:
            draw.rectangle((x + w * x0 / 8, top + h * y0 / 8, x + w * x1 / 8 - 1, top + h * y1 / 8 - 1), fill=CREAM)

    frames, durations = [], []
    for li, line in enumerate(LINES):
        rng = random.Random(li + 1)
        chars = list(line)
        glyphs = {ch: sprite(ch) for ch in chars if ch in SPRITES}
        widths = [glyphs[ch].width + 4 if ch in glyphs else geist.getlength(ch) for ch in chars]
        x0 = (W - sum(widths)) / 2
        xs = [x0 + sum(widths[:i]) for i in range(len(chars))]
        noise = [rng.choice(BLOCKS) for _ in chars]

        def frame(shown):
            im = sky.copy()
            d = ImageDraw.Draw(im)
            for ch, x, w, s in zip(chars, xs, widths, shown):
                if s == "settled":
                    if ch in glyphs:
                        im.paste(glyphs[ch], (round(x + 2), BASELINE - 24), glyphs[ch])
                    else:
                        d.text((x, BASELINE), ch, font=geist, fill=CREAM, anchor="ls")
                elif s:
                    block(d, s, x, w)
            return im

        # The line decodes in from the center, holds, then dissolves out from its edges.
        phases = [
            (scramble_times(len(chars), rng, 20, 350, 0.4), "in"),
            (scramble_times(len(chars), rng, 90, 100, 0.4, reverse=True), "out"),
        ]
        for (duration, step, times), kind in phases:
            last_step = -1
            for t_ms in range(0, int(duration) + FRAME_MS, FRAME_MS):
                v = min(t_ms / duration, 1)
                cur = int(v / step)
                if cur != last_step:
                    last_step = cur
                    noise = [rng.choice(BLOCKS) for _ in chars]
                shown = []
                for c, ch in enumerate(chars):
                    start, end = times[c]
                    before, after = (None, "settled") if kind == "in" else ("settled", None)
                    if ch == " ":
                        shown.append(None)
                    elif v >= end or v >= 1:  # anime.js snaps every character to its final state at the end.
                        shown.append(after)
                    elif kind == "in" and v < start:
                        shown.append(noise[c])  # anime.js shows noise glyphs before the reveal wave arrives.
                    elif v < start:
                        shown.append(before)
                    else:
                        shown.append(noise[c])
                frames.append(frame(shown))
                durations.append(FRAME_MS)
            if kind == "in":
                durations[-1] = HOLD_MS
        durations[-1] = GAP_MS

    # Every frame shares one palette. Pillow's optimizer reuses pixels from the previous
    # frame by palette index, so per-frame palettes would paint those pixels the wrong color.
    sample = Image.new("RGB", (W, H * len(frames)))
    for i, f in enumerate(frames):
        sample.paste(f, (0, H * i))
    palette = sample.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True)
    print(f"{len(frames)} frames, {Path(out).stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main(sys.argv[1])
