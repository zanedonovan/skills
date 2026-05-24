"""Grid profile definitions for mobile screenshot review."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GridProfile:
    """A resolution-scaled grid profile.

    Values are authored against ``base_width`` and scaled by screenshot width.
    That keeps the same profile usable for logical screenshots and high-DPI
    exports of the same device class.
    """

    name: str
    platform: str
    base_width: int
    minor_step: int
    major_every: int
    macro_columns: int
    macro_rows: int
    safe_top: int
    safe_bottom: int
    side_margin: int
    description: str
    scale_grid_steps: bool = True

    def scale_for_width(self, width: int) -> float:
        if width <= 0:
            raise ValueError("width must be positive")
        return width / self.base_width

    def scaled_px(self, width: int, value: int) -> int:
        return max(1, round(value * self.scale_for_width(width)))

    def grid_step_px(self, width: int) -> int:
        if self.scale_grid_steps:
            return self.scaled_px(width, self.minor_step)
        return self.minor_step


PROFILES: dict[str, GridProfile] = {
    "universal": GridProfile(
        name="universal",
        platform="ios/android",
        base_width=390,
        minor_step=8,
        major_every=4,
        macro_columns=4,
        macro_rows=8,
        safe_top=0,
        safe_bottom=0,
        side_margin=16,
        description="4x8 macro grid with 8pt measurement rhythm and center lines.",
    ),
    "ios": GridProfile(
        name="ios",
        platform="ios",
        base_width=390,
        minor_step=8,
        major_every=4,
        macro_columns=4,
        macro_rows=8,
        safe_top=59,
        safe_bottom=34,
        side_margin=16,
        description="iOS-oriented grid with common modern safe-area bands.",
    ),
    "android": GridProfile(
        name="android",
        platform="android",
        base_width=360,
        minor_step=8,
        major_every=4,
        macro_columns=4,
        macro_rows=8,
        safe_top=24,
        safe_bottom=48,
        side_margin=16,
        description="Android-oriented grid with status and navigation bands.",
    ),
    "dense": GridProfile(
        name="dense",
        platform="ios/android",
        base_width=390,
        minor_step=4,
        major_every=4,
        macro_columns=4,
        macro_rows=8,
        safe_top=0,
        safe_bottom=0,
        side_margin=16,
        description="Dense 4pt measurement grid for small spacing disagreements.",
    ),
    "pixel": GridProfile(
        name="pixel",
        platform="ios/android",
        base_width=390,
        minor_step=1,
        major_every=8,
        macro_columns=4,
        macro_rows=8,
        safe_top=0,
        safe_bottom=0,
        side_margin=16,
        description="Pixel-exact 1px grid with 8px major lines for measuring tiny deltas.",
        scale_grid_steps=False,
    ),
}


def get_profile(name: str) -> GridProfile:
    """Return a named profile or raise a helpful error."""

    try:
        return PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown profile {name!r}; choose one of: {choices}") from exc


def list_profiles() -> tuple[GridProfile, ...]:
    """Return all available grid profiles in stable order."""

    return tuple(PROFILES[name] for name in sorted(PROFILES))
