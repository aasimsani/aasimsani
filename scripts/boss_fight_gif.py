"""Render the website's After-hours boss fight as a looping GIF for the README.

Usage:
  uv run --no-project --with pillow --with numpy python scripts/boss_fight_gif.py \
    ../aasimsani.github.io dist/boss-fight.gif

The sprites come straight from the site's src/scripts/companion/sprites.ts. The
motion follows its engine.ts, flattened onto one straight road, so the wanderer
walks right and fights each mini-boss in page order, then the AI Slop PR.

Like the site, the world draws in chunky 2x2 blocks while the road, lanterns,
characters and effects draw on the finer 2x grid. The effects are the site's
own PixelFX modules, which scripts/bake_fx.mjs steps in Node and hands over as
RGBA frames.
"""

import base64
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

# The world is W x H world pixels, and the canvas is twice that on the 2x grid.
W, H = 324, 36
GW, GH = W * 2, H * 2
ROAD = 31
# The site steps its world 30 times a second. The GIF keeps every second step at 60 ms.
STEPS_PER_FRAME, FRAME_MS = 2, 60
SWING_EVERY = 12
WALK = 1.5
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/silkscreen/Silkscreen-Regular.ttf"

# The night palette from the site's src/styles/global.css.
COL = {
    "bg": "#0d1024", "skyTop": "#0b0f24", "skyBot": "#2b1740", "star": "#cfd8ff", "far": "#151b39",
    "rock": "#1f2a4d", "rockHi": "#34446f", "roadHi": "#9a7050", "road": "#5e4033", "roadLo": "#1c1220",
    "lantern": "#ffb347", "window": "#ffbf5e", "grass": "#3f6e5a", "grassHi": "#6fae7f", "moon": "#e9e4ff",
    "accent": "#ff9a3c", "teal": "#5fd8c6", "fx": "#ffffff", "text": "#ece4d4",
}
GLOW = "#ffaa50"

# Each mini-boss dies its own way, in MINI_BOSSES order, as in engine.ts's MINI_DEATHS. `vanish` is the
# window (seconds) in which the body fades. Without one, the effect's own actorAlpha decides.
MINI_DEATHS = [
    ("implosion", (0.3, 1.0)), ("soulRise", None), ("dissolveBurn", None), ("shatter", None),
    ("smite", (0.4, 0.55)), ("smokeBomb", (0.8, 0.95)), ("lightningStrike", (0.6, 0.75)),
]
TICK = 1 / 30

# A roadside lantern on the 2x grid, from engine.ts's LAMP.
LAMP = ["...ooo...", "..oRRRo..", ".oRrrrRo.", "ooooooooo", "oFGGFGGFo", "oFGgFgGFo", "oFGgFgGFo", "oFGGFGGFo",
        "ooooooooo", *["...oPpo.."] * 15, "..ooooo.."]


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


