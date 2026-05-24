"""SVG rendering for screenshot grid overlays."""

from __future__ import annotations

from html import escape
from string import ascii_uppercase

from .profiles import GridProfile, get_profile


def render_grid_svg(
    width: int,
    height: int,
    profile: str | GridProfile = "universal",
    *,
    screenshot_href: str | None = None,
    show_labels: bool = True,
    title: str | None = None,
) -> str:
    """Render a complete SVG overlay.

    If ``screenshot_href`` is provided, the screenshot is embedded as the bottom
    SVG layer and the grid is drawn above it. Without a screenshot, the SVG is
    transparent and can be used as a standalone overlay.
    """

    profile_obj = _coerce_profile(profile)
    _validate_dimensions(width, height)
    label = title or f"{profile_obj.name} grid {width}x{height}"

    image_layer = ""
    if screenshot_href:
        href = escape(screenshot_href, quote=True)
        image_layer = (
            f'<image href="{href}" x="0" y="0" width="{width}" height="{height}" '
            'preserveAspectRatio="none" />\n'
        )

    return "\n".join(
        [
            _svg_header(width, height, label),
            image_layer + render_grid_layers(width, height, profile_obj, show_labels=show_labels),
            "</svg>",
            "",
        ]
    )


def render_grid_layers(
    width: int,
    height: int,
    profile: str | GridProfile = "universal",
    *,
    show_labels: bool = True,
) -> str:
    """Render only the overlay layers, suitable for composition in another SVG."""

    profile_obj = _coerce_profile(profile)
    _validate_dimensions(width, height)

    minor = profile_obj.grid_step_px(width)
    major = minor * profile_obj.major_every
    side_margin = profile_obj.scaled_px(width, profile_obj.side_margin)
    safe_top = _scaled_optional(profile_obj, width, profile_obj.safe_top)
    safe_bottom = _scaled_optional(profile_obj, width, profile_obj.safe_bottom)

    parts: list[str] = [
        '<g id="mobile-grid-overlay" fill="none">',
        _safe_area_layer(width, height, safe_top, safe_bottom),
        _measurement_grid_layer(width, height, minor, major),
        _content_margin_layer(width, height, side_margin),
        _macro_grid_layer(width, height, profile_obj.macro_columns, profile_obj.macro_rows),
        _center_layer(width, height),
        _edge_ruler_layer(width, height, minor, major),
    ]
    if show_labels:
        parts.extend(
            [
                _macro_label_layer(width, height, profile_obj.macro_columns, profile_obj.macro_rows),
                _ruler_label_layer(width, height, major),
            ]
        )
    parts.append("</g>")
    return "\n".join(parts)


def _coerce_profile(profile: str | GridProfile) -> GridProfile:
    if isinstance(profile, GridProfile):
        return profile
    return get_profile(profile)


def _validate_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")


def _scaled_optional(profile: GridProfile, width: int, value: int) -> int:
    return 0 if value == 0 else profile.scaled_px(width, value)


def render_grid_defs() -> str:
    """Render SVG definitions required by grid overlay layers."""

    return "\n".join(
        [
            "<defs>",
            "<style>",
            _grid_style(),
            "</style>",
            "</defs>",
        ]
    )


def _svg_header(width: int, height: int, title: str) -> str:
    return "\n".join(
        [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
                f'height="{height}" viewBox="0 0 {width} {height}" '
                'role="img" aria-labelledby="title desc">'
            ),
            f"<title>{escape(title)}</title>",
            "<desc>Mobile screenshot review grid with macro cells, rulers, safe areas, and center lines.</desc>",
            render_grid_defs(),
        ]
    )


def _grid_style() -> str:
    return "\n".join(
        [
            ".minor-line{stroke:#00a3ff;stroke-opacity:.22;stroke-width:.55;vector-effect:non-scaling-stroke}",
            ".major-line{stroke:#00d084;stroke-opacity:.55;stroke-width:.8;vector-effect:non-scaling-stroke}",
            ".macro-line{stroke:#ffb000;stroke-opacity:.9;stroke-width:1.25;vector-effect:non-scaling-stroke}",
            ".center-line{stroke:#ff2e63;stroke-opacity:.9;stroke-width:1.1;stroke-dasharray:6 5;vector-effect:non-scaling-stroke}",
            ".margin-line{stroke:#ffffff;stroke-opacity:.78;stroke-width:1;stroke-dasharray:4 4;vector-effect:non-scaling-stroke}",
            ".ruler-bg{fill:#0b1020;fill-opacity:.42}",
            ".tick-minor{stroke:#ffffff;stroke-opacity:.35;stroke-width:.5;vector-effect:non-scaling-stroke}",
            ".tick-major{stroke:#ffffff;stroke-opacity:.85;stroke-width:.8;vector-effect:non-scaling-stroke}",
            ".safe-fill{fill:#ff2e63;fill-opacity:.11}",
            ".safe-edge{stroke:#ff2e63;stroke-opacity:.65;stroke-width:1;vector-effect:non-scaling-stroke}",
            ".label-halo{font:600 11px system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;stroke:#0b1020;stroke-width:3;stroke-linejoin:round;paint-order:stroke;fill:#fff}",
            ".ruler-label{font:500 9px system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;stroke:#0b1020;stroke-width:2;stroke-linejoin:round;paint-order:stroke;fill:#fff;opacity:.9}",
        ]
    )


