"""Generate small synthetic PNG screenshot pairs for the eval cases."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVALS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EVALS_ROOT))

from mobile_grid_overlay.evals import (
    load_cases_json,
    public_actual_path,
    public_clean_actual_path,
    public_clean_mock_path,
    public_mock_path,
)
from mobile_grid_overlay.svg import render_grid_defs, render_grid_layers


def main() -> int:
    out_dir = EVALS_ROOT / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)

    fixture_specs = [
        ("ios_header_shift_mock.png", 390, 844, "ios", {}),
        ("ios_header_shift_actual.png", 390, 844, "ios", {"title_y_delta": 8}),
        ("android_cta_spacing_mock.png", 360, 800, "android", {}),
        ("android_cta_spacing_actual.png", 360, 800, "android", {"cta_y_delta": -16}),
        ("ios_button_color_mock.png", 390, 844, "ios", {}),
        ("ios_button_color_actual.png", 390, 844, "ios", {"button_color": "#7c3aed"}),
        ("android_missing_icon_mock.png", 360, 800, "android", {}),
        ("android_missing_icon_actual.png", 360, 800, "android", {"show_search": False}),
        ("ios_subtle_layout_mock.png", 390, 844, "ios", {}),
        (
            "ios_subtle_layout_actual.png",
            390,
            844,
            "ios",
            {"title_y_delta": 3, "card_radius": 2, "cta_text_y_delta": 4},
        ),
        ("android_shape_typography_mock.png", 360, 800, "android", {}),
        (
            "android_shape_typography_actual.png",
            360,
            800,
            "android",
            {
                "title_font_size": 20,
                "title_font_family": "Times New Roman",
                "cta_radius": 18,
                "cta_text_y_delta": -4,
            },
        ),
        ("ios_card_radius_too_round_mock.png", 390, 844, "ios", {}),
        ("ios_card_radius_too_round_actual.png", 390, 844, "ios", {"card_radius": 24}),
        ("android_card_radius_too_square_mock.png", 360, 800, "android", {}),
        (
            "android_card_radius_too_square_actual.png",
            360,
            800,
            "android",
            {"card_radius": 0},
        ),
        ("ios_cta_radius_too_square_mock.png", 390, 844, "ios", {}),
        (
            "ios_cta_radius_too_square_actual.png",
            390,
            844,
            "ios",
            {"cta_radius": 0},
        ),
        ("ios_compound_header_cta_mock.png", 390, 844, "ios", {}),
        (
            "ios_compound_header_cta_actual.png",
            390,
            844,
            "ios",
            {
                "title_y_delta": 6,
                "show_search": False,
                "button_color": "#7c3aed",
                "cta_text_y_delta": 4,
            },
        ),
        ("android_micro_shape_text_mock.png", 360, 800, "android", {}),
        (
            "android_micro_shape_text_actual.png",
            360,
            800,
            "android",
            {
                "title_font_size": 20,
                "title_font_family": "Times New Roman",
                "card_radius": 0,
                "cta_text_y_delta": -4,
            },
        ),
        ("ios_dual_radius_color_mock.png", 390, 844, "ios", {}),
        (
            "ios_dual_radius_color_actual.png",
            390,
            844,
            "ios",
            {
                "card_radius": 24,
                "cta_radius": 0,
                "button_color": "#7c3aed",
            },
        ),
        ("ios_precision_stack_mock.png", 390, 844, "ios", {}),
        (
            "ios_precision_stack_actual.png",
            390,
            844,
            "ios",
            {
                "title_y_delta": 2,
                "search_x_delta": -7,
                "card_x_delta": 4,
                "card_width_delta": -8,
                "cta_text_y_delta": 3,
            },
        ),
        ("android_conflicting_shapes_mock.png", 360, 800, "android", {}),
        (
            "android_conflicting_shapes_actual.png",
            360,
            800,
            "android",
            {
                "card_radius": 20,
                "cta_radius": 0,
                "button_color": "#2563eb",
                "title_font_size": 20,
                "title_font_family": "Times New Roman",
            },
        ),
        ("ios_cta_geometry_stack_mock.png", 390, 844, "ios", {}),
        (
            "ios_cta_geometry_stack_actual.png",
            390,
            844,
            "ios",
            {
                "cta_y_delta": -7,
                "cta_x_delta": 5,
                "cta_width_delta": -10,
                "cta_height_delta": -4,
                "cta_radius": 0,
                "cta_text_y_delta": -3,
            },
        ),
    ]
    fixtures = []
    for filename, width, height, profile, options in fixture_specs:
        fixtures.append((filename, _phone_screen_png(width, height, profile, **options)))
        clean_filename = f"{Path(filename).stem}_clean.png"
        fixtures.append(
            (
                clean_filename,
                _phone_screen_png(width, height, profile, show_grid=False, **options),
            )
        )
    for filename, png in fixtures:
        png.save(out_dir / filename)
    _write_public_aliases()
    return 0


def _write_public_aliases() -> None:
    public_dir = EVALS_ROOT / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    for case in load_cases_json(EVALS_ROOT / "cases.json"):
        mock_bytes = (ROOT / case.mock_path).read_bytes()
        actual_bytes = (ROOT / case.actual_path).read_bytes()
        clean_mock_bytes = _clean_fixture_path(case.mock_path).read_bytes()
        clean_actual_bytes = _clean_fixture_path(case.actual_path).read_bytes()
        (EVALS_ROOT / public_mock_path(case)).write_bytes(mock_bytes)
        (EVALS_ROOT / public_actual_path(case)).write_bytes(actual_bytes)
        (EVALS_ROOT / public_clean_mock_path(case)).write_bytes(clean_mock_bytes)
        (EVALS_ROOT / public_clean_actual_path(case)).write_bytes(clean_actual_bytes)


def _clean_fixture_path(path: str) -> Path:
    source = ROOT / path
    return source.with_name(f"{source.stem}_clean{source.suffix}")


def _phone_screen_png(
    width: int,
    height: int,
    profile: str,
    *,
    title_y_delta: int = 0,
    title_x_delta: int = 0,
    search_x_delta: int = 0,
    cta_y_delta: int = 0,
    cta_x_delta: int = 0,
    cta_width_delta: int = 0,
    cta_height_delta: int = 0,
    button_color: str = "#007aff",
    show_search: bool = True,
    title_font_size: int = 22,
    title_font_weight: int = 700,
    title_font_family: str = "Arial",
    card_x_delta: int = 0,
    card_y_delta: int = 0,
    card_width_delta: int = 0,
    card_radius: int = 8,
    cta_radius: int = 8,
    cta_text_y_delta: int = 0,
    show_grid: bool = True,
):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise SystemExit("Pillow is required to generate PNG eval fixtures") from exc

    def font(size: int, *, bold: bool = False, family: str = "Arial"):
        candidates = []
        if "times" in family.casefold():
            candidates.append("/System/Library/Fonts/Supplemental/Times New Roman.ttf")
        elif bold:
            candidates.append("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
        else:
            candidates.append("/System/Library/Fonts/Supplemental/Arial.ttf")
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            ]
        )
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
        return ImageFont.load_default()

    image = Image.new("RGBA", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)

    header_height = 104 if profile == "ios" else 80
    base_title_y = 74 if profile == "ios" else 52
    title_x = 24 + title_x_delta
    title_y = base_title_y + title_y_delta
    search_y = base_title_y
    search_x = width - 38 + search_x_delta
    cta_y = height - (142 if profile == "ios" else 128) + cta_y_delta
    cta_x = 24 + cta_x_delta
    cta_width = width - 48 + cta_width_delta
    cta_height = 52 + cta_height_delta
    card_x = 24 + card_x_delta
    card_width = width - 48 + card_width_delta
    content_x = 44 + card_x_delta
    content_width = width - 88 + card_width_delta
    card_y = header_height + 34 + card_y_delta
    card_h = 154

    draw.rectangle((0, 0, width, header_height), fill="#ffffff")
    draw.text(
        (title_x, title_y - title_font_size),
        "Dashboard",
        font=font(title_font_size, bold=title_font_weight >= 700, family=title_font_family),
        fill="#111827",
    )
    if show_search:
        draw.ellipse(
            (search_x - 11, search_y - 19, search_x + 11, search_y + 3),
            outline="#111827",
            width=3,
        )
        draw.line(
            (search_x + 8, search_y, search_x + 16, search_y + 8),
            fill="#111827",
            width=3,
        )

    for y, h, radius in ((card_y, card_h, card_radius), (card_y + card_h + 28, 116, card_radius)):
        draw.rounded_rectangle(
            (card_x, y, card_x + card_width, y + h),
            radius=radius,
            fill="#ffffff",
            outline="#e5e7eb",
            width=1,
        )

    draw.rounded_rectangle(
        (content_x, card_y + 28, content_x + content_width, card_y + 46),
        radius=4,
        fill="#cbd5e1",
    )
    draw.rounded_rectangle(
        (content_x, card_y + 66, content_x + round(content_width * 0.72), card_y + 80),
        radius=4,
        fill="#e2e8f0",
    )
    draw.rounded_rectangle(
        (content_x, card_y + 94, content_x + round(content_width * 0.52), card_y + 108),
        radius=4,
        fill="#e2e8f0",
    )
    draw.rounded_rectangle(
        (
            content_x,
            card_y + card_h + 58,
            content_x + round(content_width * 0.84),
            card_y + card_h + 72,
        ),
        radius=4,
        fill="#cbd5e1",
    )
    draw.rounded_rectangle(
        (
            content_x,
            card_y + card_h + 90,
            content_x + round(content_width * 0.64),
            card_y + card_h + 104,
        ),
        radius=4,
        fill="#e2e8f0",
    )
    draw.rounded_rectangle(
        (cta_x, cta_y, cta_x + cta_width, cta_y + cta_height),
        radius=cta_radius,
        fill=button_color,
    )
    cta_font = font(17, bold=True)
    cta_text = "Continue"
    text_box = draw.textbbox((0, 0), cta_text, font=cta_font)
    draw.text(
        (
            round(cta_x + cta_width / 2) - round((text_box[2] - text_box[0]) / 2),
            cta_y + 16 + cta_text_y_delta,
        ),
        cta_text,
        font=cta_font,
        fill="#ffffff",
    )

    if show_grid:
        _draw_png_grid(draw, width, height, profile, font)
    return image


def _draw_png_grid(draw, width: int, height: int, profile: str, font_factory) -> None:
    minor = 8 if profile in {"ios", "universal"} else 8
    major = 32
    for x in range(0, width + 1, minor):
        color = (0, 208, 132, 140) if x % major == 0 else (0, 163, 255, 56)
        draw.line((x, 0, x, height), fill=color, width=1)
    for y in range(0, height + 1, minor):
        color = (0, 208, 132, 140) if y % major == 0 else (0, 163, 255, 56)
        draw.line((0, y, width, y), fill=color, width=1)
    for index in range(5):
        x = round(width * index / 4)
        draw.line((x, 0, x, height), fill=(255, 176, 0, 230), width=2)
    for index in range(9):
        y = round(height * index / 8)
        draw.line((0, y, width, y), fill=(255, 176, 0, 230), width=2)
    cx = round(width / 2)
    cy = round(height / 2)
    draw.line((cx, 0, cx, height), fill=(255, 46, 99, 230), width=1)
    draw.line((0, cy, width, cy), fill=(255, 46, 99, 230), width=1)
    label_font = font_factory(11, bold=True)
    for row in range(8):
        for col in range(4):
            label = f"{chr(65 + col)}{row + 1}"
            draw.text(
                (round(width * col / 4) + 6, round(height * row / 8) + 4),
                label,
                font=label_font,
                fill="#ffffff",
                stroke_width=2,
                stroke_fill="#0b1020",
            )


def _phone_screen(
    width: int,
    height: int,
    profile: str,
    *,
    title_y_delta: int = 0,
    title_x_delta: int = 0,
    search_x_delta: int = 0,
    cta_y_delta: int = 0,
    cta_x_delta: int = 0,
    cta_width_delta: int = 0,
    cta_height_delta: int = 0,
    button_color: str = "#007aff",
    show_search: bool = True,
    title_font_size: int = 22,
    title_font_weight: int = 700,
    title_font_family: str = "Arial",
    card_x_delta: int = 0,
    card_y_delta: int = 0,
    card_width_delta: int = 0,
    card_radius: int = 8,
    cta_radius: int = 8,
    cta_text_y_delta: int = 0,
    show_grid: bool = True,
) -> str:
    header_height = 104 if profile == "ios" else 80
    base_title_y = 74 if profile == "ios" else 52
    title_x = 24 + title_x_delta
    title_y = base_title_y + title_y_delta
    search_y = base_title_y
    search_x = width - 38 + search_x_delta
    cta_y = height - (142 if profile == "ios" else 128) + cta_y_delta
    cta_x = 24 + cta_x_delta
    cta_width = width - 48 + cta_width_delta
    cta_height = 52 + cta_height_delta
    card_x = 24 + card_x_delta
    card_width = width - 48 + card_width_delta
    content_x = 44 + card_x_delta
    content_width = width - 88 + card_width_delta
    card_y = header_height + 34 + card_y_delta
    card_h = 154

    parts = [
        _header(width, height, f"{profile} fixture", include_grid_defs=show_grid),
        '<rect x="0" y="0" width="100%" height="100%" fill="#f8fafc" />',
        f'<rect x="0" y="0" width="{width}" height="{header_height}" fill="#ffffff" />',
        (
            f'<text x="{title_x}" y="{title_y}" font-size="{title_font_size}" '
            f'font-weight="{title_font_weight}" font-family="{title_font_family}" '
            'fill="#111827">Dashboard</text>'
        ),
    ]
    if show_search:
        parts.extend(
            [
                f'<circle cx="{search_x}" cy="{search_y - 8}" r="11" fill="none" stroke="#111827" stroke-width="3" />',
                f'<line x1="{search_x + 8}" y1="{search_y}" x2="{search_x + 16}" y2="{search_y + 8}" stroke="#111827" stroke-width="3" stroke-linecap="round" />',
            ]
        )
    parts.extend(
        [
            f'<rect x="{card_x}" y="{card_y}" width="{card_width}" height="{card_h}" rx="{card_radius}" fill="#ffffff" stroke="#e5e7eb" />',
            f'<rect x="{content_x}" y="{card_y + 28}" width="{content_width}" height="18" rx="4" fill="#cbd5e1" />',
            f'<rect x="{content_x}" y="{card_y + 66}" width="{round(content_width * .72)}" height="14" rx="4" fill="#e2e8f0" />',
            f'<rect x="{content_x}" y="{card_y + 94}" width="{round(content_width * .52)}" height="14" rx="4" fill="#e2e8f0" />',
            f'<rect x="{card_x}" y="{card_y + card_h + 28}" width="{card_width}" height="116" rx="{card_radius}" fill="#ffffff" stroke="#e5e7eb" />',
            f'<rect x="{content_x}" y="{card_y + card_h + 58}" width="{round(content_width * .84)}" height="14" rx="4" fill="#cbd5e1" />',
            f'<rect x="{content_x}" y="{card_y + card_h + 90}" width="{round(content_width * .64)}" height="14" rx="4" fill="#e2e8f0" />',
            f'<rect x="{cta_x}" y="{cta_y}" width="{cta_width}" height="{cta_height}" rx="{cta_radius}" fill="{button_color}" />',
            f'<text x="{round(cta_x + cta_width / 2)}" y="{cta_y + 33 + cta_text_y_delta}" text-anchor="middle" font-size="17" font-weight="700" font-family="Arial" fill="#ffffff">Continue</text>',
        ]
    )
    if show_grid:
        parts.append(render_grid_layers(width, height, profile, show_labels=True))
    parts.extend(["</svg>", ""])
    return "\n".join(parts)


def _header(width: int, height: int, title: str, *, include_grid_defs: bool = True) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f"<title>{title}</title>",
    ]
    if include_grid_defs:
        parts.append(render_grid_defs())
    return "\n".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