def bake(site, specs):
    """Run bake_fx.mjs on the effect specs and decode each frame into a float RGBA array."""
    script = Path(__file__).with_name("bake_fx.mjs")
    out = subprocess.run(["node", str(script), site], input=json.dumps(specs), capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    for fx in data["fx"].values():
        fx["frames"] = [f and (f["x"], f["y"], np.frombuffer(base64.b64decode(f["rgba"]), np.uint8).reshape(f["h"], f["w"], 4).astype(float))
                        for f in fx["frames"]]
    return data


def white(pal):
    return {k: "#ffffff" for k in pal}


class Canvas:
    """A float RGB buffer on the 2x grid. px and glow take world pixels offset by the camera; apx, sprite
    and blit take 2x-grid pixels."""

    def __init__(self, sky):
        self.a = sky.copy()
        self.ox = 0.0

    def apx(self, x, y, c, w=1, h=1, alpha=1.0):
        x, y = js_round(x), js_round(y)
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, GW), min(y + h, GH)
        if x0 < x1 and y0 < y1:
            reg = self.a[y0:y1, x0:x1]
            reg += (rgb(c) - reg) * alpha

    def px(self, x, y, c, w=1, h=1, alpha=1.0):
        self.apx(js_round(x - self.ox) * 2, js_round(y) * 2, c, w * 2, h * 2, alpha)

    def glow(self, x, y, r, a, c=GLOW):
        """Add a radial light, like the engine's "lighter" composite."""
        if a <= 0:
            return
        cx, cy, r = (x - self.ox) * 2, y * 2, r * 2
        x0, x1 = max(int(cx - r), 0), min(int(cx + r) + 1, GW)
        y0, y1 = max(int(cy - r), 0), min(int(cy + r) + 1, GH)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        k = np.clip(1 - np.hypot(xx + 0.5 - cx, yy + 0.5 - cy) / r, 0, 1) * a
        self.a[y0:y1, x0:x1] = np.minimum(self.a[y0:y1, x0:x1] + k[..., None] * rgb(c), 255)

    def sprite(self, rows, left, top, d, pal, alpha=1.0):
        for r, row in enumerate(rows):
            for c, k in enumerate(row):
                if k != "." and k in pal:
                    self.apx(left + c if d > 0 else left + len(row) - 1 - c, top + r, pal[k], alpha=alpha)

    def blit(self, frame, x, y):
        """Draw one baked PixelFX frame with its origin at (x, y), source-over like drawImage."""
        if frame is None:
            return
        fx, fy, img = frame
        x, y = x + fx, y + fy
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + img.shape[1], GW), min(y + img.shape[0], GH)
        if x0 >= x1 or y0 >= y1:
            return
        src = img[y0 - y:y1 - y, x0 - x:x1 - x]
        reg = self.a[y0:y1, x0:x1]
        reg += (src[..., :3] - reg) * (src[..., 3:] / 255)


def paint_sky():
    t = np.linspace(0, 1, GH)[:, None, None]
    return np.broadcast_to(rgb(COL["skyTop"]) * (1 - t) + rgb(COL["skyBot"]) * t, (GH, GW, 3)).copy()


def hash2(x, y):
    return ((js_round(x) * 73856093) ^ (js_round(y) * 19349663)) % 997