def _safe_area_layer(width: int, height: int, safe_top: int, safe_bottom: int) -> str:
    parts = ['<g id="safe-area-bands">']
    if safe_top:
        parts.append(f'<rect class="safe-fill" x="0" y="0" width="{width}" height="{safe_top}" />')
        parts.append(_line("safe-edge", 0, safe_top, width, safe_top))
    if safe_bottom:
        y = height - safe_bottom
        parts.append(f'<rect class="safe-fill" x="0" y="{y}" width="{width}" height="{safe_bottom}" />')
        parts.append(_line("safe-edge", 0, y, width, y))
    parts.append("</g>")
    return "\n".join(parts)


def _measurement_grid_layer(width: int, height: int, minor: int, major: int) -> str:
    parts = ['<g id="measurement-grid">']
    for x in _positions(width, minor):
        class_name = "major-line" if x % major == 0 else "minor-line"
        parts.append(_line(class_name, x, 0, x, height))
    for y in _positions(height, minor):
        class_name = "major-line" if y % major == 0 else "minor-line"
        parts.append(_line(class_name, 0, y, width, y))
    parts.append("</g>")
    return "\n".join(parts)


def _content_margin_layer(width: int, height: int, side_margin: int) -> str:
    right = width - side_margin
    return "\n".join(
        [
            '<g id="content-margins">',
            _line("margin-line", side_margin, 0, side_margin, height),
            _line("margin-line", right, 0, right, height),
            "</g>",
        ]
    )


def _macro_grid_layer(width: int, height: int, columns: int, rows: int) -> str:
    parts = ['<g id="macro-grid">']
    for index in range(columns + 1):
        x = round(width * index / columns)
        parts.append(_line("macro-line", x, 0, x, height))
    for index in range(rows + 1):
        y = round(height * index / rows)
        parts.append(_line("macro-line", 0, y, width, y))
    parts.append("</g>")
    return "\n".join(parts)


def _center_layer(width: int, height: int) -> str:
    cx = round(width / 2)
    cy = round(height / 2)
    return "\n".join(
        [
            '<g id="center-lines">',
            _line("center-line", cx, 0, cx, height),
            _line("center-line", 0, cy, width, cy),
            "</g>",
        ]
    )


def _macro_label_layer(width: int, height: int, columns: int, rows: int) -> str:
    parts = ['<g id="macro-labels">']
    for row in range(rows):
        for column in range(columns):
            label = _cell_label(column, row)
            x = round(width * column / columns) + 6
            y = round(height * row / rows) + 16
            parts.append(f'<text class="label-halo" x="{x}" y="{y}">{label}</text>')
    parts.append("</g>")
    return "\n".join(parts)


def _ruler_label_layer(width: int, height: int, major: int) -> str:
    parts = ['<g id="ruler-labels">']
    for x in _positions(width, major):
        if x == 0 or x == width:
            continue
        parts.append(f'<text class="ruler-label" x="{x + 2}" y="11">{x}</text>')
    for y in _positions(height, major):
        if y == 0 or y == height:
            continue
        parts.append(f'<text class="ruler-label" x="3" y="{y - 3}">{y}</text>')
    parts.append("</g>")
    return "\n".join(parts)


def _edge_ruler_layer(width: int, height: int, minor: int, major: int) -> str:
    """Render unobtrusive top/left rulers for pixel-distance estimation."""

    parts = [
        '<g id="edge-rulers">',
        f'<rect class="ruler-bg" x="0" y="0" width="{width}" height="16" />',
        f'<rect class="ruler-bg" x="0" y="0" width="18" height="{height}" />',
    ]
    for x in _positions(width, minor):
        tick_height = 12 if x % major == 0 else 6
        class_name = "tick-major" if x % major == 0 else "tick-minor"
        parts.append(_line(class_name, x, 0, x, tick_height))
    for y in _positions(height, minor):
        tick_width = 14 if y % major == 0 else 7
        class_name = "tick-major" if y % major == 0 else "tick-minor"
        parts.append(_line(class_name, 0, y, tick_width, y))
    parts.append("</g>")
    return "\n".join(parts)


def _positions(limit: int, step: int) -> list[int]:
    values = list(range(0, limit + 1, step))
    if values[-1] != limit:
        values.append(limit)
    return values


def _line(class_name: str, x1: int, y1: int, x2: int, y2: int) -> str:
    return f'<line class="{class_name}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" />'


def _cell_label(column: int, row: int) -> str:
    prefix = ascii_uppercase[column] if column < len(ascii_uppercase) else f"C{column + 1}"
    return f"{prefix}{row + 1}"
