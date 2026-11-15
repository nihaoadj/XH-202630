"""Check statically identifiable imports at the repository's protected boundaries.

This is an import-edge check, not a proof about arbitrary Python execution or
transaction ownership. Composition roots and Services remain free to orchestrate.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ("core", "agents/shared", "api", "models", "db")


def beneath(target, namespace):
    return target == namespace or target.startswith(namespace + ".")


def violation(source, target):
    if beneath(target, "scripts"):
        return "SCRIPT_BACKDOOR"
    if source.startswith("api/"):
        if beneath(target, "app.agents"):
            return "API_AGENT_IMPORT"
        if any(beneath(target, prefix) for prefix in ("app.db", "sqlalchemy")):
            return "API_DATA_IMPORT"
        return "API_LLM_IMPORT" if beneath(target, "app.core.llm") else None
    if source.startswith(("models/", "db/")):
        if any(beneath(target, prefix) for prefix in ("app.api", "app.services", "app.agents")):
            return "MODEL_BUSINESS_IMPORT" if source.startswith("models/") else "DATA_BUSINESS_IMPORT"
        if source.startswith("models/") and any(beneath(target, prefix) for prefix in ("app.db", "sqlalchemy")):
            return "MODEL_DATA_IMPORT"
        return None
    if any(beneath(target, prefix) for prefix in ("app.api", "app.services")):
        return "SHARED_BUSINESS_IMPORT"
    if beneath(target, "app.agents") and not beneath(target, "app.agents.shared"):
        return "SHARED_WORKFLOW_IMPORT"
    return None


def load_exceptions(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"schema_version", "exceptions"} or data["schema_version"] != "1.0":
        raise ValueError("invalid exception manifest")
    result = {}
    for entry in data["exceptions"]:
        if set(entry) != {"source", "target", "reason", "remove_when"}:
            raise ValueError("exceptions require exact source, target, reason and remove_when")
        if any(not isinstance(value, str) or not value.strip() for value in entry.values()):
            raise ValueError("exception fields must be nonempty strings")
        source, target = entry["source"], entry["target"]
        if source.startswith("/") or ".." in Path(source).parts or "\\" in source or any(c in source + target for c in "*?["):
            raise ValueError("exception paths and targets must be exact")
        if not source.endswith(".py") or not any(source.startswith(prefix + "/") for prefix in PROTECTED):
            raise ValueError("exception source must be a protected Python module")
        if not violation(source, target):
            raise ValueError("exception does not describe a prohibited edge")
        key = (source, target)
        if key in result:
            raise ValueError("duplicate exception")
        result[key] = entry
    return result


def constant_string(node, constants):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = constant_string(node.left, constants), constant_string(node.right, constants)
        return left + right if left is not None and right is not None else None
    return None


def imports(tree, package):
    """Yield (line, target), including conservative dynamic import resolution."""
    modules = {"importlib": "importlib", "builtins": "builtins"}
    functions = {"__import__": "builtin"}
    assignments = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"importlib", "builtins"}:
                    modules[alias.asname or alias.name] = alias.name
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            for alias in node.names:
                if node.module == "importlib" and alias.name == "import_module":
                    functions[alias.asname or alias.name] = "importlib"
                if node.module == "builtins" and alias.name == "__import__":
                    functions[alias.asname or alias.name] = "builtin"
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
    constants = {}
    for _ in range(len(assignments) + 1):
        previous = (dict(constants), dict(functions), dict(modules))
        for name, values in assignments.items():
            if len(values) == 1:
                alias = values[0]
                if isinstance(alias, ast.Name):
                    if alias.id in functions:
                        functions[name] = functions[alias.id]
                    if alias.id in modules:
                        modules[name] = modules[alias.id]
                if isinstance(alias, ast.Attribute) and isinstance(alias.value, ast.Name):
                    module = modules.get(alias.value.id)
                    if module == "importlib" and alias.attr == "import_module":
                        functions[name] = "importlib"
                    if module == "builtins" and alias.attr == "__import__":
                        functions[name] = "builtin"
                value = constant_string(values[0], constants)
                if value is not None:
                    constants[name] = value
        if previous == (constants, functions, modules):
            break
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            try:
                target = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module or ""
            except (ValueError, ImportError):
                target = None
            yield node.lineno, target
            # "from app import services" must not hide an otherwise forbidden edge.
            if target:
                for alias in node.names:
                    if alias.name != "*":
                        yield node.lineno, target + "." + alias.name
        elif isinstance(node, ast.Call):
            kind = functions.get(node.func.id) if isinstance(node.func, ast.Name) else None
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                module = modules.get(node.func.value.id)
                if module == "importlib" and node.func.attr == "import_module":
                    kind = "importlib"
                elif module == "builtins" and node.func.attr == "__import__":
                    kind = "builtin"
            if not kind:
                continue
            keywords = {item.arg: item.value for item in node.keywords}
            name = node.args[0] if node.args else keywords.get("name")
            target = constant_string(name, constants)
            try:
                if target and kind == "importlib" and target.startswith("."):
                    anchor = node.args[1] if len(node.args) > 1 else keywords.get("package")
                    literal_package = constant_string(anchor, constants)
                    target = importlib.util.resolve_name(target, literal_package) if literal_package else None
                if target and kind == "builtin":
                    level = node.args[4] if len(node.args) > 4 else keywords.get("level", ast.Constant(value=0))
                    if not isinstance(level, ast.Constant) or not isinstance(level.value, int):
                        target = None
                    elif level.value:
                        target = importlib.util.resolve_name("." * level.value + target, package)
            except (ValueError, ImportError):
                target = None
            yield node.lineno, target


def scan(root, exceptions):
    diagnostics, used = [], set()
    if not (root / "app").is_dir():
        raise ValueError("backend root must contain app/")
    scanned = 0
    for prefix in PROTECTED:
        for path in sorted((root / "app" / prefix).rglob("*.py")):
            scanned += 1
            source = path.relative_to(root / "app").as_posix()
            module = path.relative_to(root).with_suffix("").parts
            package = ".".join(module[:-1])
            try:
                tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=source)
            except SyntaxError as exc:
                diagnostics.append((source, exc.lineno or 0, "SYNTAX_ERROR", ""))
                continue
            seen = set()
            covered = set()
            for line, target in imports(tree, package):
                if target is None:
                    diagnostics.append((source, line, "UNRESOLVED_DYNAMIC_IMPORT", ""))
                    continue
                code = violation(source, target)
                if not code:
                    continue
                # A from-import also yields the symbol; report/check its module once.
                if any(target.startswith(base + ".") and line == base_line for base_line, base in covered):
                    continue
                covered.add((line, target))
                key = (source, target)
                if key in exceptions:
                    used.add(key)
                elif (line, target) not in seen:
                    diagnostics.append((source, line, code, target))
                    seen.add((line, target))
    if not scanned:
        raise ValueError("no protected Python modules found")
    for source, target in sorted(set(exceptions) - used):
        diagnostics.append((source, 0, "UNUSED_EXCEPTION", target))
    return diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "backend")
    parser.add_argument("--exceptions", type=Path, default=ROOT / "tests/architecture-import-exceptions.json")
    args = parser.parse_args()
    try:
        exceptions = load_exceptions(args.exceptions)
        errors = scan(args.root, exceptions)
    except (ValueError, OSError, TypeError) as exc:
        print(f"ARCHITECTURE_CONFIG_ERROR: {exc}")
        return 2
    for source, line, code, target in errors:
        print(f"{source}:{line}: {code} {target}")
    if not errors:
        print(f"Architecture boundary PASS; {len(exceptions)} documented exceptions")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
