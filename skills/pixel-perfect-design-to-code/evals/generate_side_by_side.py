"""Generate a side-by-side HTML report for inline Codex eval cases."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVALS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EVALS_ROOT))

from html_report import write_side_by_side_html
from mobile_grid_overlay.evals import load_answers_json, load_cases_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate HTML side-by-side eval report.")
    parser.add_argument("--cases", default=str(EVALS_ROOT / "cases.json"))
    parser.add_argument("--answers", default=str(EVALS_ROOT / "sample_answers.json"))
    parser.add_argument("--template", default=str(EVALS_ROOT / "prompts" / "mobile_visual_diff.md"))
    parser.add_argument("--out", default=str(EVALS_ROOT / "side_by_side.html"))
    parser.add_argument("--case-id", action="append", help="Only include this case id. Repeatable.")
    parser.add_argument(
        "--transcripts-dir",
        default=None,
        help="Optional live codex transcript directory to embed full agent dialogs.",
    )
    args = parser.parse_args(argv)

    cases = load_cases_json(Path(args.cases))
    if args.case_id:
        requested = set(args.case_id)
        cases = [case for case in cases if case.id in requested]
        missing = sorted(requested - {case.id for case in cases})
        if missing:
            raise SystemExit(f"case not found: {', '.join(missing)}")
    answers = load_answers_json(Path(args.answers))
    template = Path(args.template).read_text(encoding="utf-8")
    write_side_by_side_html(
        cases,
        template,
        Path(args.out),
        answers=answers,
        transcripts_dir=Path(args.transcripts_dir) if args.transcripts_dir else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