def render(site, out):
    sp = load_sprites(site)
    rand = random.Random(7)
    look = sp["LOOKS"][1]  # "Normal human", the site's default stop: the wanderer with a red scarf.
    legs = sp["LEGS"]
    minis = sp["MINI_BOSSES"]
    assert len(minis) == len(MINI_DEATHS), "engine.ts has a death for each mini-boss"

    enemies = []
    for i, m in enumerate(minis):
        enemies.append({"tier": "mini", "m": m, "i": i, "x": 150 + i * 100, "hp": 3, "max": 3, "rows": len(m["frames"][0])})
    enemies.append({"tier": "boss", "x": 150 + len(minis) * 100 + 40, "hp": 8, "max": 8, "rows": len(sp["SLOP_PR"][0])})
    for i, e in enumerate(enemies):
        e.update(alive=True, dying=0, flash=0, kx=0.0, phase=i * 1.7, engaged=False, timer=0, telegraph=0, death=None, glitch=None)

    # The effects engine.ts's damage() and say() play, at the sizes and palettes it passes.
    specs = [{"key": f"hit{i}", "mod": "critHit", "opts": {"height": e["rows"] / 2, "palette": "EMBER", "paletteFrom": 1}} for i, e in enumerate(enemies)]
    specs += [{"key": f"death{i}", "mod": mod, "actor": f"mini:{i}", "opts": {}} for i, (mod, _) in enumerate(MINI_DEATHS)]
    specs += [
        {"key": "glitch", "mod": "glitch", "actor": "slop", "opts": {"palette": "SLOP"}, "stopAt": 39},
        {"key": "disintegrate", "mod": "disintegrate", "actor": "slop", "opts": {"palette": "SLOP"}},
        {"key": "boom", "mod": "smallExplosion", "opts": {"size": 1, "palette": "SLOP"}},
    ]
    baked = bake(site, specs)
    FX, ramps = baked["fx"], baked["ramps"]

    sky = paint_sky()
    stars = [(rand.random() * W * 3, rand.random() * (ROAD - 6), rand.random() * 6.28, 0.6 + rand.random() * 2) for _ in range(45)]
    towers = []
    for i in range(9):
        w, h = 6 + rand.randrange(8), 8 + rand.randrange(16)
        towers.append((i * 44 + rand.randrange(20), w, h, [(rand.randrange(w - 2) + 1, rand.randrange(h - 3) + 2) for _ in range(w * h // 18)]))
    lanterns = [{"x": x, "lit": 0.0} for x in range(40, enemies[-1]["x"] + 200, 64)]
    end_x = enemies[-1]["x"] - 16  # He holds his ground while the slop crumbles and the arena blows.

    hero = {"x": 40.0, "dir": 1, "speed": 0.0, "phase": 0.0, "blink": 0, "atk": -1, "atkLen": 7, "target": None, "hurt": 0, "cool": 10}
    scarf = [{"x": 36.0, "y": ROAD - 10.0, "px": 36.0, "py": ROAD - 10.0} for _ in range(11)]
    sparks, shots, streaks, live, later = [], [], [], [], []
    hud = {"name": "", "hp": 0, "max": 0, "note": "", "noteFor": 0, "say": "", "sayFor": 0}
    shake, time, freeze = 0, 0, 0

    def spark(x, y, vx, vy, life, c):
        if len(sparks) < 220:
            sparks.append({"x": x, "y": y, "vx": vx, "vy": vy, "life": life, "max": life, "c": c})

    def play(key, x, y):
        fx = {"fx": FX[key], "k": 0, "x": x, "y": y}
        live.append(fx)
        return fx

    def lift_of(e):
        return 12 if e["tier"] == "mini" and e["m"]["flying"] else 0

    def say(e, line):
        hud.update(say=sp["SLOP_LINES"][line % len(sp["SLOP_LINES"])], sayFor=70 if line == 0 else 60)
        # The slop tears and color-splits for as long as its speech bubble is up.
        if e["alive"] and not e["glitch"]:
            e["glitch"] = play("glitch", e["x"], ROAD)

    def damage(e):
        nonlocal shake, freeze
        e["hp"] -= 1
        e["flash"], e["kx"] = 3, hero["dir"] * 1.5
        shake = max(shake, 2)
        play(f"hit{enemies.index(e)}", e["x"], ROAD - lift_of(e))
        freeze = max(freeze, 3)
        hud["hp"] = e["hp"]
        if e["hp"] > 0:
            return
        boss = e["tier"] == "boss"
        e["alive"], e["dying"] = False, 40 if boss else 14
        shake = 10 if boss else 5
        streaks.append({"x": e["x"], "y": ROAD - (14 if boss else 10), "life": 8, "dir": hero["dir"]})
        if boss:
            if e["glitch"] in live:
                live.remove(e["glitch"])
            e["glitch"] = None
            e["death"] = play("disintegrate", e["x"], ROAD)
            later.append((time + 78, lambda: (play("boom", e["x"], ROAD), set_shake(10))))
        else:
            e["death"] = play(f"death{e['i']}", e["x"], ROAD - lift_of(e))
        hud.update(note=("AI SLOP PR #4096" if boss else e["m"]["name"].upper()) + " DEFEATED", noteFor=70, name="", sayFor=0)

    def set_shake(v):
        nonlocal shake
        shake = v

    def step():
        nonlocal shake, time
        time += 1
        for fx in live[:]:
            fx["k"] += 1
            if fx["k"] >= len(fx["fx"]["frames"]):
                live.remove(fx)
        for job in [j for j in later if time >= j[0]]:
            later.remove(job)
            job[1]()
        for e in enemies:
            if e["death"] and e["death"] not in live:
                e["death"] = None
            if e["glitch"] and e["glitch"] not in live:
                e["glitch"] = None
        shake = max(0, shake - 1)
        hero["hurt"] = max(0, hero["hurt"] - 1)
        for e in enemies:
            e["flash"] = max(0, e["flash"] - 1)
            e["kx"] *= 0.7
            e["dying"] = max(0, e["dying"] - 1)

        # The nearest live enemy blocks the road. The hero walks on while its death plays, as on the site.
        blocker = next((e for e in enemies if e["alive"]), None)
        reach = 16 if blocker and blocker["tier"] == "boss" else 9
        stop = blocker["x"] - reach if blocker else end_x
        gap = stop - hero["x"]
        mag = min(abs(gap), WALK) * (0.3 if hero["atk"] >= 0 else 1)
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
                say(foe, 0)
        hero["cool"] = max(0, hero["cool"] - 1)
        if foe and hero["atk"] < 0 and hero["cool"] == 0:
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
                    say(boss, 1 + rand.randrange(len(sp["SLOP_LINES"]) - 1))
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
                    spark(hero["x"], ROAD - 8, (rand.random() - 0.5) * 1.5, -rand.random(), 14, COL["fx"] if k % 2 else "#ff6bd0")

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

        for lamp in lanterns:
            lamp["lit"] += ((1 if hero["x"] >= lamp["x"] else 0) - lamp["lit"]) * 0.08
            if lamp["lit"] > 0.6 and rand.random() < 0.03:
                spark(lamp["x"], ROAD - 10, (rand.random() - 0.5) * 0.1, -0.25, 40, COL["lantern"])
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

    w0, w1, w2, w3, w4, w5 = ramps["wood"]
    _, s1, s2, s3, _ = ramps["stone"]
    g0, g1, g2, g3 = ramps["grass"]

    def draw():
        cv = Canvas(sky)
        cam = hero["x"] - 96 + ((rand.random() - 0.5) * shake if shake else 0)

        def ax(x):
            return js_round((x - cam) * 2)

        for sx, sy, sp_, ss in stars:
            tw = math.sin(time * 0.05 * ss + sp_)
            if tw > -0.2:
                cv.px((sx - cam * 0.06) % W, sy, COL["star"], alpha=0.3 + 0.5 * tw * tw)
        cv.glow(W - 20, 9, 22, 0.12, "#c8beff")
        yy, xx = np.mgrid[0:GH, 0:GW]
        cv.a[np.hypot(xx + 0.5 - (W - 20) * 2, yy + 0.5 - 18) < 13] = rgb(COL["moon"])
        for dx, dy, s in ((-3, -1, 3), (2, 3, 2), (3, -4, 2)):
            cv.px(W - 20 + dx, 9 + dy, COL["far"], s, s, alpha=0.35)
        span = 9 * 44
        for tx, tw_, th, wins in towers:
            x = (tx - cam * 0.3) % span - 30
            cv.px(x, ROAD - th, COL["far"], tw_, th)
            for cx in range(0, tw_, 2):
                cv.px(x + cx, ROAD - th - 2, COL["far"], 1, 2)
            for wx, wy in wins:
                cv.px(x + wx, ROAD - th + wy, COL["window"], alpha=0.5 + 0.5 * math.sin(time * 0.05 + wx * 3 + wy))

        # The road is engine.ts's cobbled ledge on the 2x grid: rounded stones lit from the top-left, mortar
        # between them, and a jagged rock underside.
        cv.ox = cam
        shift, Y = js_round(cam * 2), ROAD * 2
        for X in range(GW):
            xa = X + shift
            h, c = hash2(xa, Y), xa % 7
            cv.apx(X, Y, w2 if c == 0 else w5)
            cv.apx(X, Y + 1, w1 if c == 0 else w5 if c == 1 else w4)
            cv.apx(X, Y + 2, w1 if c == 0 else w2 if c == 6 else w3)
            cv.apx(X, Y + 3, w0 if c == 0 else w2 if c > 4 else w3)
            cv.apx(X, Y + 4, w1)
            cv.apx(X, Y + 5, w0)
            drop = 2 + h % 5
            cv.apx(X, Y + 6, s3)
            cv.apx(X, Y + 7, s2, 1, drop)
            cv.apx(X, Y + 7 + drop, s1, 1, 2)
            if h % 11 == 0:
                cv.apx(X, Y - 1, g1)
            if h % 23 == 0:
                cv.apx(X, Y - 2, g2)
        for x in range(math.floor(cam), math.floor(cam) + W + 1):
            if hash2(x, ROAD) % 13 == 0:
                X, sway = ax(x), 1 if math.sin(time * 0.06 + x) > 0.4 else 0
                cv.apx(X - 2, Y - 1, g0, 5, 1)
                cv.apx(X - 1, Y - 2, g1, 3, 1)
                cv.apx(X - 2 + sway, Y - 4, g1, 1, 2)
                cv.apx(X + sway, Y - 5, g2, 1, 3)
                cv.apx(X + 2 + sway, Y - 3, g3, 1, 1)
        for lamp in lanterns:
            lit = lamp["lit"] > 0.5
            lp = {"o": "#0a0c18", "R": w4, "r": w3, "F": w2, "P": w3, "p": w1,
                  "G": COL["lantern"] if lit else ramps["roadDark"], "g": "#fff3c4" if lit else w1}
            cv.sprite(LAMP, ax(lamp["x"]) - 4, Y - len(LAMP), 1, lp)
        for lamp in lanterns:
            if lamp["lit"] > 0.05:
                cv.glow(lamp["x"] + 0.5, ROAD - 10, 12 + math.sin(time * 0.3 + lamp["x"]), 0.35 * lamp["lit"])

        for e in enemies:
            alpha = 1.0
            if e["death"]:
                # While a death effect runs, the body shows only for as long as the effect wants it.
                fx = e["death"]
                vanish = MINI_DEATHS[e["i"]][1] if e["tier"] == "mini" else None
                t = fx["k"] * TICK
                alpha = 1 - max(0, min(1, (t - vanish[0]) / (vanish[1] - vanish[0]))) if vanish else fx["fx"]["alpha"][fx["k"]]
                if alpha <= 0:
                    continue
            elif not e["alive"] or e["glitch"]:
                # The glitch effect draws the slop's body while it speaks.
                continue
            is_white = e["alive"] and (e["flash"] > 0 or e["telegraph"] % 4 > 1)
            d = 1 if hero["x"] > e["x"] else -1
            if e["tier"] == "mini":
                m = e["m"]
                frame = m["frames"][int((time + e["phase"] * 10) / 7) % len(m["frames"])]
                lift = 12 + js_round(math.sin(time * 0.08 + e["phase"]) * 2) if m["flying"] else 0
                cv.glow(e["x"], ROAD - 6 - lift, 16, 0.12 if e["alive"] else 0, "#ff5078")
                cv.sprite(frame, ax(e["x"] + e["kx"]) - len(frame[0]) // 2, (ROAD - lift) * 2 - len(frame), d, white(m["pal"]) if is_white else m["pal"], alpha)
            else:
                frame = sp["SLOP_PR"][int(time / 9) % 2]
                enraged = e["hp"] <= e["max"] / 2
                bob = js_round(math.sin(time * 0.06) * 1.5)
                cv.glow(e["x"], ROAD - 14, 30, 0.32 if enraged else 0.18, "#ff4fd8" if enraged else "#7fae9a")
                left, top = ax(e["x"] + e["kx"]) - len(frame[0]) // 2, (ROAD + bob) * 2 - len(frame)
                cv.sprite(frame, left, top, d, white(sp["SLOP_PAL"]) if is_white else sp["SLOP_PAL"], alpha)
                # The slop glitches. A few rows tear sideways every few frames, and more once it's enraged.
                if e["alive"] and time % (3 if enraged else 7) == 0:
                    for _ in range(4 if enraged else 2):
                        row = js_round(top + rand.random() * len(frame))
                        shift_x = js_round((rand.random() - 0.5) * (16 if enraged else 8))
                        th = 2 + int(rand.random() * 3)
                        x0, x1 = max(left - 4, 0), min(left + len(frame[0]) + 4, GW)
                        if 0 <= row < GH and x0 < x1:
                            strip = cv.a[row:row + th, x0:x1].copy()
                            d0, d1 = max(x0 + shift_x, 0), min(x1 + shift_x, GW)
                            cv.a[row:row + th, d0:d1] = strip[:, d0 - x0 - shift_x:d1 - x0 - shift_x]
                if e["telegraph"]:
                    cv.px(e["x"], ROAD - len(frame) / 2 - 6 + bob, COL["fx"], 1, 3)

        # The hero, following drawHero and drawWeapon in engine.ts.
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
            cv.apx(ax(n["x"]), js_round(n["y"] * 2), look["trail"][1] if i >= look["trailLength"] - 2 else look["trail"][0], 3 if i < 5 else 2, 2)
        leg = legs["lunge"] if lunging else legs["idle"] if not moving else legs["pass"] if passing else legs["stride"]
        L, T = ax(left), top * 2
        cv.sprite(leg, L, (feet - 2) * 2, d, pal)
        cv.sprite(look["body"][14:], L, T + 14, d, pal)
        cv.sprite(look["body"][:14], L + lean * 2, T, d, pal)
        hx, hy, c, gold = ax(left + 6 + lean + d * 3), (top + 9) * 2, look["weaponColor"], "#c9a45a"
        if p < 0:
            cv.apx(hx - d * 10, hy + 2, gold, 2, 2)
            for i in range(1, 9):
                cv.apx(hx - d * 10 - d * i * 0.5, hy + 3 + i, c)
        elif p < 0.4:
            cv.apx(hx - d * 4, hy - 8, gold, 2, 2)
            for i in range(1, 10):
                cv.apx(hx - d * 4 + (0 if d > 0 else 1), hy - 8 - i, c)
        elif p < 0.75:
            reach = 1 if p < 0.55 else 0.65
            a = -1.3
            while a <= 1.1:
                r = 12 + (2 if a > 0 else 0)
                x, y = hx + d * math.cos(a) * r * reach, hy + math.sin(a) * r
                cv.apx(x, y, COL["teal"] if a > 0.6 else COL["fx"])
                if p < 0.55:
                    cv.apx(x - d * 2, y, COL["teal"])
                a += 0.06
        else:
            cv.apx(hx, hy + 6, gold, 2, 2)
            for i in range(1, 10):
                cv.apx(hx + d * (1 + i), hy + 7 + (i >> 1), c)

        for fx in live:
            cv.blit(fx["fx"]["frames"][fx["k"]], ax(fx["x"]), js_round(fx["y"] * 2))

        for s in shots:
            X, Y = ax(s["x"]), js_round(s["y"] * 2)
            if s["kind"] == "dash":
                cv.apx(X - 5, Y, COL["fx"], 10, 1)
                cv.apx(X - 5, Y + 1, ramps["fxLo"], 10, 1)
            else:
                cv.apx(X, Y - 3, sp["SLOP_PAL"]["Y"], 1, 7)
                cv.apx(X - 3, Y, sp["SLOP_PAL"]["Y"], 7, 1)
                cv.apx(X, Y, "#ffffff")
        for k in streaks[:]:
            for j in range(-18, 19):
                X, Y = ax(k["x"]) + j * k["dir"], js_round(k["y"] * 2) + js_round(j * 0.55)
                cv.apx(X, Y, COL["fx"], alpha=k["life"] / 8)
                cv.apx(X, Y + 1, COL["teal"], alpha=k["life"] / 8)
            k["life"] -= 1
            if k["life"] <= 0:
                streaks.remove(k)
        for s in sparks:
            X, Y, a = ax(s["x"]), js_round(s["y"] * 2), min(1, s["life"] / s["max"] * 1.5)
            cv.apx(X, Y, s["c"], 2, 1, alpha=a)
            cv.apx(X - math.copysign(1, s["vx"]) * (s["vx"] != 0), Y - math.copysign(1, s["vy"] or 1), s["c"], alpha=a)

        img = Image.fromarray(cv.a.clip(0, 255).astype(np.uint8))
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
            x0 = min(ax(enemies[-1]["x"]) + 40, GW - 8 - width)
            g.rectangle((x0, 4, x0 + width, 24), fill=COL["text"])
            g.text((x0 + 8, 7), text, font=font, fill=COL["bg"])
        return img

    font_path = Path(tempfile.gettempdir()) / "Silkscreen-Regular.ttf"
    if not font_path.exists():
        urllib.request.urlretrieve(FONT_URL, font_path)
    font = ImageFont.truetype(str(font_path), 16)

    frames = []
    after = 0
    while after < 15:
        for _ in range(STEPS_PER_FRAME):
            # A hit-stop holds the world still for a few steps, as in engine.ts's frame loop.
            if freeze > 0:
                freeze -= 1
            else:
                step()
        frames.append(draw())
        if not enemies[-1]["alive"] and not live and abs(hero["x"] - end_x) < 1:
            after += 1
    # Every frame shares one palette. Pillow's optimizer reuses pixels from the previous
    # frame by palette index, so per-frame palettes would paint those pixels the wrong color.
    sample = Image.new("RGB", (GW, GH * 30))
    for i, f in enumerate(frames[:: max(1, len(frames) // 30)][:30]):
        sample.paste(f, (0, GH * i))
    palette = sample.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0, optimize=True, disposal=1)
    print(f"{len(frames)} frames, {Path(out).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
