# Skills

Installable Agent Skills in this repository.

## Visual QA

- [`pixel-perfect-design-to-code`](pixel-perfect-design-to-code/) — compare target design screenshots against current UI implementation with grid overlays, diff artifacts, zoom crops, and goal-loop reporting.

## Add a skill

1. Create a workspace at `skills/<skill-name>/`.
2. Put installable skill bundles under `skills/<skill-name>/skills/<skill-name>/`.
3. Keep eval suites under `skills/<skill-name>/evals/`, including their `tests/`, fixtures, prompts, and generated reports.
4. Keep the skill bundle self-contained: paths inside `SKILL.md` should be relative to the installable skill root.
5. Put deterministic helpers in `scripts/`, on-demand docs in `references/`, reusable assets in `assets/`, and optional Codex sub-agent profiles in `agents/`.
6. Add the skill to this index and cover its structure in that skill workspace's eval tests.
