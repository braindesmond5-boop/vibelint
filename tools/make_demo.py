#!/usr/bin/env python3
"""Render halfbaked's real output as an animated SVG for the README.

    python3 tools/make_demo.py

Re-runs halfbaked, captures the coloured output, and writes demo.svg. The demo
is generated from real output, so it can never drift from what the tool
actually prints - regenerate it and the README is correct again.

The output is shown in full rather than with --quiet, because the snippet and
the suggested fix are the parts that make the point. Full output is far taller
than a README image should be, so the terminal scrolls: a fixed viewport with
the content sliding up, the way you would actually watch it run.

Standard library only, like the rest of the project. No vhs, no ffmpeg, no
screen recording, and the result is a few kilobytes of vector.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "demo.svg"
TARGET = "examples/vibe_coded_app"

# -- appearance ----------------------------------------------------------

FONT_SIZE = 14
CHAR_WIDTH = 8.4  # monospace advance at this size
LINE_HEIGHT = 21
PAD_X = 22
PAD_Y = 16
TITLEBAR = 34
RADIUS = 10

#: Output lines visible at once. The rest scrolls past.
VISIBLE_LINES = 22

#: Pacing, in seconds.
TYPE_DURATION = 1.3  # command "typing" in
PAUSE_AFTER_TYPING = 0.7
LINE_DELAY = 0.16  # between output lines
HOLD = 6.0  # final frame, so the summary can be read
LOOP_GAP = 1.2

THEME = {
    "bg": "#12131a",
    "titlebar": "#1b1d27",
    "fg": "#c8ccd8",
    "dim": "#6b7185",
    "red": "#ff6b81",
    "yellow": "#ffc457",
    "cyan": "#63d2ea",
    "green": "#5ee0a0",
}

ANSI = re.compile(r"\033\[([0-9;]*)m")


def parse_ansi(line: str) -> List[Tuple[str, str, bool]]:
    """Split a line into (text, colour, bold) runs."""
    runs: List[Tuple[str, str, bool]] = []
    colour, bold = THEME["fg"], False
    position = 0

    for match in ANSI.finditer(line):
        text = line[position : match.start()]
        if text:
            runs.append((text, colour, bold))
        position = match.end()

        for code in (match.group(1) or "0").split(";"):
            if code in ("", "0"):
                colour, bold = THEME["fg"], False
            elif code == "1":
                bold = True
            elif code == "2":
                colour = THEME["dim"]
            elif code == "31":
                colour = THEME["red"]
            elif code == "33":
                colour = THEME["yellow"]
            elif code == "36":
                colour = THEME["cyan"]
            elif code == "32":
                colour = THEME["green"]

    tail = line[position:]
    if tail:
        runs.append((tail, colour, bold))
    return runs


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_line(runs: List[Tuple[str, str, bool]], y: float) -> str:
    spans = []
    column = 0
    for text, colour, bold in runs:
        stripped = text.rstrip("\n")
        if stripped.strip():
            x = PAD_X + column * CHAR_WIDTH
            weight = ' font-weight="600"' if bold else ""
            spans.append(
                f'<tspan x="{x:.1f}" fill="{colour}"{weight}>{escape(stripped)}</tspan>'
            )
        column += len(stripped)
    if not spans:
        return ""
    return f'<text y="{y:.1f}">{"".join(spans)}</text>'


def build_svg(lines: List[str], command: str) -> str:
    lines = [line.rstrip("\n") for line in lines]

    widest = max([len(ANSI.sub("", line)) for line in lines] + [len(command) + 2])
    width = int(PAD_X * 2 + widest * CHAR_WIDTH) + 12

    prompt_y = TITLEBAR + PAD_Y + LINE_HEIGHT - 6
    output_top = prompt_y + LINE_HEIGHT
    viewport_height = VISIBLE_LINES * LINE_HEIGHT
    height = int(output_top + viewport_height + PAD_Y)

    start = TYPE_DURATION + PAUSE_AFTER_TYPING
    reveal_end = start + len(lines) * LINE_DELAY
    total = reveal_end + HOLD
    cycle = total + LOOP_GAP

    # -- output lines ----------------------------------------------------
    # Every line is drawn opaque. Nothing is hidden and nothing fades in, so a
    # renderer that ignores SMIL still shows the first screenful of real
    # output instead of an empty black rectangle. Motion comes entirely from
    # scrolling the viewport, which is a pure enhancement.
    rows = []
    for index, line in enumerate(lines):
        element = render_line(parse_ansi(line), output_top + (index + 1) * LINE_HEIGHT - 6)
        if element:
            rows.append(element)

    # -- scrolling: keep the newest line inside the viewport -------------
    # SMIL requires the first keyTime to be exactly 0, so the list opens with
    # the resting position before the scroll begins. Renderers are entitled to
    # discard the whole animation otherwise.
    times, offsets = [0.0], [0.0]
    for index in range(len(lines) + 1):
        overflow = max(0, (index + 1) - VISIBLE_LINES)
        times.append(min(start + index * LINE_DELAY, cycle))
        offsets.append(-overflow * LINE_HEIGHT)
    times.append(cycle)
    offsets.append(offsets[-1])
    times.append(cycle + 0.001)
    offsets.append(0)  # snap back for the loop

    key_times = ";".join(f"{min(t / cycle, 1.0):.5f}" for t in times)
    values = ";".join(f"0 {o}" for o in offsets)

    scroll = (
        f'<animateTransform attributeName="transform" type="translate"'
        f' values="{values}" keyTimes="{key_times}" dur="{cycle:.2f}s"'
        f' repeatCount="indefinite" calcMode="linear"/>'
    )

    # -- the command "typing" in via an expanding clip --------------------
    command_width = len(command) * CHAR_WIDTH
    cursor_x = PAD_X + 2 * CHAR_WIDTH

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace" font-size="{FONT_SIZE}">
  <defs>
    <clipPath id="viewport">
      <rect x="0" y="{output_top}" width="{width}" height="{viewport_height}"/>
    </clipPath>
    <clipPath id="typing">
      <!-- Full width by default, so the command is visible without animation. -->
      <rect x="0" y="0" width="{PAD_X + 2 * CHAR_WIDTH + command_width}" height="{height}">
        <animate attributeName="width" from="0" to="{PAD_X + 2 * CHAR_WIDTH + command_width}"
                 dur="{TYPE_DURATION}s" begin="0s;loop.begin" fill="freeze" calcMode="linear"/>
      </rect>
    </clipPath>
  </defs>

  <rect width="{width}" height="{height}" rx="{RADIUS}" fill="{THEME['bg']}"/>
  <path d="M0 {RADIUS}a{RADIUS} {RADIUS} 0 0 1 {RADIUS}-{RADIUS}h{width - 2 * RADIUS}a{RADIUS} {RADIUS} 0 0 1 {RADIUS} {RADIUS}v{TITLEBAR - RADIUS}H0z" fill="{THEME['titlebar']}"/>
  <circle cx="20" cy="{TITLEBAR // 2}" r="6" fill="#ff5f57"/>
  <circle cx="39" cy="{TITLEBAR // 2}" r="6" fill="#febc2e"/>
  <circle cx="58" cy="{TITLEBAR // 2}" r="6" fill="#28c840"/>
  <text x="{width / 2:.0f}" y="{TITLEBAR / 2 + 4:.0f}" fill="{THEME['dim']}" text-anchor="middle" font-size="12">halfbaked</text>

  <animate id="loop" attributeName="opacity" from="1" to="1" begin="0s;loop.end+0s" dur="{cycle:.2f}s"/>

  <g clip-path="url(#typing)">
    <text y="{prompt_y:.1f}">
      <tspan x="{PAD_X}" fill="{THEME['green']}" font-weight="600">$ </tspan>
      <tspan x="{cursor_x:.1f}" fill="{THEME['fg']}">{escape(command)}</tspan>
    </text>
  </g>
  <rect x="{cursor_x + command_width:.1f}" y="{prompt_y - 12:.1f}" width="8" height="16" fill="{THEME['green']}" opacity="0">
    <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;{TYPE_DURATION / cycle:.5f};{start / cycle:.5f};{(start + 0.01) / cycle:.5f}" dur="{cycle:.2f}s" repeatCount="indefinite"/>
  </rect>

  <g clip-path="url(#viewport)">
    <g>
      {scroll}
      {chr(10).join("      " + row for row in rows)}
    </g>
  </g>
</svg>
"""


def main() -> int:
    env = dict(os.environ, FORCE_COLOR="1", PYTHONPATH=str(ROOT / "src"))
    completed = subprocess.run(
        [sys.executable, "-m", "halfbaked.cli", TARGET],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    lines = [line for line in completed.stdout.split("\n") if line.strip()]
    if not lines:
        print("halfbaked produced no output; nothing to render", file=sys.stderr)
        print(completed.stderr, file=sys.stderr)
        return 1

    OUTPUT.write_text(build_svg(lines, f"halfbaked {TARGET}"), encoding="utf-8")
    size = OUTPUT.stat().st_size // 1024
    print(f"wrote {OUTPUT.relative_to(ROOT)}  ({size} KB, {len(lines)} lines of output)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
