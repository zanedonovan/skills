"""Deterministic contract checks for the pixel-perfect skill workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PIXEL_SKILL_NAME = "pixel-perfect-design-to-code"
PIXEL_STATE_PATH = ".pixel-goal/state.md"
PIXEL_SUBAGENTS = (
    "pixel-spark-explorer",
    "pixel-spark-worker",
    "pixel-smart-reviewer",
)

_CALL_KIND_TERMS = ("tool", "agent", "subagent", "function_call")
_CALL_NAME_KEYS = ("name", "tool", "tool_name", "recipient_name", "agent", "subagent")
_EVENT_KIND_KEYS = ("type", "event", "kind", "item_type")
_IGNORED_TOOL_NAMES = {"update_plan"}


@dataclass(frozen=True)
class ContractResult:
    passed: bool
    errors: tuple[str, ...]
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActivationCase:
    prompt: str
    should_activate: bool
    reason: str


def activation_eval_cases() -> tuple[ActivationCase, ...]:
    return (
        ActivationCase(
            prompt="Use pixel-perfect-design-to-code to compare target and implementation screenshots.",
            should_activate=True,
            reason="explicit skill invocation for visual screenshot comparison",
        ),
        ActivationCase(
            prompt="/goal match this Figma mock to the current mobile implementation screenshot.",
            should_activate=True,
            reason="implicit /goal pixel-perfect convergence request",
        ),
        ActivationCase(
            prompt="Find M1/M2 visual mismatches from boxes and zoom crops, then suggest code fixes.",
            should_activate=True,
            reason="artifact vocabulary specific to the skill",
        ),
        ActivationCase(
            prompt="Format this Python project with ruff and fix import ordering.",
            should_activate=False,
            reason="Python formatting is outside screenshot visual matching",
        ),
        ActivationCase(
            prompt="Create a spreadsheet summarizing monthly revenue by region.",
            should_activate=False,
            reason="spreadsheet generation is outside the skill",
        ),
        ActivationCase(
            prompt="Summarize README.md and suggest documentation headings.",
            should_activate=False,
            reason="plain document review should not trigger visual diff tooling",
        ),
    )


def expected_activation(prompt: str) -> bool:
    """Local trigger oracle for deterministic activation-boundary eval cases."""
    text = prompt.casefold()
    positive_terms = (
        PIXEL_SKILL_NAME,
        "/goal",
        "pixel-perfect",
        "figma mock",
        "design mock",
        "implementation screenshot",
        "visual mismatches",
        "zoom crops",
        "m1/m2",
    )
    negative_terms = (
        "ruff",
        "spreadsheet",
        "revenue",
        "readme",
        "documentation",
    )
    if any(term in text for term in negative_terms):
        return False
    return any(term in text for term in positive_terms)


def grade_activation_trace(
    trace: list[dict[str, Any]],
    *,
    skill_name: str = PIXEL_SKILL_NAME,
    should_activate: bool = True,
) -> ContractResult:
    """Require structural trace proof for skill activation decisions."""
    evidence = tuple(_activation_evidence(trace, skill_name=skill_name))
    if should_activate and not evidence:
        return ContractResult(
            passed=False,
            errors=(f"missing actual skill activation trace: {skill_name}",),
        )
    if not should_activate and evidence:
        return ContractResult(
            passed=False,
            errors=(f"unexpected skill activation trace: {skill_name}",),
            evidence=evidence,
        )
    return ContractResult(passed=True, errors=(), evidence=evidence)


def grade_subagent_trace(
    trace: list[dict[str, Any]],
    *,
    required_agents: tuple[str, ...],
) -> ContractResult:
    found: list[str] = []
    for event in trace:
        found.extend(_actual_call_names(event))
    missing = tuple(agent for agent in required_agents if agent not in found)
    if missing:
        return ContractResult(
            passed=False,
            errors=tuple(f"missing actual sub-agent call: {agent}" for agent in missing),
            evidence=tuple(found),
        )
    return ContractResult(passed=True, errors=(), evidence=tuple(found))


def grade_resume_trace_reads_state_first(
    trace: list[dict[str, Any]],
    *,
    state_path: str = PIXEL_STATE_PATH,
) -> ContractResult:
    actions = [event for event in trace if _is_action_event(event)]
    if not actions:
        return ContractResult(
            passed=False,
            errors=("no tool/action events found after resume",),
        )
    first = actions[0]
    if _event_reads_state(first, state_path):
        return ContractResult(
            passed=True,
            errors=(),
            evidence=(_event_summary(first),),
        )
    return ContractResult(
        passed=False,
        errors=(f"first action after resume did not read {state_path}",),
        evidence=(_event_summary(first),),
    )


def _activation_evidence(trace: list[dict[str, Any]], *, skill_name: str) -> list[str]:
    evidence: list[str] = []
    for event in trace:
        if _is_skill_activation_event(event, skill_name=skill_name):
            evidence.append(_event_summary(event))
    return evidence


def _is_skill_activation_event(event: dict[str, Any], *, skill_name: str) -> bool:
    flat = _flatten_strings(event).casefold()
    skill = skill_name.casefold()
    if skill not in flat and f"/{skill}/skill.md" not in flat:
        return False

    role = str(event.get("role", "")).casefold()
    kind_text = " ".join(
        str(event.get(key, "")).casefold()
        for key in _EVENT_KIND_KEYS
        if isinstance(event.get(key), str)
    )
    structural_text = " ".join(
        (
            kind_text,
            " ".join(str(key).casefold() for key in event.keys()),
            str(event.get("name", "")).casefold(),
            str(event.get("path", "")).casefold(),
        )
    )
    if role in {"assistant", "user"} and "skill" not in structural_text:
        return False
    return "skill" in structural_text


def _actual_call_names(event: dict[str, Any]) -> list[str]:
    kind_text = " ".join(
        str(event.get(key, "")).casefold()
        for key in _EVENT_KIND_KEYS
        if isinstance(event.get(key), str)
    )
    if not any(term in kind_text for term in _CALL_KIND_TERMS):
        return []

    names: list[str] = []
    for key in _CALL_NAME_KEYS:
        value = event.get(key)
        if isinstance(value, str):
            names.append(value)
    for nested_key in ("call", "tool_call", "function", "payload"):
        nested = event.get(nested_key)
        if isinstance(nested, dict):
            names.extend(_actual_call_names({"type": kind_text, **nested}))
    return names


def _is_action_event(event: dict[str, Any]) -> bool:
    names = _actual_call_names(event)
    if any(name in _IGNORED_TOOL_NAMES for name in names):
        return False
    if names:
        return True
    kind_text = " ".join(
        str(event.get(key, "")).casefold()
        for key in _EVENT_KIND_KEYS
        if isinstance(event.get(key), str)
    )
    return any(term in kind_text for term in ("exec", "shell", "file", "tool"))


def _event_reads_state(event: dict[str, Any], state_path: str) -> bool:
    text = _flatten_strings(event).casefold()
    state = state_path.casefold()
    if state not in text:
        return False
    read_terms = ("read", "cat", "sed", "open", "fetch", "state.md")
    return any(term in text for term in read_terms)


def _event_summary(event: dict[str, Any]) -> str:
    text = _flatten_strings(event)
    return " ".join(text.split())[:240]


def _flatten_strings(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_strings(item) for item in value.values())
    if isinstance(value, list | tuple):
        return " ".join(_flatten_strings(item) for item in value)
    return ""
