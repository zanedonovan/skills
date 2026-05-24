from __future__ import annotations

import unittest

import eval_suite  # noqa: F401
from mobile_grid_overlay.profiles import get_profile
from mobile_grid_overlay.svg import render_grid_svg


class GridSvgTests(unittest.TestCase):
    def test_ios_safe_area_scales_with_width(self) -> None:
        profile = get_profile("ios")
        self.assertEqual(59, profile.scaled_px(390, profile.safe_top))
        self.assertEqual(118, profile.scaled_px(780, profile.safe_top))
        self.assertEqual(68, profile.scaled_px(780, profile.safe_bottom))

    def test_svg_contains_macro_labels_and_center_lines(self) -> None:
        svg = render_grid_svg(390, 844, "universal")
        self.assertIn('id="macro-grid"', svg)
        self.assertIn('id="center-lines"', svg)
        self.assertIn('id="edge-rulers"', svg)
        self.assertIn(">A1</text>", svg)
        self.assertIn(">D8</text>", svg)

    def test_pixel_profile_uses_one_pixel_measurement_grid(self) -> None:
        profile = get_profile("pixel")
        self.assertEqual(1, profile.grid_step_px(390))
        self.assertEqual(1, profile.grid_step_px(780))
        svg = render_grid_svg(12, 10, "pixel", show_labels=False)
        self.assertIn('x1="1" y1="0" x2="1" y2="10"', svg)
        self.assertIn('x1="8" y1="0" x2="8" y2="10"', svg)

    def test_edge_rulers_remain_available_without_labels(self) -> None:
        svg = render_grid_svg(390, 844, "pixel", show_labels=False)
        self.assertIn('id="edge-rulers"', svg)
        self.assertNotIn('id="macro-labels"', svg)

    def test_svg_can_embed_screenshot_under_grid(self) -> None:
        svg = render_grid_svg(390, 844, "ios", screenshot_href="screens/mock.png")
        self.assertIn('<image href="screens/mock.png"', svg)
        self.assertLess(svg.index("<image"), svg.index('id="mobile-grid-overlay"'))


if __name__ == "__main__":
    unittest.main()
