from __future__ import annotations

import os
from pathlib import Path

import pytest


EVAL_TEST_FILES = {
    "test_codex_exec_runner.py",
    "test_evals.py",
    "test_eval_workflow_cli.py",
    "test_fixture_generation.py",
    "test_goal_report.py",
    "test_goal_workflow.py",
    "test_grid_svg.py",
    "test_html_report.py",
    "test_skill_structure.py",
    "test_uv_workflow.py",
}


INTEGRATION_TEST_NAMES = {
    "test_raster_png_jpg_run_writes_agent_review_layers",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path = Path(str(item.path))
        if path.name in EVAL_TEST_FILES or "tests/evals" in path.as_posix():
            item.add_marker(pytest.mark.eval)
            if item.name in INTEGRATION_TEST_NAMES:
                item.add_marker(pytest.mark.integration)
            elif item.get_closest_marker("integration") is None and item.get_closest_marker("live") is None:
                item.add_marker(pytest.mark.fast)

        if item.get_closest_marker("live") and not os.environ.get("RUN_LIVE_EVALS"):
            item.add_marker(pytest.mark.skip(reason="set RUN_LIVE_EVALS=1 to run live evals"))
