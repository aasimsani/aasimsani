"""Render the website's After-hours boss fight as a looping GIF for the README.

Usage:
  uv run --no-project --with pillow --with numpy python scripts/boss_fight_gif.py \
    ../aasimsani.github.io dist/boss-fight.gif

The sprites come straight from the site's src/scripts/companion/sprites.ts. The
motion follows its engine.ts, flattened onto one straight road, so the wanderer
walks right and fights each mini-boss in page order, then the AI Slop PR.
"""

import json
import math
import random
import subprocess
import sys
import tempfile
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, SCALE = 324, 36, 2
ROAD = 31
# The site steps its world once per 60 Hz frame. The GIF keeps every third step
# at 50 ms, which plays at the site's speed in a third of the frames.
STEPS_PER_FRAME, FRAME_MS = 3, 50
SWING_EVERY = 22
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/silkscreen/Silkscreen-Regular.ttf"

# The night palette from the site's src/styles/global.css.
COL = {
    "bg": "#0d1024", "skyTop": "#0b0f24", "skyBot": "#2b1740", "star": "#cfd8ff", "far": "#151b39",
    "rock": "#1f2a4d", "rockHi": "#34446f", "roadHi": "#9a7050", "road": "#5e4033", "roadLo": "#1c1220",
    "lantern": "#ffb347", "window": "#ffbf5e", "grass": "#3f6e5a", "grassHi": "#6fae7f", "moon": "#e9e4ff",
    "accent": "#ff9a3c", "teal": "#5fd8c6", "fx": "#ffffff", "text": "#ece4d4",
}
GLOW = "#ffaa50"


def js_round(v):
    return math.floor(v + 0.5)


@lru_cache(maxsize=None)
def rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float)


def load_sprites(site):
    url = (Path(site) / "src/scripts/companion/sprites.ts").resolve().as_uri()
    js = f"const s = await import({json.dumps(url)}); console.log(JSON.stringify(s));"
    out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def white(pal):
    return {k: "#ffffff" for k in pal}


class Canvas:
    """A float RGB buffer with the engine's px, glow and sprite helpers, offset by a camera."""

    def __init__(self, sky):
        self.a = sky.copy()
        self.ox = 0.0

    def px(self, x, y, c, w=1, h=1, alpha=1.0):
        x, y = js_round(x - self.ox), js_round(y)
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
        if x0 < x1 and y0 < y1:
            reg = self.a[y0:y1, x0:x1]
            reg += (rgb(c) - reg) * alpha

    def glow(self, x, y, r, a, c=GLOW):
        """Add a radial light, like the engine's "lighter" composite."""
        if a <= 0:
            return
        cx = x - self.ox
        x0, x1 = max(int(cx - r), 0), min(int(cx + r) + 1, W)
        y0, y1 = max(int(y - r), 0), min(int(y + r) + 1, H)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        k = np.clip(1 - np.hypot(xx + 0.5 - cx, yy + 0.5 - y) / r, 0, 1) * a
        self.a[y0:y1, x0:x1] = np.minimum(self.a[y0:y1, x0:x1] + k[..., None] * rgb(c), 255)

    def sprite(self, rows, left, top, d, pal, alpha=1.0):
        for r, row in enumerate(rows):
            for c, k in enumerate(row):
                if k != "." and k in pal:
                    self.px(left + c if d > 0 else left + len(row) - 1 - c, top + r, pal[k], alpha=alpha)


def paint_sky():
    t = np.linspace(0, 1, H)[:, None, None]
    return np.broadcast_to(rgb(COL["skyTop"]) * (1 - t) + rgb(COL["skyBot"]) * t, (H, W, 3)).copy()


def hash2(x, y):
    return ((js_round(x) * 73856093) ^ (js_round(y) * 19349663)) % 997


