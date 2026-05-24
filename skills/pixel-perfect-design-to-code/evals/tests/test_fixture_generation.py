from __future__ import annotations

import unittest

from eval_suite import load_pixel_eval_module


_phone_screen = load_pixel_eval_module("generate_fixtures")._phone_screen


class FixtureGenerationTests(unittest.TestCase):
    def test_synthetic_fixture_contains_visible_grid_styles(self) -> None:
        svg = _phone_screen(390, 844, "ios")

        self.assertIn("<defs>", svg)
        self.assertIn(".minor-line{stroke:#00a3ff", svg)
        self.assertIn(".macro-line{stroke:#ffb000", svg)
        self.assertIn('id="edge-rulers"', svg)

    def test_synthetic_fixture_can_render_without_grid_for_strict_diff(self) -> None:
        svg = _phone_screen(390, 844, "ios", show_grid=False)

        self.assertIn("<svg", svg)
        self.assertIn("<title>ios fixture</title>", svg)
        self.assertNotIn('id="mobile-grid-overlay"', svg)
        self.assertNotIn('id="edge-rulers"', svg)
        self.assertNotIn(".minor-line{stroke:#00a3ff", svg)

    def test_title_shift_does_not_move_unrelated_header_icon(self) -> None:
        svg = _phone_screen(390, 844, "ios", title_y_delta=8, show_grid=False)

        self.assertIn('cy="66"', svg)
        self.assertNotIn('cy="74"', svg)


if __name__ == "__main__":
    unittest.main()
