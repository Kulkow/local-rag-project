"""Keep domain/application modules independent of adapters and frameworks."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "app"


def test_inner_layers_do_not_import_frameworks_or_adapters() -> None:
    forbidden = {
        "fastapi",
        "sqlalchemy",
        "celery",
        "httpx",
        "redis",
        "pydantic",
        "langchain",
        "langgraph",
        "qdrant_client",
        "boto3",
        "botocore",
        "pypdf",
    }
    for path in (ROOT / "modules").rglob("*.py"):
        if not {"domain", "application"}.intersection(path.relative_to(ROOT).parts):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"Use explicit imports in {path}"
                imports = [node.module or ""]
            for module in imports:
                parts = module.split(".")
                assert parts[0] not in forbidden, (path, module)
                assert not {"infrastructure", "api", "core", "main"}.intersection(parts), (
                    path,
                    module,
                )
                if "domain" in path.relative_to(ROOT).parts:
                    assert "application" not in parts, (path, module)
