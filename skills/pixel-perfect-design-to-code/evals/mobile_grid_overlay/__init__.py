"""Reusable screenshot grid overlays for mobile visual-diff evals."""

from .profiles import GridProfile, get_profile, list_profiles
from .svg import render_grid_layers, render_grid_svg

__all__ = [
    "GridProfile",
    "get_profile",
    "list_profiles",
    "render_grid_layers",
    "render_grid_svg",
]
