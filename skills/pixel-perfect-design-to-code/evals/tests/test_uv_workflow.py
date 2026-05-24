from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


class UvWorkflowTests(unittest.TestCase):
    def test_user_facing_python_commands_use_uv_run(self) -> None:
        paths = [
            ROOT / "README.md",
            ROOT / "skills" / "pixel-perfect-design-to-code" / "evals" / "CODEX_INLINE.md",
            ROOT / "skills" / "pixel-perfect-design-to-code" / "skills" / "pixel-perfect-design-to-code" / "SKILL.md",
        ]

        for path in paths:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("python3 ", text)
                self.assertNotIn("python3\n", text)
                self.assertIn("uv run", text)


if __name__ == "__main__":
    unittest.main()
