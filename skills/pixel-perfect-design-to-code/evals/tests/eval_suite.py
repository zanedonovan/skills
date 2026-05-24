from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PIXEL_EVALS = Path(__file__).resolve().parents[1]
ROOT = PIXEL_EVALS.parents[2]

if str(PIXEL_EVALS) not in sys.path:
    sys.path.insert(0, str(PIXEL_EVALS))


def load_pixel_eval_module(module_name: str):
    module_path = PIXEL_EVALS / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"pixel_perfect_design_to_code_eval_{module_name}",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
