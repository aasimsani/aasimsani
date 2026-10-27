"""Run with `python3 scripts/test_afterhours_snake.py`."""

import xml.etree.ElementTree as ET

from afterhours_snake import caption, caption_path, period_s, render

full = [[1] * 7 for _ in range(52)]
svg = render(full)
ET.fromstring(svg)
assert svg.count('class="s"') == 364, "the snake covers every cell once"

# The preview loops every 711 frames at 60 Hz for a full 52x7 grid.
assert abs(period_s(364) - 711 / 60) < 1e-9
assert "11.85s" in svg

# Days that haven't happened yet are neither drawn nor on the snake's path.
partial = full[:-1] + [[2, 2, None, None, None, None, None]]
assert render(partial).count('class="s"') == 359

# Empty cells never change color, so only cells with contributions get an eat keyframe.
assert render([[0] * 7] * 52).count("@keyframes e") == 0

# The caption counts the same days the grid shows. A streak runs across week
# boundaries, and future days end it.
counts = [[1, 1, 0, 2, 2, 2, 1200], [3, 0, 0, None, None, None, None]]
assert caption(counts) == "1,211 CONTRIBUTIONS · LONGEST STREAK 5 DAYS · BEST DAY 1,200", caption(counts)
assert caption([[0, 1, 0, 0, 0, 0, 0]]) == "1 CONTRIBUTION · LONGEST STREAK 1 DAY · BEST DAY 1"

# Every caption character has a Silkscreen glyph, and the caption lands in the SVG.
assert caption_path(caption(counts)).count("M") > 20
assert "LONGEST" not in render(full, caption(counts))
assert caption_path(caption(counts)) in render(full, caption(counts))

print("ok")