def render(site, out):
    sp = load_sprites(site)
    rand = random.Random(7)
    look = sp["LOOKS"][1]  # "Normal human", the site's default stop: the wanderer with a red scarf.
    legs = sp["LEGS"]
    sky = paint_sky()
    stars = [(rand.random() * W * 3, rand.random() * (ROAD - 6), rand.random() * 6.28, 0.6 + rand.random() * 2) for _ in range(45)]
    towers = []
    for i in range(9):
        w, h = 6 + rand.randrange(8), 8 + rand.randrange(16)
        towers.append((i * 44 + rand.randrange(20), w, h, [(rand.randrange(w - 2) + 1, rand.randrange(h - 3) + 2) for _ in range(w * h // 18)]))

    enemies = []
    for i, m in enumerate(sp["MINI_BOSSES"]):
        enemies.append({"tier": "mini", "m": m, "x": 150 + i * 120, "hp": 3, "max": 3})
    enemies.append({"tier": "boss", "x": 150 + 7 * 120 + 40, "hp": 8, "max": 8})
    for i, e in enumerate(enemies):
        e.update(alive=True, dying=0, flash=0, kx=0.0, phase=i * 1.7, engaged=False, timer=0, telegraph=0)
    lanterns = [{"x": x, "lit": 0.0} for x in range(40, enemies[-1]["x"] + 200, 64)]
    end_x = enemies[-1]["x"] + 90

    hero = {"x": 40.0, "dir": 1, "speed": 0.0, "phase": 0.0, "blink": 0, "atk": -1, "atkLen": 7, "target": None, "hurt": 0, "cool": 10}
    scarf = [{"x": 36.0, "y": ROAD - 10.0, "px": 36.0, "py": ROAD - 10.0} for _ in range(11)]
    sparks, shots, streaks = [], [], []
    hud = {"name": "", "hp": 0, "max": 0, "note": "", "noteFor": 0, "say": "", "sayFor": 0}
    shake, time = 0, 0

    def spark(x, y, vx, vy, life, c):
        if len(sparks) < 220:
            sparks.append({"x": x, "y": y, "vx": vx, "vy": vy, "life": life, "max": life, "c": c})

    def damage(e):
        nonlocal shake
        e["hp"] -= 1
        e["flash"], e["kx"] = 3, hero["dir"] * 1.5
        shake = max(shake, 2)
        for i in range(6):
            spark(e["x"], ROAD - 6, hero["dir"] * (0.4 + rand.random()), -rand.random() * 0.9, 12, COL["fx"] if i % 2 else COL["teal"])
        hud["hp"] = e["hp"]
        if e["hp"] > 0:
            return
        boss = e["tier"] == "boss"
        e["alive"], e["dying"] = False, 40 if boss else 14
        shake = 10 if boss else 5
        streaks.append({"x": e["x"], "y": ROAD - (14 if boss else 10), "life": 8, "dir": hero["dir"]})
        pal = sp["SLOP_PAL"] if boss else e["m"]["pal"]
        colors = [pal["P"], pal["E"], pal["Y"], pal["G"]] if boss else [pal["A"], pal["a"], COL["lantern"]]
        for i in range(90 if boss else 40):
            spark(e["x"], ROAD - 8, (rand.random() - 0.5) * (4 if boss else 2.2), -rand.random() * 2.2, 24 + rand.random() * 24, colors[i % len(colors)])
        hud.update(note=("AI SLOP PR #4096" if boss else e["m"]["name"].upper()) + " DEFEATED", noteFor=70, name="", sayFor=0)

    def step():
        nonlocal shake, time
        time += 1
        shake = max(0, shake - 1)
        hero["hurt"] = max(0, hero["hurt"] - 1)
        for e in enemies:
            e["flash"] = max(0, e["flash"] - 1)
            e["kx"] *= 0.7
            e["dying"] = max(0, e["dying"] - 1)

        # A dying enemy still blocks the road, so the hero waits for it to fade out.
        blocker = next((e for e in enemies if e["alive"] or e["dying"]), None)
        reach = 16 if blocker and blocker["tier"] == "boss" else 9
        stop = blocker["x"] - reach if blocker else end_x
        gap = stop - hero["x"]
        mag = min(abs(gap), 1.1) * (0.3 if hero["atk"] >= 0 else 1)
        hero["x"] += math.copysign(mag, gap)
        hero["speed"] = hero["speed"] * 0.7 + mag * 0.3
        hero["phase"] += hero["speed"] / 2.4
        if hero["blink"]:
            hero["blink"] -= 1
        elif rand.random() < 0.008:
            hero["blink"] = 4

        foe = blocker if blocker and abs(gap) < 1.2 else None
        if foe and not foe["engaged"]:
            foe["engaged"] = True
            hud.update(name="AI SLOP PR #4096" if foe["tier"] == "boss" else foe["m"]["name"].upper(), hp=foe["hp"], max=foe["max"])
            if foe["tier"] == "boss":
                hud.update(say=sp["SLOP_LINES"][0], sayFor=70)
        hero["cool"] = max(0, hero["cool"] - 1)
        if foe and foe["alive"] and hero["atk"] < 0 and hero["cool"] == 0:
            hero.update(atk=0, target=foe, cool=SWING_EVERY)
        if hero["atk"] >= 0:
            hero["atk"] += 1
            tgt = hero["target"]
            if tgt["alive"] and hero["atk"] == max(2, int(hero["atkLen"] * 0.45)):
                damage(tgt)
            if hero["atk"] >= hero["atkLen"]:
                hero.update(atk=-1, target=None)

        # The final boss telegraphs for 16 steps, then throws em-dashes and sparkles.
        boss = enemies[-1]
        if boss["alive"] and boss["engaged"]:
            boss["timer"] += 1
            every = 50 if boss["hp"] <= boss["max"] / 2 else 80
            if boss["timer"] % every == every - 16:
                boss["telegraph"] = 16
                if rand.random() < 0.6:
                    hud.update(say=rand.choice(sp["SLOP_LINES"][1:]), sayFor=60)
            if boss["telegraph"] > 0:
                boss["telegraph"] -= 1
                if boss["telegraph"] == 0:
                    for i in range(5 if every == 50 else 3):
                        shots.append({"x": boss["x"] - 4, "y": ROAD - 16 - i * 3, "vx": (hero["x"] - boss["x"]) / 22 + (rand.random() - 0.5) * 0.3,
                                      "vy": -0.8 - rand.random() * 0.6, "kind": "sparkle" if i % 2 else "dash", "life": 60})
        for s in shots[:]:
            s["x"] += s["vx"]
            s["y"] += s["vy"]
            s["vy"] += 0.06
            s["life"] -= 1
            if s["life"] <= 0 or s["y"] > ROAD + 4:
                shots.remove(s)
            elif abs(s["x"] - hero["x"]) < 4 and abs(s["y"] - (ROAD - 8)) < 8:
                shots.remove(s)
                hero["hurt"], hero["x"], shake = 10, hero["x"] - 7, 4
                for k in range(8):
                    spark(hero["x"], ROAD - 8, (rand.random() - 0.5) * 1.5, -rand.random(), 14, COL["fx"] if k % 2 else sp["SLOP_PAL"]["E"])

        # The scarf is a verlet chain pinned at the neck, as in engine.ts.
        d = hero["dir"]
        scarf[0]["x"], scarf[0]["y"] = hero["x"] - d * 3.5, ROAD - 10
        wind = -d * (0.02 + hero["speed"] * 0.09) + math.sin(time * 0.06) * 0.035
        for i, n in enumerate(scarf[1:], 1):
            vx, vy = (n["x"] - n["px"]) * 0.9, (n["y"] - n["py"]) * 0.9
            n["px"], n["py"] = n["x"], n["y"]
            n["x"] += vx + wind
            n["y"] += vy + 0.06 - min(hero["speed"], 2) * 0.03 + math.sin(time * 0.15 + i) * 0.02
        for _ in range(3):
            for a, b in zip(scarf, scarf[1:]):
                dx, dy = b["x"] - a["x"], b["y"] - a["y"]
                f = (math.hypot(dx, dy) - 1.2) / (math.hypot(dx, dy) or 1)
                b["x"] -= dx * f
                b["y"] -= dy * f

        for l in lanterns:
            l["lit"] += ((1 if hero["x"] >= l["x"] else 0) - l["lit"]) * 0.08
            if l["lit"] > 0.6 and rand.random() < 0.03:
                spark(l["x"], ROAD - 10, (rand.random() - 0.5) * 0.1, -0.25, 40, COL["lantern"])
        for p in sparks[:]:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vy"] += 0.02
            p["vx"] *= 0.97
            p["life"] -= 1
            if p["life"] <= 0:
                sparks.remove(p)
        for k in ("noteFor", "sayFor"):
            hud[k] = max(0, hud[k] - 1)

    def draw():
        cv = Canvas(sky)
        cam = hero["x"] - 96 + ((rand.random() - 0.5) * shake if shake else 0)
        for sx, sy, sp_, ss in stars:
            tw = math.sin(time * 0.05 * ss + sp_)
            if tw > -0.2:
                cv.px((sx - cam * 0.06) % W, sy, COL["star"], alpha=0.3 + 0.5 * tw * tw)
        cv.glow(W - 20, 9, 22, 0.12, "#c8beff")
        yy, xx = np.mgrid[0:H, 0:W]
        cv.a[np.hypot(xx + 0.5 - (W - 20), yy + 0.5 - 9) < 6.5] = rgb(COL["moon"])
        for dx, dy, s in ((-3, -1, 3), (2, 3, 2), (3, -4, 2)):
            cv.px(W - 20 + dx, 9 + dy, COL["far"], s, s, alpha=0.35)
        span = 9 * 44
        for tx, tw_, th, wins in towers:
            x = (tx - cam * 0.3) % span - 30
            cv.px(x, ROAD - th, COL["far"], tw_, th)
            for wx, wy in wins:
                cv.px(x + wx, ROAD - th + wy, COL["window"], alpha=0.5 + 0.5 * math.sin(time * 0.05 + wx * 3 + wy))

        cv.ox = cam
        for x in range(math.floor(cam), math.floor(cam) + W + 1):
            h = hash2(x, ROAD)
            cv.px(x, ROAD, COL["roadHi"])
            cv.px(x, ROAD + 1, COL["roadLo"] if x % 4 == 0 else COL["road"])
            cv.px(x, ROAD + 2, COL["roadLo"] if (x + 2) % 4 == 0 else COL["road"])
            cv.px(x, ROAD + 3, COL["roadLo"])
            cv.px(x, ROAD + 4, COL["rock"], 1, H)
            cv.px(x, ROAD + 4 + 1 + h % 3, COL["rockHi"] if h % 5 == 0 else COL["rock"])
            if h % 9 == 0:
                cv.px(x, ROAD - 1, COL["grass"])
                cv.px(x + (1 if math.sin(time * 0.06 + x) > 0.4 else 0), ROAD - 2, COL["grassHi"])
        for l in lanterns:
            cv.px(l["x"], ROAD - 8, COL["roadLo"], 1, 8)
            cv.px(l["x"] - 1, ROAD - 11, COL["lantern"] if l["lit"] > 0.5 else COL["road"], 3, 3)
            cv.px(l["x"] - 1, ROAD - 12, COL["roadLo"], 3, 1)
            cv.glow(l["x"] + 0.5 - cam, ROAD - 9.5, 12 + math.sin(time * 0.3 + l["x"]), 0.35 * l["lit"])

        for e in enemies:
            if not e["alive"] and not e["dying"]:
                continue
            is_white = e["flash"] > 0 or e["telegraph"] % 4 > 1
            alpha = 1.0 if e["alive"] else e["dying"] / (40 if e["tier"] == "boss" else 14)
            d = 1 if hero["x"] > e["x"] else -1
            if e["tier"] == "mini":
                m = e["m"]
                frame = m["frames"][int((time + e["phase"] * 10) / 7) % len(m["frames"])]
                lift = 12 + js_round(math.sin(time * 0.08 + e["phase"]) * 2) if m["flying"] else 0
                cv.glow(e["x"] - cam, ROAD - 6 - lift, 16, 0.12 if e["alive"] else 0, "#ff5078")
                cv.sprite(frame, e["x"] - len(frame[0]) // 2 + e["kx"], ROAD - len(frame) - lift, d, white(m["pal"]) if is_white else m["pal"], alpha)
            else:
                frame = sp["SLOP_PR"][int(time / 9) % 2]
                enraged = e["hp"] <= e["max"] / 2
                bob = js_round(math.sin(time * 0.06) * 1.5)
                cv.glow(e["x"] - cam, ROAD - 14, 30, 0.32 if enraged else 0.18, "#ff4fd8" if enraged else "#7fae9a")
                left, top = e["x"] - len(frame[0]) // 2 + e["kx"], ROAD - len(frame) + bob
                cv.sprite(frame, left, top, d, white(sp["SLOP_PAL"]) if is_white else sp["SLOP_PAL"], alpha)
                # The slop glitches. A few rows tear sideways, and more once it's enraged.
                if e["alive"] and time % (3 if enraged else 7) == 0:
                    for _ in range(4 if enraged else 2):
                        row = js_round(top + rand.random() * len(frame))
                        # The tear only shifts the strip the boss covers, like the engine's drawImage call.
                        x0 = max(js_round(left - 2 - cam), 0)
                        x1 = min(x0 + len(frame[0]) + 4, W)
                        if 0 <= row < H - 1:
                            strip = cv.a[row:row + 2, x0:x1]
                            strip[:] = np.roll(strip, js_round((rand.random() - 0.5) * (8 if enraged else 4)), axis=1)
                if e["telegraph"]:
                    cv.px(e["x"], top - 6, COL["fx"], 1, 3)

        # The hero, following drawHero in engine.ts.
        d = hero["dir"]
        moving, fighting = hero["speed"] > 0.08, hero["atk"] >= 0
        passing = moving and math.floor(hero["phase"]) % 2 == 1
        breathe = 1 if not moving and not fighting and math.sin(time * 0.09) > 0.6 else 0
        left, feet = js_round(hero["x"]) - 6, ROAD - 1
        top = feet - 15 - (1 if passing else 0) + breathe
        p = hero["atk"] / hero["atkLen"] if fighting else -1
        lunging = 0.4 <= p < 0.75
        lean = d if lunging else 0
        pal = dict(look["pal"], e=look["pal"]["f"] if hero["blink"] else look["pal"]["e"])
        if hero["hurt"] > 0 and hero["hurt"] % 4 > 1:
            pal = white(pal)
        for i in range(look["trailLength"] - 1, 0, -1):
            n = scarf[i]
            cv.px(n["x"], n["y"], look["trail"][1] if i >= look["trailLength"] - 2 else look["trail"][0], 2 if i < 5 else 1, 1)
        leg = legs["lunge"] if lunging else legs["idle"] if not moving else legs["pass"] if passing else legs["stride"]
        cv.sprite(leg, left, feet - 2, d, pal)
        cv.sprite(look["body"][7:], left, top + 7, d, pal)
        cv.sprite(look["body"][:7], left + lean, top, d, pal)
        sx, sy, c = left + 6 + lean + d * 3, top + 9, look["weaponColor"]
        if p < 0:
            cv.px(sx - d * 5, sy + 1, "#c9a45a")
            for i in range(1, 5):
                cv.px(sx - d * 5 - d * i * 0.5, sy + 1 + i, c)
        elif p < 0.4:
            for i in range(5):
                cv.px(sx - d * 2, sy - 4 - i, c if i else "#c9a45a")
        elif p < 0.75:
            reach = 1 if p < 0.55 else 0.65
            a = -1.3
            while a <= 1.1:
                r = 6 + (1 if a > 0 else 0)
                x, y = sx + d * math.cos(a) * r * reach, sy + math.sin(a) * r
                cv.px(x, y, COL["teal"] if a > 0.6 else COL["fx"])
                if p < 0.55:
                    cv.px(x - d, y, COL["teal"])
                a += 0.12
        else:
            for i in range(5):
                cv.px(sx + d * i, sy + 3 + (i >> 1), c if i else "#c9a45a")

        for s in shots:
            if s["kind"] == "dash":
                cv.px(s["x"] - 2, s["y"], COL["fx"], 5, 1)
            else:
                cv.px(s["x"], s["y"] - 1, sp["SLOP_PAL"]["Y"], 1, 3)
                cv.px(s["x"] - 1, s["y"], sp["SLOP_PAL"]["Y"], 3, 1)
        for k in streaks[:]:
            for j in range(-9, 10):
                cv.px(k["x"] + j * k["dir"], k["y"] + j * 0.55, COL["fx"], alpha=k["life"] / 8)
                cv.px(k["x"] + j * k["dir"], k["y"] + j * 0.55 + 1, COL["teal"], alpha=k["life"] / 8)
            k["life"] -= 1
            if k["life"] <= 0:
                streaks.remove(k)
        for s in sparks:
            cv.px(s["x"], s["y"], s["c"], alpha=min(1, s["life"] / s["max"] * 1.5))

        img = Image.fromarray(cv.a.clip(0, 255).astype(np.uint8)).resize((W * SCALE, H * SCALE), Image.Resampling.NEAREST)
        g = ImageDraw.Draw(img)
        if hud["name"]:
            g.text((10, 5), hud["name"], font=font, fill=COL["accent"])
            for i in range(hud["max"]):
                g.rectangle((10 + i * 10, 22, 17 + i * 10, 26), fill=COL["accent"] if i < hud["hp"] else COL["far"], outline=COL["accent"])
        if hud["noteFor"]:
            g.text((10, 5), hud["note"], font=font, fill=COL["teal"])
        if hud["sayFor"] and enemies[-1]["alive"]:
            text = hud["say"].encode("ascii", "ignore").decode().strip(" -")
            # The bubble sits right of the boss, clear of the HUD and the hero, and stays inside the frame.
            width = g.textlength(text, font=font) + 16
            x0 = min((enemies[-1]["x"] - cam) * SCALE + 40, W * SCALE - 8 - width)
            x1 = x0 + width
            g.rectangle((x0, 4, x1, 24), fill=COL["text"])
            g.text((x0 + 8, 7), text, font=font, fill=COL["bg"])
        return img

    font_path = Path(tempfile.gettempdir()) / "Silkscreen-Regular.ttf"
    if not font_path.exists():
        urllib.request.urlretrieve(FONT_URL, font_path)
    font = ImageFont.truetype(str(font_path), 16)

    frames = []
    after = 0
    while after < 30:
        for _ in range(STEPS_PER_FRAME):
            step()
        frames.append(draw())
        if not enemies[-1]["alive"] and abs(hero["x"] - end_x) < 1:
            after += 1
    # Every frame shares one palette. Pillow's optimizer reuses pixels from the previous
    # frame by palette index, so per-frame palettes would paint those pixels the wrong color.
    sample = Image.new("RGB", (W * SCALE, H * SCALE * 20))
    for i, f in enumerate(frames[:: max(1, len(frames) // 20)][:20]):
        sample.paste(f, (0, H * SCALE * i))
    palette = sample.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0, optimize=True, disposal=1)
    print(f"{len(frames)} frames, {Path(out).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
