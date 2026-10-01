"""Build the README's branded SVGs.

GitHub serves README images in a way that blocks web fonts, so every piece of text is
shaped with HarfBuzz (real kerning) and written out as vector paths. Each themed asset
has a light and a dark version, which the README swaps with <picture>.

    python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
    .venv/bin/python scripts/build_assets.py

Fonts (all SIL Open Font License) are downloaded once into scripts/.fonts/.
"""

from __future__ import annotations

import html
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import uharfbuzz as hb

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
FONT_DIR = Path(__file__).resolve().parent / ".fonts"
GOOGLE_FONTS = "https://raw.githubusercontent.com/google/fonts/main/ofl"
FONT_FILES = {
    "BricolageGrotesque.ttf": f"{GOOGLE_FONTS}/bricolagegrotesque/BricolageGrotesque%5Bopsz,wdth,wght%5D.ttf",
    "Geist.ttf": f"{GOOGLE_FONTS}/geist/Geist%5Bwght%5D.ttf",
    "GeistMono.ttf": f"{GOOGLE_FONTS}/geistmono/GeistMono%5Bwght%5D.ttf",
}

# The website's palette.
ACCENT = "#E8501E"
INK = "#111312"
PAPER = "#F3F3EF"
THEMES = {
    "light": {
        "ground": PAPER, "grid": "#E3E5DE", "frame": INK, "ink": INK, "muted": "#575C58",
        "chip": "#C3C7BE", "line": "#D3D6CE", "card": "#FAFAF7", "row": "#E3E5DE",
        "rule": "#D1D9E0", "btn_bg": PAPER, "btn_border": INK, "btn_fg": INK,
    },
    "dark": {
        "ground": "#0F1211", "grid": "#1A1F1D", "frame": "#2B312E", "ink": PAPER,
        "muted": "#9BA39E", "chip": "#343B37", "line": "#2B312E", "card": "#151918",
        "row": "#2B312E", "rule": "#3D444D", "btn_bg": "#151918", "btn_border": "#343B37",
        "btn_fg": "#E9ECE6",
    },
}
CONSOLE = {
    "bg": "#151918", "panel": "#121615", "line": "#2B312E", "dot": "#343B37", "fg": "#E9ECE6",
    "text": "#F4F6F1", "muted": "#9BA39E", "dim": "#C9CFC9", "bubble": "#262C29",
    "track": "#1C211F", "ok": "#3DDC97", "ok_bg": "#17332A", "ok_fg": "#7FE3B5",
    "deny_bg": "#3A1D1A", "deny_fg": "#FF8A80",
}
WIDTH = 816  # README content width


# ---------------------------------------------------------------- text as paths

@dataclass(frozen=True)
class Style:
    file: str
    variations: tuple[tuple[str, float], ...]


STYLES = {
    "display": Style("BricolageGrotesque.ttf", (("wght", 750), ("opsz", 96), ("wdth", 100))),
    "title": Style("BricolageGrotesque.ttf", (("wght", 700), ("opsz", 36), ("wdth", 100))),
    "sans": Style("Geist.ttf", (("wght", 400),)),
    "sans600": Style("Geist.ttf", (("wght", 600),)),
    "mono": Style("GeistMono.ttf", (("wght", 400),)),
    "mono600": Style("GeistMono.ttf", (("wght", 600),)),
}
_fonts: dict[str, hb.Font] = {}


def font(style: str) -> hb.Font:
    if style not in _fonts:
        spec = STYLES[style]
        path = FONT_DIR / spec.file
        if not path.exists():
            FONT_DIR.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(FONT_FILES[spec.file], path)  # noqa: S310 - fixed URL
        hb_font = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
        hb_font.set_variations(dict(spec.variations))
        _fonts[style] = hb_font
    return _fonts[style]


