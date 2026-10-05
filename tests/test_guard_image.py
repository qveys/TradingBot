import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from tradingbot.guard_image import (
    forbidden_imports,
    forbidden_in_project,
    forbidden_requirements,
    main,
)


class GuardImageTest(unittest.TestCase):
    def test_langgraph_and_llm_requirements_fail(self) -> None:
        self.assertEqual(
            forbidden_requirements("langgraph>=0.2\nopenai==1\nmypy\n"),
            ["langgraph", "openai"],
        )
        self.assertEqual(forbidden_requirements("LangChain-core==0.1\n"), ["langchain-core"])

    def test_vcs_and_editable_requirements_fail(self) -> None:
        line = "-e git+https://github.com/langchain-ai/langgraph.git\n"
        self.assertEqual(forbidden_requirements(line), ["langgraph", "langchain"])
        bare = "git+https://example.com/langgraph.git\n"
        self.assertEqual(forbidden_requirements(bare), ["langgraph"])

    def test_mypy_requirement_is_allowed(self) -> None:
        self.assertEqual(forbidden_requirements("mypy\n"), [])

    def test_langgraph_import_fails(self) -> None:
        self.assertEqual(forbidden_imports("import os\nimport langgraph\n"), ["langgraph"])
        self.assertEqual(
            forbidden_imports("from langchain_core import prompts\n"),
            ["langchain_core"],
        )
        self.assertEqual(
            forbidden_imports("import google.generativeai\n"),
            ["google.generativeai"],
        )
        self.assertEqual(forbidden_imports("import google.auth\n"), [])
        self.assertEqual(
            forbidden_imports('import importlib\nimportlib.import_module("langgraph")\n'),
            ["langgraph"],
        )
        self.assertEqual(forbidden_imports('exec("import langgraph")\n'), ["langgraph"])

    def test_syntax_error_is_not_an_llm_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "src" / "tradingbot"
            package.mkdir(parents=True)
            (package / "bad.py").write_text("def (\n", encoding="utf-8")
            self.assertEqual(forbidden_in_project(root), [])

    def test_project_has_no_llm_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(forbidden_in_project(root), [])

    def test_main_fails_when_a_requirement_names_langgraph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("langgraph==1\n", encoding="utf-8")
            err = io.StringIO()
            with redirect_stderr(err), self.assertRaises(SystemExit) as caught:
                main(root)
            self.assertEqual(caught.exception.code, 1)
            self.assertIn("langgraph", err.getvalue())


if __name__ == "__main__":
    unittest.main()
