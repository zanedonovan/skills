"""Command-line entrypoint for rendering mobile grid overlays."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from mobile_grid_overlay.profiles import list_profiles
    from mobile_grid_overlay.svg import render_grid_svg
else:
    from .profiles import list_profiles
    from .svg import render_grid_svg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render mobile screenshot grid overlays as SVG.")
    parser.add_argument("--width", type=int, required=True, help="Screenshot width in pixels.")
    parser.add_argument("--height", type=int, required=True, help="Screenshot height in pixels.")
    parser.add_argument(
        "--profile",
        choices=[profile.name for profile in list_profiles()],
        default="universal",
        help="Grid profile to render.",
    )
    parser.add_argument("--screenshot", help="Optional screenshot path or URL to embed under the grid.")
    parser.add_argument("--no-labels", action="store_true", help="Hide macro cell and ruler labels.")
    parser.add_argument("--out", required=True, help="Output SVG path.")
    args = parser.parse_args(argv)

    svg = render_grid_svg(
        args.width,
        args.height,
        args.profile,
        screenshot_href=args.screenshot,
        show_labels=not args.no_labels,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
