#!/usr/bin/env python3
"""Generate the GitHub social preview card (1280x640 PNG).

    python3 tools/make_social.py

Writes social-preview.png, ready to upload under
Settings -> General -> Social preview on the GitHub repo.

Why a PDF in the middle: there is no PIL, no cairosvg and no ImageMagick on a
stock macOS, and QuickLook renders SVG at an unpredictable scale. PDF is a
plain-text format with fourteen fonts every renderer already has, so it can be
written with the standard library alone - and `sips`, which ships with macOS,
converts PDF to PNG exactly and without resampling surprises.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "tools" / "social-preview.pdf"
PNG_PATH = ROOT / "social-preview.png"

WIDTH, HEIGHT = 1280, 640

# Courier advances at exactly 0.6 em, which makes layout arithmetic exact.
COURIER_ADVANCE = 0.6

COLORS = {
    "bg": (0.071, 0.075, 0.102),
    "panel": (0.047, 0.051, 0.075),
    "border": (0.141, 0.153, 0.212),
    "white": (0.949, 0.957, 0.973),
    "grey": (0.545, 0.565, 0.639),
    "dim": (0.302, 0.322, 0.396),
    "red": (1.0, 0.420, 0.506),
    "yellow": (1.0, 0.769, 0.341),
    "cyan": (0.388, 0.824, 0.918),
    "green": (0.157, 0.784, 0.251),
    "amber": (0.996, 0.737, 0.180),
}


class Content:
    """A PDF content stream, addressed in top-left screen coordinates."""

    def __init__(self) -> None:
        self.parts: List[str] = []

    def rect(self, x: float, y: float, w: float, h: float, color: Tuple) -> None:
        r, g, b = color
        self.parts.append(
            f"{r:.3f} {g:.3f} {b:.3f} rg {x:.1f} {HEIGHT - y - h:.1f} {w:.1f} {h:.1f} re f"
        )

    def text(
        self, x: float, y: float, size: float, color: Tuple, value: str, bold: bool = False
    ) -> float:
        """Draw text, returning the x position just past it."""
        r, g, b = color
        font = "/F2" if bold else "/F1"
        escaped = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        self.parts.append(
            f"BT {font} {size:.1f} Tf {r:.3f} {g:.3f} {b:.3f} rg "
            f"1 0 0 1 {x:.1f} {HEIGHT - y:.1f} Tm ({escaped}) Tj ET"
        )
        return x + len(value) * size * COURIER_ADVANCE

    def circle(self, cx: float, cy: float, radius: float, color: Tuple) -> None:
        """Four Bezier arcs, which is how PDF draws a circle."""
        r, g, b = color
        k = radius * 0.5523
        y = HEIGHT - cy
        self.parts.append(
            f"{r:.3f} {g:.3f} {b:.3f} rg "
            f"{cx - radius:.1f} {y:.1f} m "
            f"{cx - radius:.1f} {y + k:.1f} {cx - k:.1f} {y + radius:.1f} {cx:.1f} {y + radius:.1f} c "
            f"{cx + k:.1f} {y + radius:.1f} {cx + radius:.1f} {y + k:.1f} {cx + radius:.1f} {y:.1f} c "
            f"{cx + radius:.1f} {y - k:.1f} {cx + k:.1f} {y - radius:.1f} {cx:.1f} {y - radius:.1f} c "
            f"{cx - k:.1f} {y - radius:.1f} {cx - radius:.1f} {y - k:.1f} {cx - radius:.1f} {y:.1f} c f"
        )

    def render(self) -> str:
        return "\n".join(self.parts)


def draw_card() -> Content:
    c = Content()

    c.rect(0, 0, WIDTH, HEIGHT, COLORS["bg"])
    c.rect(0, 0, WIDTH, 5, COLORS["red"])

    c.text(80, 138, 68, COLORS["white"], "vibelint", bold=True)
    c.text(80, 186, 21, COLORS["grey"], "Find the mistakes AI leaves behind in your code.")

    # Terminal panel
    c.rect(80, 228, 1120, 250, COLORS["border"])
    c.rect(81, 229, 1118, 248, COLORS["panel"])

    for i, dot in enumerate(("red", "amber", "green")):
        c.circle(110 + i * 20, 260, 6, COLORS[dot])
    c.text(172, 265, 13, COLORS["dim"], "vibelint .")

    findings = [
        ("x", "red", "GHOST FUNCTION", "sanitize_input() is not defined anywhere"),
        ("x", "red", "LOST AWAIT", "send_email() is async, never awaited, never runs"),
        ("x", "red", "TEST THEATER", "test_truncate() asserts nothing, cannot fail"),
        ("!", "yellow", "SILENT FAIL", "except Exception: return None hides every error"),
    ]
    for i, (mark, color, label, message) in enumerate(findings):
        y = 312 + i * 34
        c.text(112, y, 16, COLORS[color], mark, bold=True)
        c.text(142, y, 16, COLORS[color], label)
        c.text(330, y, 16, COLORS["white"], message)

    c.rect(112, 434, 1056, 1, COLORS["border"])

    x = c.text(112, 460, 15, COLORS["white"], "25 flops", bold=True)
    x = c.text(x + 12, 460, 15, COLORS["dim"], "\xb7")
    x = c.text(x + 12, 460, 15, COLORS["red"], "15 critical")
    x = c.text(x + 12, 460, 15, COLORS["dim"], "\xb7")
    x = c.text(x + 12, 460, 15, COLORS["yellow"], "10 warnings")
    x = c.text(x + 12, 460, 15, COLORS["dim"], "\xb7")
    c.text(x + 12, 460, 15, COLORS["dim"], "checked in 0.18s")

    # Footer
    x = c.text(80, 550, 19, COLORS["cyan"], "15 checks")
    x = c.text(x + 22, 550, 19, COLORS["dim"], "\xb7")
    x = c.text(x + 22, 550, 19, COLORS["cyan"], "zero dependencies")
    x = c.text(x + 22, 550, 19, COLORS["dim"], "\xb7")
    x = c.text(x + 22, 550, 19, COLORS["cyan"], "never runs your code")
    x = c.text(x + 22, 550, 19, COLORS["dim"], "\xb7")
    c.text(x + 22, 550, 19, COLORS["cyan"], "Python 3.9+")

    c.text(80, 596, 16, COLORS["dim"], "pip install vibelint")

    return c


def build_pdf(stream: str) -> bytes:
    """Assemble a minimal single-page PDF with a correct xref table."""
    body = stream.encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {WIDTH} {HEIGHT}] "
            f"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>"
        ).encode(),
        b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()

    return bytes(out)


def main() -> int:
    PDF_PATH.write_bytes(build_pdf(draw_card().render()))
    print(f"wrote {PDF_PATH.relative_to(ROOT)}")

    if not shutil.which("sips"):
        print("sips not found - convert the PDF to a 1280x640 PNG yourself", file=sys.stderr)
        return 1

    result = subprocess.run(
        ["sips", "-s", "format", "png", str(PDF_PATH), "--out", str(PNG_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return 1

    subprocess.run(
        ["sips", "-z", str(HEIGHT), str(WIDTH), str(PNG_PATH)],
        capture_output=True,
        text=True,
    )
    print(f"wrote {PNG_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
