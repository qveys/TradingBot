"""Échoue si le garde-fou déclare ou importe un LLM ou LangGraph."""

import ast
import sys
import tomllib
from pathlib import Path

_EXACT = frozenset(
    {
        "openai",
        "anthropic",
        "litellm",
        "cohere",
        "mistralai",
        "groq",
        "ollama",
        "llama-cpp",
        "llama-cpp-python",
        "google-generativeai",
        "google-genai",
        "transformers",
    }
)
_NEEDLES = (
    "langgraph",
    "langchain",
    *_EXACT,
)
_IMPORT_ROOTS = ("google.generativeai", "google.genai", "llama_cpp")


def forbidden_requirements(text: str) -> list[str]:
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line == "":
            continue
        name = _package_name(line)
        if _is_forbidden(name):
            found.append(name)
            continue
        found.extend(_needles_in(line))
    return found


def forbidden_imports(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_forbidden(alias.name):
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if _module_forbidden(node.module):
                found.append(node.module)
        elif isinstance(node, ast.Call):
            _dynamic_import(node, found)
    return found


def forbidden_in_project(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.glob("requirements*.txt")):
        found.extend(forbidden_requirements(path.read_text(encoding="utf-8")))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        found.extend(_pyproject_dependencies(pyproject.read_text(encoding="utf-8")))
    package = root / "src" / "tradingbot"
    if package.is_dir():
        for path in sorted(package.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            try:
                found.extend(forbidden_imports(source))
            except SyntaxError:
                continue
    return found


def main(root: Path | None = None) -> None:
    project = Path(__file__).resolve().parents[2] if root is None else root
    found = forbidden_in_project(project)
    if found:
        print(
            "dépendance LLM ou LangGraph interdite : " + ", ".join(found),
            file=sys.stderr,
        )
        raise SystemExit(1)


def _pyproject_dependencies(text: str) -> list[str]:
    data = tomllib.loads(text)
    project = data.get("project", {})
    if not isinstance(project, dict):
        return []
    found: list[str] = []
    dependencies = project.get("dependencies", [])
    if isinstance(dependencies, list):
        for dep in dependencies:
            if isinstance(dep, str):
                found.extend(forbidden_requirements(dep))
    optional = project.get("optional-dependencies", {})
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                for dep in group:
                    if isinstance(dep, str):
                        found.extend(forbidden_requirements(dep))
    return found


def _dynamic_import(node: ast.Call, found: list[str]) -> None:
    name = _call_name(node.func)
    if not node.args:
        return
    code = node.args[0]
    if not isinstance(code, ast.Constant) or not isinstance(code.value, str):
        return
    if name in {"importlib.import_module", "import_module", "__import__"}:
        if _module_forbidden(code.value):
            found.append(code.value)
        return
    if name in {"exec", "eval"}:
        try:
            found.extend(forbidden_imports(code.value))
        except SyntaxError:
            return


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return None


def _module_forbidden(module: str) -> bool:
    lowered = module.lower()
    for root in _IMPORT_ROOTS:
        if lowered == root or lowered.startswith(root + "."):
            return True
    head = lowered.split(".", 1)[0].replace("_", "-")
    return _is_forbidden(head)


def _needles_in(line: str) -> list[str]:
    lowered = line.lower().replace("_", "-")
    return [needle for needle in _NEEDLES if needle in lowered]


def _package_name(requirement: str) -> str:
    name = requirement.strip().lower()
    for mark in "[=<>!~; ":
        name = name.split(mark, 1)[0]
    return name.replace("_", "-")


def _is_forbidden(name: str) -> bool:
    if name == "":
        return False
    head = name.split(".", 1)[0]
    if head.startswith("langgraph") or head.startswith("langchain"):
        return True
    return head in _EXACT


if __name__ == "__main__":
    main()
