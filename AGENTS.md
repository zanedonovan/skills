# Project Agent Instructions

## Must

- Do not add commit watermarks such as "Generated with Codex", "Co-Authored-By: Codex", or similar footers.
- Evaluate tests from the feature goal, not from the internal style of the tests.
- If tests fail, diagnose why. If a test exposes a product or skill bug, fix the code. If the failure is test infrastructure, fix the infrastructure. Do not remove requested functionality just to make tests pass.

## Never

- Never read JSON/YAML config or secret files such as `settings.json`, `settings.yaml`, `*.prod.json`, `*.dev.json`, `.config/*.json`, `secrets.*`, or `credentials.*`.
- Reading eval data files such as case manifests, answer fixtures, grading artifacts, and benchmark outputs is allowed when working on the eval harness.

## Eval Workflow

- When working on evals, review them from the target skill's user promise and success criteria, not from test-code aesthetics.
- Keep the eval infrastructure pytest-native.
- Treat pytest as the orchestration layer for local gates; helper scripts such as `evals/<skill-name>/run_evals.py` and `evals/<skill-name>/run_codex_exec.py` may still implement grading or live capture underneath.
- Use pytest markers for eval layers: `eval`, `fast`, `integration`, and `live`.
- Run deterministic/local eval checks through pytest, for example `uv run python -m pytest tests -m "eval and fast"`.
- Run local artifact/workflow checks through pytest, for example `uv run python -m pytest tests -m "eval and integration"`.
- Run live/model evals only behind `RUN_LIVE_EVALS=1`, for example `RUN_LIVE_EVALS=1 uv run python -m pytest tests/evals -m "eval and live"`.
- Do not make live/model evals part of the default test target.
- In compare mode, every selected case must include both `with_skill` and `without_skill`; missing baselines are invalid eval runs, not passing `with_skill`-only results.
- Baseline comparisons must isolate the intended variable. Do not attribute an improvement to the skill when `with_skill` and `without_skill` received different inputs, artifacts, tools, model settings, or context.
- Preserve traces, grading evidence, benchmark outputs, and produced artifacts so failures can be debugged later.
- Prefer deterministic assertions for mechanical facts: JSON shape, files, schemas, coordinates, dimensions, score metadata, hashes, and command exit status.
- Use model or human judging only for semantic, visual, writing, or holistic quality where script checks are insufficient.
- Do not hard-code fixes just to satisfy current eval cases. Improve the skill, bundled resources, prompt, grader, or harness based on root cause.
- Keep one-shot diagnosis evals separate from `/goal` loop evals. A visual-diff answer suite does not prove iterative patch/rerender/report behavior by itself.
- `/goal` evals should assert final state and artifacts: iteration folders, scorer-provenance metadata, hashes, score gates, rejected regressions, `state.md`, and HTML report output.

## Working Style

- Make surgical changes: touch only files needed for the requested task.
- Do not refactor unrelated code or clean up unrelated existing changes.
- If the worktree is dirty, assume unrelated changes belong to the user and do not revert them.
- Prefer the existing project patterns and commands.
