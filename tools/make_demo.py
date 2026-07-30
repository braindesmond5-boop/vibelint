#!/usr/bin/env python3
"""Render vibelint's real output as an animated SVG for the README.

Run it, and it re-runs vibelint, captures the coloured output, and writes
demo.svg. The demo can therefore never drift from what the tool actually
prints - regenerate it and the README is correct again.

    python3 tools/make_demo.py

Standard library only, like the rest of the project. No vhs, no ffmpeg, no
screen recording. The result is a vector image, so it stays sharp on any
display and weighs a few kilobytes.
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
#: --quiet gives one line per finding. The full form is more useful in a
#: terminal but renders as a very tall strip, which reads badly in a README.
ARGS = ["--quiet"]

# -- appearance ----------------------------------------------------------

FONT_SIZE = 14
CHAR_WIDTH = 8.4  # monospace advance at this size
LINE_HEIGHT = 21
PAD_X = 22
PAD_Y = 18
TITLEBAR = 34
RADIUS = 10

#: Reveal one line every this many seconds, then hold the finished frame.
LINE_DELAY = 0.055
HOLD = 4.0

THEME = {
    "bg": "#12131a",
    "titlebar": "#1b1d27",
    "fg": "#c8ccd8",
    "dim": "#666b7d",
    "red": "#ff6b81",
    "yellow": "#ffc457",
    "cyan": "#63d2ea",
    "green": "#5ee0a0",
    "prompt": "#5ee0a0",
}

ANSI = re.compile(r"\033\[([0-9;]*)m")


# -- ANSI -> styled runs -------------------------------------------------


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


# -- SVG -----------------------------------------------------------------


def render_line(runs: List[Tuple[str, str, bool]], y: float) -> str:
    """One terminal line as a <text> element with positioned spans."""
    if not runs:
        return ""

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
    # The prompt line is drawn first, then the captured output.
    display = [f"$ {command}", ""] + [line.rstrip("\n") for line in lines]

    widest = max((len(ANSI.sub("", line)) for line in display), default=0)
    width = int(PAD_X * 2 + widest * CHAR_WIDTH) + 10
    height = int(TITLEBAR + PAD_Y * 2 + len(display) * LINE_HEIGHT)
    total = len(display) * LINE_DELAY + HOLD

    rows = []
    for index, line in enumerate(display):
        y = TITLEBAR + PAD_Y + (index + 1) * LINE_HEIGHT - 6

        if index == 0:
            runs = [("$ ", THEME["prompt"], True), (command, THEME["fg"], False)]
        else:
            runs = parse_ansi(line)

        element = render_line(runs, y)
        if element:
            begin = index * LINE_DELAY
            rows.append(
                f'<g opacity="0">{element}'
                f'<animate attributeName="opacity" from="0" to="1"'
                f' begin="{begin:.2f}s" dur="0.12s" fill="freeze"'
                f' repeatCount="1"/>'
                f'<animate attributeName="opacity" to="0"'
                f' begin="{total:.2f}s" dur="0.01s" fill="freeze"/>'
                f"</g>"
            )

    dots = "".join(
        f'<circle cx="{20 + i * 19}" cy="{TITLEBAR / 2:.0f}" r="6" fill="{c}"/>'
        for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840"))
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace" font-size="{FONT_SIZE}">
  <rect width="{width}" height="{height}" rx="{RADIUS}" fill="{THEME['bg']}"/>
  <path d="M0 {RADIUS}a{RADIUS} {RADIUS} 0 0 1 {RADIUS}-{RADIUS}h{width - 2 * RADIUS}a{RADIUS} {RADIUS} 0 0 1 {RADIUS} {RADIUS}v{TITLEBAR - RADIUS}H0z" fill="{THEME['titlebar']}"/>
  {dots}
  <text x="{width / 2:.0f}" y="{TITLEBAR / 2 + 4:.0f}" fill="{THEME['dim']}" text-anchor="middle" font-size="12">vibelint</text>
  <g>
    <animate id="loop" attributeName="opacity" from="1" to="1" begin="0s;loop.end+0.4s" dur="{total + 0.4:.2f}s"/>
    {chr(10).join("    " + row for row in rows)}
  </g>
</svg>
"""


def main() -> int:
    env = dict(os.environ, FORCE_COLOR="1", PYTHONPATH=str(ROOT / "src"))
    completed = subprocess.run(
        [sys.executable, "-m", "vibelint.cli", TARGET, *ARGS],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        print("vibelint produced no output; nothing to render", file=sys.stderr)
        print(completed.stderr, file=sys.stderr)
        return 1

    command = " ".join(["vibelint", TARGET, *ARGS])
    OUTPUT.write_text(build_svg(lines, command), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}  ({OUTPUT.stat().st_size // 1024} KB, {len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
