#!/usr/bin/env python3
"""Render an OG share card from a TOML brief.

Pipeline: brief.toml -> tokenized JSON tspans -> SVG (from template) ->
Inkscape PNG @2x -> PIL downscale to 1x -> PIL flatten RGBA->RGB on #0f0f14.

Usage:
    render.py <path/to/og-card.toml>

The brief lives at social/images/<slug>/og-card.toml and produces
og-card.svg, og-card.png, og-card@2x.png in the same directory.

Requires Pillow (`pip install pillow`) and Inkscape on PATH.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.stderr.write(
        "error: Pillow is required. Install with `pip install pillow`.\n"
    )
    sys.exit(2)

# Canonical palette (matches Part 2 / issue #63 spec).
BG = "#0f0f14"
BG_RGB = (15, 15, 20)
COLOR_KEY = "#2698ba"
COLOR_STRING = "#11d68b"
COLOR_NUMBER = "#efcc00"
COLOR_PUNCT = "#8a8a99"

# Code window layout (canonical).
CODE_X_BASE = 280              # x for indent=0
INDENT_PX_PER_CHAR = 12        # 20px JetBrains Mono char width
LINE_Y_START = 240             # y for first code line
LINE_HEIGHT = 22

# Title/subhead presets (named by title line count).
PRESET_SINGLE_LINE = {
    "title_ys": [90],
    "subhead_y": 140,
}
PRESET_TWO_LINE = {
    "title_ys": [62, 120],
    "subhead_y": 158,
}

# Window right-edge in canvas px (window x=244, width=712). Used to warn
# when a rendered line would overrun. Per-indent because deeper indents have
# less room: at indent 0, ~56 chars fit; at indent 6, only ~50.
WINDOW_RIGHT_EDGE = 956

# Line-budget guardrail (warning only).
MAX_CODE_LINES = 16

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = REPO_ROOT / "social" / "images" / "og-card-template.svg"


def tokenize_json_line(line: str) -> tuple[int, list[tuple[str, str]]]:
    """Split one line of pretty-printed JSON into (indent, [(color, literal), ...])."""
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    rest = stripped
    tokens: list[tuple[str, str]] = []
    string_re = re.compile(r'"((?:[^"\\]|\\.)*)"')
    number_re = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
    keyword_re = re.compile(r"true|false|null")

    while rest:
        if rest.startswith('"'):
            m = string_re.match(rest)
            if not m:
                raise ValueError(f"Unterminated string in line: {line!r}")
            literal = m.group(0)
            rest = rest[m.end():]
            following = rest.lstrip(" ")
            if following.startswith(":"):
                tokens.append((COLOR_KEY, literal))
            else:
                tokens.append((COLOR_STRING, literal))
            continue
        m = number_re.match(rest)
        if m:
            tokens.append((COLOR_NUMBER, m.group(0)))
            rest = rest[m.end():]
            continue
        m = keyword_re.match(rest)
        if m:
            tokens.append((COLOR_PUNCT, m.group(0)))
            rest = rest[m.end():]
            continue
        # Punctuation run: consume until the next meaningful token start.
        j = 1
        while j < len(rest) and rest[j] not in '"-0123456789tfn':
            j += 1
        tokens.append((COLOR_PUNCT, rest[:j]))
        rest = rest[j:]
    return indent, tokens


def xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_code_block(json_sample: str) -> str:
    """Build the <g> contents (the code <text>/<tspan> lines) from raw JSON text."""
    lines = json_sample.rstrip("\n").split("\n")
    if len(lines) > MAX_CODE_LINES:
        print(
            f"warn: {len(lines)} code lines exceeds budget of {MAX_CODE_LINES} "
            f"(font-size 20 / line-height 22). Consider shrinking font or compressing JSON.",
            file=sys.stderr,
        )
    out: list[str] = ['<g font-family="\'JetBrains Mono\',\'SF Mono\',Consolas,monospace" font-size="20" xml:space="preserve">']
    for i, line in enumerate(lines):
        indent, tokens = tokenize_json_line(line)
        x = CODE_X_BASE + indent * INDENT_PX_PER_CHAR
        y = LINE_Y_START + i * LINE_HEIGHT
        x_end = x + (len(line) - indent) * INDENT_PX_PER_CHAR
        if x_end > WINDOW_RIGHT_EDGE:
            print(
                f"warn: line {i + 1} extends to x={x_end} past window right edge "
                f"({WINDOW_RIGHT_EDGE}); shorten content or compress nested objects.",
                file=sys.stderr,
            )
        tspans = "".join(
            f'<tspan fill="{color}">{xml_escape(literal)}</tspan>' for color, literal in tokens
        )
        out.append(f'<text x="{x}" y="{y}">{tspans}</text>')
    out.append("</g>")
    return "\n".join(out)


def render_title_block(title: list[str]) -> tuple[str, dict]:
    if len(title) == 1:
        preset = PRESET_SINGLE_LINE
    elif len(title) == 2:
        preset = PRESET_TWO_LINE
    else:
        raise ValueError(f"title must be 1 or 2 lines, got {len(title)}")
    lines = [
        f'<text x="600" y="{y}" text-anchor="middle" fill="#ffffff" '
        f'font-size="56" font-weight="300">{xml_escape(text)}</text>'
        for y, text in zip(preset["title_ys"], title)
    ]
    return "\n".join(lines), preset


def render_subhead_block(subhead: str, preset: dict) -> str:
    return (
        f'<text x="600" y="{preset["subhead_y"]}" text-anchor="middle" '
        f'fill="#c0c0c8" font-size="28" font-weight="400">{xml_escape(subhead)}</text>'
    )


def build_svg(title: list[str], subhead: str, json_sample: str) -> str:
    template = TEMPLATE_PATH.read_text()
    title_block, preset = render_title_block(title)
    subhead_block = render_subhead_block(subhead, preset)
    code_block = render_code_block(json_sample)
    return (
        template.replace("{{TITLE_BLOCK}}", title_block)
        .replace("{{SUBHEAD_BLOCK}}", subhead_block)
        .replace("{{CODE_BLOCK}}", code_block)
    )


def inkscape_export(svg_path: Path, png_path: Path, width: int) -> None:
    """Inkscape is snap-confined to $HOME — paths must be absolute and under $HOME."""
    cmd = [
        "inkscape",
        str(svg_path.resolve()),
        f"--export-filename={png_path.resolve()}",
        f"--export-width={width}",
        "--export-type=png",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"inkscape failed (exit {e.returncode}):\n{e.stderr}")
        raise


def flatten_and_downscale(png_2x: Path, png_1x: Path) -> None:
    """Flatten RGBA->RGB on canonical bg, then write a downscaled 1x copy.

    LinkedIn's Post Inspector composites RGBA OG images on white during preview
    generation, which muddies dark cards. Rendering only @2x and downscaling
    via PIL.LANCZOS halves Inkscape startup cost.
    """
    with Image.open(png_2x) as src:
        src.load()
    if src.mode != "RGBA":
        src = src.convert("RGBA")
    flat_2x = Image.new("RGB", src.size, BG_RGB)
    flat_2x.paste(src, mask=src.split()[3])
    flat_2x.save(png_2x, "PNG")

    flat_1x = flat_2x.resize((1200, 630), Image.LANCZOS)
    flat_1x.save(png_1x, "PNG")

    for path in (png_2x, png_1x):
        with Image.open(path) as img:
            if img.mode != "RGB":
                raise RuntimeError(f"{path} is mode {img.mode}, expected RGB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path, help="Path to og-card.toml brief")
    args = parser.parse_args()

    brief_path: Path = args.brief.resolve()
    if not brief_path.is_file():
        print(f"error: brief not found at {brief_path}", file=sys.stderr)
        return 2
    with open(brief_path, "rb") as f:
        brief = tomllib.load(f)

    title = brief.get("title")
    subhead = brief.get("subhead")
    json_sample = brief.get("json_sample")
    if not (isinstance(title, list) and 1 <= len(title) <= 2):
        print("error: brief.title must be a list of 1 or 2 strings", file=sys.stderr)
        return 2
    if not isinstance(subhead, str) or not isinstance(json_sample, str):
        print("error: brief.subhead and brief.json_sample are required strings", file=sys.stderr)
        return 2

    if shutil.which("inkscape") is None:
        print("error: inkscape not found on PATH", file=sys.stderr)
        return 2

    home = Path.home().resolve()
    try:
        brief_path.relative_to(home)
    except ValueError:
        print(
            f"error: brief must live under {home} — Inkscape is snap-confined "
            f"to $HOME and cannot read/write outside it. Got: {brief_path}",
            file=sys.stderr,
        )
        return 2

    out_dir = brief_path.parent
    svg_path = out_dir / "og-card.svg"
    png_1x = out_dir / "og-card.png"
    png_2x = out_dir / "og-card@2x.png"

    svg = build_svg(title, subhead, json_sample)
    svg_path.write_text(svg, encoding="utf-8")
    print(f"wrote {svg_path}")

    inkscape_export(svg_path, png_2x, 2400)
    flatten_and_downscale(png_2x, png_1x)
    print(f"wrote {png_2x} (2400px, RGB)")
    print(f"wrote {png_1x} (1200px, RGB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
