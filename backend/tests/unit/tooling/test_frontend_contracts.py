"""Versioned redacted wire fixtures and deterministic exports use actual DTOs."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("frontend_contract_export", ROOT / "scripts/export_frontend_contracts.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def test_exports_are_deterministic_and_fixtures_match_server_models():
    assert exporter.build_outputs() == exporter.build_outputs()
    models = {model.__name__: model for model in exporter.MODELS}
    fixture = json.loads((ROOT / "tests/contracts/v1.json").read_text(encoding="utf-8"))
    assert fixture["schema_version"] == "1.0"
    for name, payload in fixture["models"].items():
        models[name].model_validate(payload)
    with pytest.raises(ValidationError):
        models["GenerationJobStatusResponse"].model_validate({**fixture["models"]["GenerationJobStatusResponse"], "job_status": "interrupted"})
    with pytest.raises(ValidationError):
        models["ReportInvalidation"].model_validate({**fixture["models"]["ReportInvalidation"], "window_days": 14})
    assert "any" not in exporter.build_outputs()["contracts.d.ts"].split()


def test_check_reports_drift_and_does_not_rewrite(tmp_path):
    outputs = exporter.build_outputs()
    for name, value in outputs.items():
        (tmp_path / name).write_bytes(value.encode("utf-8"))
    command = [sys.executable, str(ROOT / "scripts/export_frontend_contracts.py"), "--output", str(tmp_path), "--check"]
    assert subprocess.run(command, capture_output=True).returncode == 0
    changed = tmp_path / "contracts.d.ts"
    changed.write_bytes(changed.read_bytes() + b"// injected drift\n")
    before = changed.read_bytes()
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1 and "CONTRACT_DRIFT: contracts.d.ts" in result.stdout
    assert changed.read_bytes() == before


def test_unsupported_schema_structure_is_not_silently_erased():
    with pytest.raises(ValueError, match="unsupported"):
        exporter.typescript({"type": "array", "prefixItems": [{"type": "string"}]})
