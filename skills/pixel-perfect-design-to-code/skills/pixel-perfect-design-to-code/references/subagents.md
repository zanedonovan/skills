# Sub-Agent Delegation

Use this reference when a `/goal` run has multiple independent mismatch regions, code ownership is unclear, or a fast Spark pass can reduce the main pixel-perfect agent's context load.

## Activation Boundary

Skill bundles can include agent profile templates, but they do not register runtime Codex agents by themselves. To activate the bundled profiles, copy or sync the TOML files from `agents/` into `.codex/agents/` for the current project or `~/.codex/agents/` globally.

Bundled profiles:

- `pixel-spark-explorer`: read-only Spark agent for mapping visual artifacts to likely code ownership.
- `pixel-spark-worker`: Spark implementation agent for one bounded visual adjustment.
- `pixel-smart-reviewer`: read-only smart reviewer for iteration acceptance, stale state, and regression checks.

Keep the model locks in the TOML profiles. The Spark profiles must use `gpt-5.3-codex-spark`.

## Required Delegation Attempt

When the runtime agents are installed, the main pixel-perfect agent must attempt delegation for either of these cases:

- code ownership is unclear after the scorer/report artifacts are generated;
- there are two or more independent `M1`, `M2`, ... mismatch regions that can be investigated or patched separately.

If runtime agents are not installed or cannot be called in the host environment, continue locally and state that the bundled profiles were unavailable. Do not silently pretend a sub-agent reviewed or patched anything.

## Ownership Rules

The main agent owns:

- product intent and visual acceptance criteria;
- scorer/report commands;
- `.pixel-goal/state.md` freshness;
- score gate acceptance or rejection;
- conflict resolution and final user answer.

Sub-agents may inspect generated artifacts, map findings to code, propose focused fixes, or edit a narrow owned file set. They must not hand-edit `.pixel-goal/state.md`, metadata, masks, overlays, crops, screenshots, or reports.

Treat any worker diff that touches `.pixel-goal/**` as a rejected worker result. Regenerate those artifacts only through the scorer/report commands owned by the main agent.

## `/goal` Split

1. Main agent renders or receives the current screenshot.
2. Main agent runs the scorer and `goal_report.py --state-out .pixel-goal/state.md`.
3. Main agent delegates independent findings to `pixel-spark-explorer` when code ownership is unclear.
4. Main agent delegates one bounded patch to `pixel-spark-worker` only after assigning owned files and verification.
5. Main agent inspects the worker diff and rejects it if generated `.pixel-goal/**` artifacts changed.
6. Main agent rerenders, reruns scorer/report/state, and accepts the iteration only if the verified score improves without visible regression.
7. Main agent may ask `pixel-smart-reviewer` for a read-only review before accepting a high-risk iteration.

## Explorer Packet

```text
You are pixel-spark-explorer.

Question:
- Map finding <M-id/cells/point> to the most likely UI code ownership and fix direction.

Context:
- Goal/state: <paste relevant lines from .pixel-goal/state.md>
- Artifacts: <review_panel>, <side_by_side>, <boxes>, <zoom crop paths>
- Finding: <component, difference, evidence, expected code direction>

Scope:
- Read-only. Use fast search first.
- Do not read secret-like JSON/YAML configs or credentials.
- Do not edit files or generated .pixel-goal artifacts.

Return:
- Likely owning files/symbols.
- Evidence from artifacts and code.
- Proposed minimal fix direction.
- Unknowns.
- Fastest next check.
```

## Worker Packet

```text
You are pixel-spark-worker.

Mission:
- Implement one bounded visual fix: <specific component and pixel/design delta>.

Success criteria:
- The assigned visual mismatch should move toward the target without changing unrelated regions.
- Focused checks pass: <command/check>.

Owned write scope:
- <files/modules this worker may edit>

Read-only context:
- <state.md excerpt, artifact paths, relevant code paths>

Do not touch:
- .pixel-goal/** generated artifacts
- unrelated components
- secret-like JSON/YAML configs or credentials

Verification:
- Run: <command/check>
- If it fails, diagnose product code, test logic, or test infrastructure. Do not remove functionality just to pass tests.

Return:
- Changed paths.
- What changed and why.
- Verification result.
- Residual risk.
```

## Reviewer Packet

```text
You are pixel-smart-reviewer.

Review:
- Original /goal request and acceptance criteria.
- Latest .pixel-goal/state.md.
- Latest scorer metadata and report artifacts.
- Worker report and code diff.

Return findings first:
- P0/P1/P2/P3 issues with file/artifact references.
- State freshness check.
- Whether any `.pixel-goal/**` generated artifact was edited by hand or by a worker.
- Score verification and regression risk.
- Decision: accept | fix locally | send follow-up | reject.
```