class PathPen:
    """Collects a glyph outline in font units, flipped so y points down."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    @staticmethod
    def _pt(p) -> str:
        return f"{p[0]:.0f} {-p[1]:.0f}"

    def moveTo(self, p):  # noqa: N802 - pen protocol
        self.parts.append("M" + self._pt(p))

    def lineTo(self, p):  # noqa: N802
        self.parts.append("L" + self._pt(p))

    def qCurveTo(self, *pts):  # noqa: N802
        self.parts.append("Q" + " ".join(self._pt(p) for p in pts))

    def curveTo(self, *pts):  # noqa: N802
        self.parts.append("C" + " ".join(self._pt(p) for p in pts))

    def closePath(self):  # noqa: N802
        self.parts.append("Z")


# Glyph outlines used by the SVG being built: each is defined once and reused with <use>.
_glyphs: dict[tuple[str, int], str] = {}


def _glyph(style: str, gid: int) -> str | None:
    key = (style, gid)
    if key not in _glyphs:
        pen = PathPen()
        font(style).draw_glyph_with_pen(gid, pen)
        if not pen.parts:
            return None  # spaces have no outline
        _glyphs[key] = "".join(pen.parts)
    return f"g{list(_glyphs).index(key)}"


def _shape(text: str, style: str):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font(style), buf, {"kern": True, "liga": True})
    for info, char in zip(buf.glyph_infos, text, strict=False):
        if info.codepoint == 0 and not char.isspace():
            raise ValueError(f"{style} has no glyph for {char!r}")
    return buf.glyph_infos, buf.glyph_positions


def measure(text: str, style: str, size: float, tracking: float = 0) -> float:
    _, positions = _shape(text, style)
    scale = size / 1000
    return sum(p.x_advance for p in positions) * scale + tracking * size * len(positions)


def text(
    value: str,
    style: str,
    size: float,
    x: float,
    y: float,
    fill: str,
    tracking: float = 0,
    anchor: str = "start",
) -> str:
    """Text as reused glyph outlines; `y` is the baseline."""
    width = measure(value, style, size, tracking)
    x -= {"start": 0, "middle": width / 2, "end": width}[anchor]
    infos, positions = _shape(value, style)
    scale = size / 1000
    uses: list[str] = []
    cursor = 0.0
    for info, pos in zip(infos, positions, strict=True):
        glyph_id = _glyph(style, info.codepoint)
        if glyph_id:
            gx = x + (cursor + pos.x_offset) * scale
            gy = y - pos.y_offset * scale
            uses.append(
                f'<use href="#{glyph_id}" transform="matrix({scale:.4g} 0 0 {scale:.4g} '
                f'{gx:.1f} {gy:.1f})"/>'
            )
        cursor += pos.x_advance + tracking * 1000
    return f'<g fill="{fill}">{"".join(uses)}</g>' if uses else ""


def wrap(value: str, style: str, size: float, max_width: float) -> list[str]:
    lines, line = [], ""
    for word in value.split():
        candidate = f"{line} {word}".strip()
        if line and measure(candidate, style, size) > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return [*lines, line] if line else lines


def svg(width: float, height: float, body: list[str], title: str) -> str:
    glyphs = "".join(f'<path id="g{i}" d="{d}"/>' for i, d in enumerate(_glyphs.values()))
    _glyphs.clear()
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{html.escape(title)}">'
        f"<title>{html.escape(title)}</title><defs>{glyphs}</defs>{''.join(body)}</svg>\n"
    )


def rect(x, y, w, h, fill="none", stroke=None, rx=0, extra="") -> str:
    stroke_attr = f' stroke="{stroke}"' if stroke else ""
    return (
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx}" '
        f'fill="{fill}"{stroke_attr}{extra}/>'
    )


def bubble(x, y, w, h, fill, r=12, tail=4) -> str:
    """Chat bubble with a tighter bottom-right corner."""
    return (
        f'<path fill="{fill}" d="M{x + r} {y}H{x + w - r}Q{x + w} {y} {x + w} {y + r}'
        f"V{y + h - tail}Q{x + w} {y + h} {x + w - tail} {y + h}H{x + r}"
        f'Q{x} {y + h} {x} {y + h - r}V{y + r}Q{x} {y} {x + r} {y}Z"/>'
    )


def write(name: str, content: str) -> None:
    (ASSETS / name).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------- assets

def banner(theme: str) -> str:
    t = THEMES[theme]
    w, h, pad = 880, 316, 36
    body = [
        "<defs>",
        f'<pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">'
        f'<path d="M32 0H0V32" fill="none" stroke="{t["grid"]}" stroke-width="1"/></pattern>',
        f'<clipPath id="frame"><rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="12"/>'
        "</clipPath></defs>",
        f'<g clip-path="url(#frame)">{rect(0, 0, w, h, t["ground"])}'
        f'{rect(0, 0, w, h, "url(#grid)")}</g>',
        rect(0.5, 0.5, w - 1, h - 1, stroke=t["frame"], rx=12),
    ]
    x = pad
    for i, chip in enumerate(["AI PLATFORM ENGINEER", "CLOUD", "DATA PRODUCTS", "JOHANNESBURG, ZA"]):
        cw = measure(chip, "mono", 11, 0.04) + 16
        body.append(rect(x, pad, cw, 22, t["ground"], t["ink"] if i == 0 else t["chip"], 5))
        body.append(text(chip, "mono", 11, x + 8, pad + 15, t["ink"] if i == 0 else t["muted"], 0.04))
        x += cw + 6
    line_height = 58 * 0.96
    baseline = 130
    lines = ["I build AI systems that", "show their work"]
    for i, line in enumerate(lines):
        body.append(text(line, "display", 58, pad, baseline + i * line_height, t["ink"], -0.045))
    last = baseline + (len(lines) - 1) * line_height
    caret_x = pad + measure(lines[-1], "display", 58, -0.045) + 58 * 0.08
    body.append(
        f'<rect x="{caret_x:.2f}" y="{last - 58 * 0.78:.2f}" width="{58 * 0.42:.2f}" '
        f'height="{58 * 0.82:.2f}" fill="{ACCENT}"><animate attributeName="opacity" '
        'values="1;0" dur="1.1s" calcMode="discrete" repeatCount="indefinite"/></rect>'
    )
    rule_y = 252
    body.append(f'<path d="M{pad} {rule_y}H{w - pad}" stroke="{t["line"]}" stroke-width="1"/>')
    body.append(rect(pad, rule_y + 18, 24, 24, t["ink"], rx=5))
    body.append(text("zg", "mono600", 11, pad + 12, rule_y + 34, t["ground"], anchor="middle"))
    body.append(text("Zakhele Gamede", "mono600", 12.5, pad + 34, rule_y + 34.5, t["ink"]))
    body.append(
        text("Manager, AI Lab @ CrossCountry Consulting", "mono", 12.5, w - pad, rule_y + 34.5,
             t["muted"], anchor="end")
    )
    return svg(w, h, body, "I build AI systems that show their work. Zakhele Gamede, AI platform engineer, Johannesburg.")


def button(label: str, theme: str | None, filled: bool) -> str:
    t = THEMES[theme or "light"]
    size, pad, h = 12.5, 14, 34
    style = "mono600" if filled else "mono"
    w = measure(label, style, size) + pad * 2
    if filled:
        body = [rect(0, 0, w, h, ACCENT, rx=7), text(label, style, size, pad, 21.5, INK)]
    else:
        body = [rect(0.5, 0.5, w - 1, h - 1, t["btn_bg"], t["btn_border"], 7),
                text(label, style, size, pad, 21.5, t["btn_fg"])]
    return svg(w, h, body, label)


def header(path: str, title: str, theme: str) -> str:
    t = THEMES[theme]
    h = 76
    body = [
        text(path, "mono", 12, 0, 16, ACCENT),
        text(title, "title", 28, 0, 54, t["ink"], -0.03),
        f'<path d="M0 {h - 0.5}H{WIDTH}" stroke="{t["rule"]}" stroke-width="1"/>',
    ]
    return svg(WIDTH, h, body, f"{path} {title}")


PROFILE = [
    ("role", "Manager, AI Lab @ CrossCountry Consulting"),
    ("focus", "RAG, model evaluation, cloud platforms"),
    ("stack", "Python, FastAPI, TypeScript, Azure, Postgres"),
    ("building", "Quantum Shelf (personal)"),
    ("open_to", "Senior AI platform roles, technical conversations"),
]


def profile(theme: str) -> str:
    t = THEMES[theme]
    head, row = 32, 38
    h = head + row * len(PROFILE)
    body = [
        '<defs><clipPath id="card"><rect x="0.5" y="0.5" '
        f'width="{WIDTH - 1}" height="{h - 1}" rx="10"/></clipPath></defs>',
        f'<g clip-path="url(#card)">{rect(0, 0, WIDTH, h, t["card"])}{rect(0, 0, WIDTH, head, INK)}</g>',
        text("profile.yaml", "mono", 12, 16, 20.5, "#C9CFC9"),
        text("read-only", "mono", 12, WIDTH - 16, 20.5, ACCENT, anchor="end"),
    ]
    for i, (key, value) in enumerate(PROFILE):
        y = head + i * row
        if i:
            body.append(f'<path d="M0 {y + 0.5}H{WIDTH}" stroke="{t["row"]}" stroke-width="1"/>')
        body.append(text(key, "mono", 13.5, 16, y + 24, t["muted"]))
        body.append(text(value, "mono", 13.5, 124, y + 24, t["ink"]))
    body.append(rect(0.5, 0.5, WIDTH - 1, h - 1, stroke=t["frame"], rx=10))
    return svg(WIDTH, h, body, "profile.yaml: " + "; ".join(f"{k}: {v}" for k, v in PROFILE))


def ask_preview() -> str:
    c = CONSOLE
    bar, left_w = 34, 470
    body: list[str] = []
    # Conversation, laid out top to bottom.
    y = bar + 18
    lx, lw = 18, left_w - 36
    turns = [
        ("Where is Zakhele based?", "answered · grounded", "ok",
         "Zakhele is based in Johannesburg, South Africa.", "S1"),
        ("Which client was that built for?", "declined · confidential", "deny",
         "Client names aren't shared here, but I can explain what the workflow does.", None),
    ]
    for question, badge, tone, answer, cite in turns:
        qw = measure(question, "sans", 13.5) + 26
        body.append(bubble(lx + lw - qw, y, qw, 34, c["bubble"]))
        body.append(text(question, "sans", 13.5, lx + lw - qw + 13, y + 22, c["text"]))
        y += 34 + 14
        body.append(rect(lx, y, 22, 22, ACCENT, rx=6))
        body.append(text("zg", "mono600", 10, lx + 11, y + 15, INK, anchor="middle"))
        tx = lx + 32
        body.append(text("assistant", "mono", 10.5, tx, y + 11, c["muted"]))
        bx = tx + measure("assistant", "mono", 10.5) + 8
        bw = measure(badge, "mono", 10.5) + 12
        body.append(rect(bx, y + 1, bw, 15, c[f"{tone}_bg"], rx=4))
        body.append(text(badge, "mono", 10.5, bx + 6, y + 11.5, c[f"{tone}_fg"]))
        lines = wrap(answer, "sans", 13.5, lw - 32 - (24 if cite else 0))
        ly = y + 36
        for line in lines:
            body.append(text(line, "sans", 13.5, tx, ly, c["text"]))
            ly += 21.5
        if cite:
            cx = tx + measure(lines[-1], "sans", 13.5) + 6
            body.append(rect(cx, ly - 21.5 - 11, 20, 14, "none", ACCENT, 3))
            body.append(text(cite, "mono600", 9.5, cx + 10, ly - 21.5, ACCENT, anchor="middle"))
        y = ly - 21.5 + 22
    left_h = y + 4
    # Trace panel.
    rx, rw = left_w, 816 - left_w
    trace: list[str] = []
    ty = bar + 22
    trace.append(text("TRACE", "mono", 11, rx + 18, ty, c["fg"], 0.06))
    trace.append(text("policy v9cb1840e", "mono", 11, rx + rw - 18, ty, c["muted"], anchor="end"))
    my, mw = ty + 12, (rw - 36) / 2
    for i, (label, value) in enumerate([("GROUNDED", "1/1"), ("MODERATION", "passed")]):
        mx = rx + 18 + i * mw
        trace.append(rect(mx, my, mw, 46, c["panel"], c["line"], 0))
        trace.append(text(label, "mono", 9.5, mx + 10, my + 17, c["muted"], 0.04))
        trace.append(text(value, "mono", 15, mx + 10, my + 37, c["text"]))
    ry = my + 46 + 26
    trace.append(text("RETRIEVAL · FLOOR 0.25", "mono", 9.5, rx + 18, ry, c["muted"], 0.06))
    rows = [("S1", "profile.md#location", 0.75, True), ("S2", "profile.md#contact", 0.53, False),
            ("S3", "areas.md#problems-zakhele-works-on", 0.52, False),
            ("S4", "approach.md#how-zakhele-works", 0.21, False)]
    ry += 10
    for label, chunk, sim, cited in rows:
        ry += 22
        trace.append(text(label, "mono600", 11, rx + 18, ry, ACCENT if cited else c["muted"]))
        shown = chunk if measure(chunk, "mono", 11) < rw - 110 else chunk[:30] + "…"
        trace.append(text(shown, "mono", 11, rx + 44, ry, c["dim"]))
        trace.append(text(f"{sim:.2f}", "mono", 11, rx + rw - 18, ry, c["fg"], anchor="end"))
        track_w = rw - 62 - 18
        trace.append(rect(rx + 44, ry + 6, track_w, 3, c["track"], rx=1.5))
        color = ACCENT if cited else ("#3F4642" if sim < 0.25 else "#7C847F")
        trace.append(rect(rx + 44, ry + 6, track_w * sim, 3, color, rx=1.5))
        trace.append(rect(rx + 44 + track_w * 0.25, ry + 3, 1, 9, c["muted"]))
    h = max(left_h, ry + 26)
    frame = [
        '<defs><clipPath id="win"><rect x="0.5" y="0.5" '
        f'width="{815}" height="{h - 1:.0f}" rx="12"/></clipPath></defs>',
        f'<g clip-path="url(#win)">{rect(0, 0, 816, h, c["bg"])}{rect(rx, bar, rw, h - bar, c["panel"])}</g>',
        f'<path d="M0 {bar - 0.5}H816M{rx + 0.5} {bar}V{h}" stroke="{c["line"]}" stroke-width="1"/>',
    ]
    for i in range(3):
        frame.append(f'<circle cx="{18 + i * 13}" cy="{bar / 2}" r="4" fill="{c["dot"]}"/>')
    frame.append(text("portfolio-assistant", "mono", 11, 64, bar / 2 + 4, c["fg"]))
    frame.append(text("rag · pgvector · streaming", "mono", 11,
                      72 + measure("portfolio-assistant", "mono", 11), bar / 2 + 4, c["muted"]))
    frame.append(f'<circle cx="{816 - 64}" cy="{bar / 2}" r="3" fill="{c["ok"]}"/>')
    frame.append(text("online", "mono", 11, 816 - 18, bar / 2 + 4, c["muted"], anchor="end"))
    frame.append(rect(0.5, 0.5, 815, h - 1, stroke=c["line"], rx=12))
    alt = ("Preview of the portfolio assistant: a grounded answer citing its source, a declined "
           "question about a client, and the trace with retrieval scores and policy version.")
    return svg(816, h, frame + body + trace, alt)


def quantum_shelf() -> str:
    w, left = 816, 462
    body_lines = wrap(
        "A platform shell that brings applications, games, and labs together, with access "
        "managed separately from sign-in.", "sans", 14, left - 48)
    h = 64 + 44 + len(body_lines) * 21 + 26
    body = [
        '<defs><clipPath id="qs"><rect x="0.5" y="0.5" '
        f'width="{w - 1}" height="{h - 1}" rx="12"/></clipPath></defs>',
        f'<g clip-path="url(#qs)">{rect(0, 0, left, h, ACCENT)}{rect(left, 0, w - left, h, INK)}</g>',
        text("platform · react · fastapi", "mono", 11, 24, 34, INK),
        text("Quantum Shelf", "display", 38, 24, 78, INK, -0.035),
    ]
    for i, line in enumerate(body_lines):
        body.append(text(line, "sans", 14, 24, 108 + i * 21, INK))
    tx = left + 24
    for i, (prefix, rest) in enumerate([("$ ", "open quantum-ops-shelf-web"),
                                        ("", "apps: queueflow, house-stock,"),
                                        ("", "casedesk-live"), ("", "sdk: orchestrator")]):
        y = 34 + i * 19
        if prefix:
            body.append(text("$", "mono", 11.5, tx, y, ACCENT))
        body.append(text(rest, "mono", 11.5, tx + (16 if prefix else 0), y, "#9BA39E"))
    label = "Open Quantum Shelf ↗"
    bw = measure(label, "sans600", 13) + 24
    body.append(rect(tx, h - 24 - 32, bw, 32, PAPER, rx=7))
    body.append(text(label, "sans600", 13, tx + 12, h - 24 - 11, INK))
    body.append(rect(0.5, 0.5, w - 1, h - 1, stroke=INK, rx=12))
    return svg(w, h, body, "Quantum Shelf: a platform shell for applications, games, and labs. Open Quantum Shelf.")


def footer(theme: str) -> str:
    t = THEMES[theme]
    h = 42
    body = [
        rect(0.5, 0.5, WIDTH - 1, h - 1, t["ground"], t["frame"], 8),
        text("zakhele.gamede", "mono", 12, 16, 25.5, t["muted"]),
        text("JNB · SAST", "mono", 12, WIDTH / 2, 25.5, t["muted"], anchor="middle"),
        text("zakhelegamede.co.za ↗", "mono", 12, WIDTH - 16, 25.5, ACCENT, anchor="end"),
    ]
    return svg(WIDTH, h, body, "zakhelegamede.co.za")


HEADERS = {
    "ask": ("/ask", "Ask the portfolio"),
    "work": ("/work", "Selected client work"),
    "areas": ("/areas", "Problems I work on"),
    "products": ("/products", "Things I build on my own time"),
    "stack": ("/stack", "What I reach for"),
    "contact": ("/contact", "Building something that has to be right?"),
}


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    for old in ASSETS.glob("*.svg"):
        old.unlink()
    write("btn-site.svg", button("zakhelegamede.co.za ↗", None, filled=True))
    write("ask-preview.svg", ask_preview())
    write("quantum-shelf.svg", quantum_shelf())
    for theme in THEMES:
        write(f"banner-{theme}.svg", banner(theme))
        write(f"btn-ask-{theme}.svg", button("/ask the portfolio ↗", theme, filled=False))
        write(f"btn-email-{theme}.svg", button("hello@zakhelegamede.co.za", theme, filled=False))
        write(f"profile-{theme}.svg", profile(theme))
        write(f"footer-{theme}.svg", footer(theme))
        for key, (path, title) in HEADERS.items():
            write(f"h-{key}-{theme}.svg", header(path, title, theme))
    files = sorted(ASSETS.glob("*.svg"))
    total = sum(f.stat().st_size for f in files)
    print(f"Wrote {len(files)} SVGs, {total / 1024:.0f} KB")


if __name__ == "__main__":
    main()
