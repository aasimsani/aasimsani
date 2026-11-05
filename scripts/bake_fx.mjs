// Bake the website's PixelFX effects into RGBA frames for boss_fight_gif.py.
//
// Usage: node scripts/bake_fx.mjs <site> < specs.json > baked.json
//
// Each spec is { key, mod, opts, actor, stopAt }. `mod` names an effect the site's engine.ts plays,
// `actor` is "mini:<i>" or "slop" for effects that wrap a body, and `stopAt` is the step on which the
// engine calls stop(). The script steps each effect at the engine's 30 fps clock, the same way step()
// and draw() do, and composites every frame over transparency like effects.ts's Layer.flush(). It also
// prints the site's sprites and the wood, stone and grass ramps that engine.ts derives from the theme.
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const site = process.argv[2];
const load = (p) => import(pathToFileURL(join(site, "src/scripts", p)).href);

const sprites = await load("companion/sprites.ts");
const { actorOf, createFx, pocketPoof, TICK, TEAL, EMBER, SLOP } = await load("companion/effects.ts");
const { actorAlphaOf, createFrame, composite } = await load("pixelfx/core/index.js");
const MODS = {
  critHit: "impacts/crit-hit.js", implosion: "explosions/implosion.js", soulRise: "spawn/soul-rise.js",
  dissolveBurn: "spawn/dissolve-burn.js", shatter: "spawn/shatter-death.js", smite: "holy/smite.js",
  smokeBomb: "explosions/smoke-bomb.js", lightningStrike: "lightning/lightning-strike.js",
  disintegrate: "spawn/disintegrate.js", smallExplosion: "explosions/small-explosion.js", glitch: "scifi/glitch.js",
};
const mods = { pocketPoof };
for (const [k, p] of Object.entries(MODS)) mods[k] = await load(`pixelfx/fx/${p}`);
const RAMPS = { TEAL, EMBER, SLOP };

// The night theme's tokens from src/styles/global.css, which palettes() in engine.ts shades into ramps.
const { shade } = sprites;
const col = { rock: "#1f2a4d", rockHi: "#34446f", roadHi: "#9a7050", road: "#5e4033", roadLo: "#1c1220", grass: "#3f6e5a", grassHi: "#6fae7f", fx: "#ffffff" };
const ramps = {
  wood: [shade(col.roadLo, -1), col.roadLo, col.road, col.roadHi, shade(col.roadHi, 1), shade(col.roadHi, 2)],
  stone: [shade(col.rock, -2), shade(col.rock, -1), col.rock, col.rockHi, shade(col.rockHi, 1)],
  grass: [shade(col.grass, -1), col.grass, col.grassHi, shade(col.grassHi, 1)],
  fxLo: shade(col.fx, -2),
  roadDark: shade(col.road, -1),
};

// Effects draw into a frame with their origin at (OX, OY), so tall strikes and wide bursts fit.
const FW = 512, FH = 320, OX = 256, OY = 240;

function bake(spec) {
  const actor = spec.actor === "slop" ? actorOf(sprites.SLOP_PR[0], sprites.SLOP_PAL)
    : spec.actor ? actorOf(sprites.MINI_BOSSES[+spec.actor.split(":")[1]].frames[0], sprites.MINI_BOSSES[+spec.actor.split(":")[1]].pal) : undefined;
  const opts = { ...spec.opts };
  if (typeof opts.palette === "string") opts.palette = RAMPS[opts.palette].slice(opts.paletteFrom ?? 0);
  delete opts.paletteFrom;
  const mod = mods[spec.mod];
  const fx = createFx(mod, actor ? { ...opts, actor } : opts);
  const frame = createFrame(FW, FH), rgba = new Uint8ClampedArray(FW * FH * 4);
  const out = { frames: [], alpha: [] };
  for (let k = 0; ; k++) {
    // step(): update, drop it once done, then run the engine's queued stop().
    if (k > 0) {
      fx.update(TICK);
      if (fx.done()) break;
      if (k === spec.stopAt) fx.stop();
    }
    frame.color.fill(0);
    frame.light.fill(0);
    fx.options.x = OX;
    fx.options.y = OY;
    fx.draw(frame);
    composite(frame, rgba, null);
    let x0 = FW, y0 = FH, x1 = -1, y1 = -1;
    for (let y = 0; y < FH; y++) for (let x = 0; x < FW; x++) if (rgba[(y * FW + x) * 4 + 3]) {
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
    if (x1 < 0) out.frames.push(null);
    else {
      const w = x1 - x0 + 1, h = y1 - y0 + 1, crop = Buffer.alloc(w * h * 4);
      for (let y = 0; y < h; y++) crop.set(rgba.subarray(((y0 + y) * FW + x0) * 4, ((y0 + y) * FW + x1 + 1) * 4), y * w * 4);
      out.frames.push({ x: x0 - OX, y: y0 - OY, w, h, rgba: crop.toString("base64") });
    }
    out.alpha.push(actorAlphaOf(mod, fx.t, fx.options));
  }
  return out;
}

let input = "";
for await (const chunk of process.stdin) input += chunk;
const fx = Object.fromEntries(JSON.parse(input).map((s) => [s.key, bake(s)]));
process.stdout.write(JSON.stringify({ sprites, ramps, fx }));
