"""Prove the boundary check fails for real import mutations, not only this tree."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("architecture_gate", ROOT / "scripts/check_architecture.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.mark.parametrize("source,code", [
    ("core/example.py", "import app.services.generation.jobs"),
    ("core/example.py", "from ..services.generation import jobs"),
    ("core/example.py", "from .. import services"),
    ("core/example.py", "def f():\n    from app.api import dependencies"),
    ("core/example.py", "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import app.services.foo"),
    ("agents/shared/example.py", "from ..resource_workflows import learning_documents"),
    ("api/example.py", "from ..agents.resource_workflows import learning_documents"),
    ("api/example.py", "from app.db.courseware import repository"),
    ("api/example.py", "from sqlalchemy import select"),
    ("api/example.py", "from app.core.llm import gateway"),
    ("models/example.py", "from app.db.learners import mastery"),
    ("models/example.py", "from sqlalchemy.orm import Session"),
    ("models/example.py", "from app.services.learners import mastery"),
    ("models/example.py", "from app.agents.learning_agents import feedback_agent"),
    ("models/example.py", "from app.api import dependencies"),
    ("db/example.py", "from app.services.courseware import CoursewareService"),
    ("db/example.py", "from app.api import dependencies"),
    ("db/example.py", "from app.agents.learning_agents import feedback_agent"),
    ("db/example.py", "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.services import feedback"),
    ("models/example.py", "from importlib import import_module\nimport_module('app.db.learners')"),
    ("core/example.py", "import importlib as loader\nloader.import_module('app.services.foo')"),
    ("core/example.py", "from importlib import import_module as load\nload('app.' + 'services.foo')"),
    ("core/example.py", "from importlib import import_module as load\nNAME = 'app.services.foo'\nload(NAME)"),
    ("core/example.py", "from importlib import import_module\nimport_module('..services.foo', 'app.core')"),
    ("core/example.py", "__import__('app.api.foo')"),
    ("core/example.py", "load = __import__\nload('app.services.foo')"),
    ("core/example.py", "import importlib\nloader = importlib\nload = loader.import_module\nload('app.services.foo')"),
    ("core/example.py", "import builtins as b\nb.__import__('services.foo', level=2)"),
    ("core/example.py", "from importlib import import_module\ndef f(name):\n    return import_module(name)"),
    ("core/example.py", "import scripts.courseware_harness.offline"),
])
def test_prohibited_edges_are_rejected(tmp_path, source, code):
    path = tmp_path / "app" / source
    path.parent.mkdir(parents=True)
    path.write_text(code, encoding="utf-8")
    assert gate.scan(tmp_path, {})


def test_allowed_dependencies_and_composition_are_not_banned(tmp_path):
    for source, code in {
        "core/example.py": "from app.models.shared import persistence\nfrom app.db.audit import base\nfrom . import other",
        "api/example.py": "from app.services.generation import jobs\nfrom app.api import dependencies",
        "models/example.py": "from app.models.shared import persistence\nfrom app.core.learning_tiers import tier_for_level",
        "db/example.py": "from app.models.learners import mastery\nfrom app.config import get_settings\nfrom app.core import execution",
        "services/example.py": "from app.agents.resource_workflows import learning_documents",
        "containers.py": "from app.agents.resource_workflows import learning_documents",
    }.items():
        path = tmp_path / "app" / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
    assert gate.scan(tmp_path, {}) == []


def test_exact_exception_cannot_hide_a_different_target_or_become_stale(tmp_path):
    path = tmp_path / "app/core/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("from scripts.harness import run", encoding="utf-8")
    exceptions = {("core/example.py", "scripts.harness"): {}}
    assert gate.scan(tmp_path, exceptions) == []
    path.write_text("from scripts.another import run", encoding="utf-8")
    assert {row[2] for row in gate.scan(tmp_path, exceptions)} == {"SCRIPT_BACKDOOR", "UNUSED_EXCEPTION"}


@pytest.mark.parametrize("patch", [{"target": "scripts.*"}, {"reason": ""}, {"remove_when": ""}, {"source": "../core/a.py"}])
def test_unbounded_or_undocumented_exceptions_fail(tmp_path, patch):
    entry = {"source": "core/a.py", "target": "scripts.harness", "reason": "legacy", "remove_when": "callers migrated", **patch}
    manifest = tmp_path / "exceptions.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "exceptions": [entry]}), encoding="utf-8")
    with pytest.raises(ValueError):
        gate.load_exceptions(manifest)


def test_cli_failure_cannot_be_reported_as_pass(tmp_path):
    path = tmp_path / "app/api/bad.py"
    path.parent.mkdir(parents=True)
    path.write_text("import app.agents.resource_agents", encoding="utf-8")
    exceptions = tmp_path / "exceptions.json"
    exceptions.write_text('{"schema_version":"1.0","exceptions":[]}', encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_architecture.py"),
                             "--root", str(tmp_path), "--exceptions", str(exceptions)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "API_AGENT_IMPORT" in result.stdout
